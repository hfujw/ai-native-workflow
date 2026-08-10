# 多 Agent 演化全景

> Phase 1-5 已完成 ✅ | Redis 已实现（StateBackend 一行切换：STATE_BACKEND=redis）  
> Phase 1 已单独成文档：`docs/records/multi-agent-phase1-render.md`

---

## 演化概览

```
Phase 1        Phase 2          Phase 3          Phase 4            Phase 5
render Agent   designer Agent   researcher Agent  消息总线           分布式
   │               │                │               │                  │
   │  外表不动      │  合并2个工具    │  搜索自主决策    │  Agent互相对话     │  Redis Stream
   │  内部循环      │  design+compose │  换词/评估/兜底  │  Supervisor变薄    │  多worker
   │               │                │               │                  │
   ▼               ▼                ▼               ▼                  ▼
┌──────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ 1 个 │    │  2 个     │    │  3 个     │    │  3 个     │    │  3 个     │
│ Agent│    │  Agent    │    │  Agent    │    │  Agent    │    │  Agent    │
│      │    │           │    │           │    │  + 消息总线│    │  + Redis  │
│ 改 1  │    │  改 2 个   │    │  改 1 个   │    │  改通信层  │    │  改配置    │
│ 文件  │    │  文件      │    │  文件      │    │           │    │           │
└──────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
```

---

## Phase 2：Designer Agent（合并 design + compose）

### 为什么合并

`tool_design` 和 `tool_compose` 是强耦合的：

```
design 输出: {"components": ["timeline", "cards"], ...}
    ↓ 直接喂给
compose 输出: {"title": "...", "blocks": [...]}
```

分开时，design 选了不合适的叙事形式，compose 只能硬写。合并后 Agent 可以：
- 设计形式 → 试写文案 → 发现形式不合适 → 换形式 → 重写
- 这个循环在当前架构里要跑两轮 orchestrator 循环，Agent 化后内部解决

### 结构

```python
class DesignerAgent:
    async def run(self, material, user_input, push=None, session_records=None) -> dict:
        # 内部循环
        for attempt in range(2):
            design = await self._design(material, user_input, session_records)
            # 自检：选择的组件数和素材量匹配吗？
            self_check = self._check_design_fit(design, material)
            if not self_check["ok"]:
                continue  # 素材不够撑 timeline，换成 encyclopedia

            content = await self._compose(material, design, user_input, session_records)
            # 自检：来源覆盖率 > 50%？
            if self._source_coverage(content) >= 0.5:
                return {"design": design, "content": content, "attempts": attempt + 1}

        # 降级：百科条目 + 诚实文案
        return self._fallback(material, user_input)
```

### 文件变更

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `agents/designer_agent.py` | DesignerAgent 类 |
| 修改 | `agents/orchestrator.py` | `_execute_tool` 里 design/compose 两个分支合并为一个 |
| 保留 | `tools/design.py`, `tools/compose.py` | Agent 内部调用，不删 |

### orchestrator 改动

```python
# 之前：两个步骤
elif tool_name == "design":
    result = await tool_design(...)
elif tool_name == "compose":
    result = await tool_compose(...)

# 之后：一步
elif tool_name == "design":
    result = await designer_agent.run(
        ctx["material"], ctx["user_input"],
        push=ctx.get("_push"),
        session_records=ctx.get("cost_records"),
    )
    ctx["design"] = result.get("design")
    ctx["content"] = result.get("content")
```

---

## Phase 3：Researcher Agent（搜索升级）

### 为什么升级

当前 `tool_search` 搜一次就返回——搜不到就空着，等 orchestrator 再调一次。这个"重搜"决策目前在 LLM（`_decide` 里），不在搜索本身。

Researcher Agent 自己决定：
- 搜几次
- 换什么词
- 什么时候该停（连续 2 次搜空）
- 什么时候用语义向量兜底

### 结构

```python
class ResearcherAgent:
    async def run(self, topic, existing_material, push=None, session_records=None) -> dict:
        material = list(existing_material) if existing_material else []

        for attempt in range(3):
            # 1. 决定搜什么词（第一次用原词，后续换角度）
            query = self._pick_query(topic, attempt, material)

            # 2. 搜
            results = await tool_search(query, existing_material=material)
            material.extend(results.get("results", []))

            # 3. 评估
            evaluation = evaluate_material(material, topic)
            if evaluation["level"] == "high":
                break
            if evaluation["level"] == "none" and attempt >= 1:
                break  # 连续 2 次搜空，不搜了

            # 4. 语义向量兜底（只在第一轮搜索失败后触发）
            if attempt == 0 and evaluation["level"] in ("low", "none"):
                kb_hits = self._vector_fallback(topic)
                material.extend(kb_hits)

        return {"tool": "search", "results": material, "count": len(material),
                "level": evaluation["level"]}
```

### 文件变更

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `agents/researcher_agent.py` | ResearcherAgent 类 |
| 修改 | `agents/orchestrator.py` | `_execute_tool` 里 search 分支改为调 Agent |
| 保留 | `tools/search.py` | Agent 内部调用 `_search_tavily` |

---

## Phase 4：消息总线（Agent 互相对话）

### 这是最大的一次架构变更

前三个 Phase 里，Agent 之间还是串行的——orchestrator 调完一个再调下一个。Phase 4 让 Agent 能直接通信。

### 架构对比

```
Phase 1-3（串行调度）：              Phase 4（消息总线）：

orchestrator                        Supervisor（只管启动+终止）
    │                                    │
    ├── researcher.run()                 ├── 创建消息总线
    ├── designer.run()                   ├── 启动 3 个 Agent
    └── renderer.run()                   └── 等待完成信号
                                         │
                                    消息总线 (asyncio.Queue × N)
                                     Researcher ←→ Designer ←→ Renderer
```

### 消息总线实现

```python
# agents/message_bus.py
import asyncio

class MessageBus:
    """进程内消息总线——每个 Agent 有自己的收件箱。"""

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}

    def register(self, agent_name: str):
        self._queues[agent_name] = asyncio.Queue()

    async def send(self, target: str, msg: dict):
        """给某个 Agent 发消息。"""
        await self._queues[target].put(msg)

    async def recv(self, agent_name: str) -> dict:
        """当前 Agent 收消息（阻塞）。"""
        return await self._queues[agent_name].get()
```

### Agent 通信示例

```python
# Researcher 搜完后：素材不够，主动通知 Designer
await bus.send("designer", {
    "type": "material_ready",
    "level": "low",
    "material": [...] ,
    "hint": "素材不足，请用百科全书形式"
})

# Designer 设计时：发现缺少时间线数据，让 Researcher 再搜
await bus.send("researcher", {
    "type": "need_more",
    "query": "秦始皇 修建长城 时间线",
    "reason": "timeline 组件需要具体年份"
})
```

### Supervisor 变薄

```python
# agents/supervisor.py
class Supervisor:
    async def run(self, user_input, push) -> dict:
        bus = MessageBus()
        bus.register("researcher")
        bus.register("designer")
        bus.register("renderer")

        # 启动 3 个 Agent 作为后台任务
        tasks = [
            asyncio.create_task(ResearcherAgent(bus).run()),
            asyncio.create_task(DesignerAgent(bus).run()),
            asyncio.create_task(RendererAgent(bus).run()),
        ]

        # 发启动消息
        await bus.send("researcher", {"type": "start", "topic": user_input})

        # 等所有完成，或预算超限
        done, pending = await asyncio.wait(tasks, timeout=settings.generation_timeout)
        for t in pending:
            t.cancel()

        # 收集结果
        return self._collect_results(bus)
```

### 文件变更

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `agents/message_bus.py` | MessageBus 类 |
| 新建 | `agents/supervisor.py` | Supervisor 替代 orchestrator 主循环 |
| 修改 | `agents/orchestrator.py` | 降级为兼容层，或者直接废弃 |
| 修改 | `agents/researcher_agent.py` | 改为读取 bus 消息驱动 |
| 修改 | `agents/designer_agent.py` | 同上 |
| 修改 | `agents/render_agent.py` | 同上 |

---

## Phase 5：分布式（Redis Stream）

### 为什么要分布式

Phase 4 的 asyncio.Queue 是进程内的——一个 Supervisor + 3 个 Agent 都在同一个 Python 进程里。

如果用户量上来（日活 > 50），一个进程不够：
- 单进程同时只能跑一个生成请求
- 第二个用户要点"生成"，得等第一个跑完

### 解决方案

把 Agent 从"线程/协程"变成"独立进程"。消息总线从 asyncio.Queue 换成 Redis Stream：

```
Worker 1: Supervisor A               Worker 2: Supervisor B
              │                                  │
              └──────────┬───────────────────────┘
                         │
                    Redis Stream
                    (消息总线)
                         │
              ┌──────────┼──────────┐
              │          │          │
         Researcher  Designer   Renderer
         (独立进程)  (独立进程)  (独立进程)
```

### 代码改动

```python
# 改之前（Phase 4）
bus = MessageBus()  # asyncio.Queue

# 改之后（Phase 5）
bus = RedisStreamBus(redis_url="redis://localhost:6379")
```

Agent 代码一行不改——只换 MessageBus 实现。这就是为什么 Phase 1-4 要一直用 MessageBus 抽象。

### 部署

```yaml
# docker-compose.yml
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    deploy:
      replicas: 2              # 2 个 Supervisor worker
  redis:
    image: redis:7-alpine
  researcher:
    build: ./backend
    command: python -m app.agents.researcher_worker
    deploy:
      replicas: 2
  designer:
    build: ./backend
    command: python -m app.agents.designer_worker
    deploy:
      replicas: 2
  renderer:
    build: ./backend
    command: python -m app.agents.renderer_worker
    deploy:
      replicas: 1              # render 最贵，限制并发
```

这就是 `CUTS.md` 里说的"Redis 改一行配置"的实际含义。

---

## 演进节奏

| Phase | 工作量 | 风险 | 上线？ |
|-------|--------|------|--------|
| 1: Render Agent | 半天 | 低——外表不动，orchestrator 无感 | 改完就上 |
| 2: Designer Agent | 一天 | 中——改 orchestrator 调用链 | 改完就上 |
| 3: Researcher Agent | 半天 | 低——接口没变 | 改完就上 |
| 4: 消息总线 | 两天 | 高——通信模式变更 | 需要充分测试 |
| 5: Redis 分布式 | 一天 | 低——只改配置，Agent 代码不动 | 有用户量再上 |

**Phase 1-3 是"优化现有"——每一版都能上线。Phase 4 是"架构变更"——需要单独测试。Phase 5 是"运维动作"——不改业务逻辑。**
