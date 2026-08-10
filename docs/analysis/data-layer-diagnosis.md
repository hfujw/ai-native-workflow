# 数据层深度诊断

> 2026-08-08  
> 当前状态：无持久化（设计选择，有意识地接受）、内存限流、ChromaDB 只读、StateBackend 闲置

---

## 1. "无持久化"诊断

### 是设计选择还是技术债？

**设计选择。** 当前项目定位是"实时策展生成 HTML 页面"——每次生成是独立会话，生成结果通过 WebSocket 实时推送给用户。没有"保存历史"的用户需求。类比 ChatGPT 早期版本——对话结束后不可回溯。

但以下场景需要持久化：
- 用户想查看历史生成记录
- Demo 页面预生成后需要持久保存
- 限流计数器需要跨进程共享

### 3 种持久化方案对比

| 维度 | SQLite | JSON 文件 | Redis |
|------|--------|----------|-------|
| **实现成本** | 低（Python 内置 `sqlite3`） | 极低（`json.dump`） | 中（需要 Redis 服务） |
| **依赖** | 零（标准库） | 零 | Redis 服务器 |
| **并发安全** | 写锁（WAL 模式可读并发） | 无锁（竞态风险） | 单线程原子操作 |
| **查询能力** | SQL 全功能 | 无（只能全量加载） | 有限（key-value） |
| **数据一致性** | ACID 事务 | 无保证 | 单操作原子，多操作需 Lua |
| **备份难度** | 低（复制 .db 文件） | 低（复制 .json 文件） | 中（RDB/AOF 配置） |
| **迁移难度** | 低（SQL 导出） | 低（JSON 通用格式） | 中（需 Redis 客户端） |
| **适合场景** | 历史记录、用户设置 | Demo 页面、配置 | 限流、缓存、Session |
| **不适合场景** | 高频写入（<100 QPS OK） | 大批量数据、并发写 | 复杂查询、大 value |

### 推荐组合方案

```
SQLite     ← 用户生成历史（按 session_id 索引）
JSON 文件  ← Demo 页面（已经这样做了）
Redis      ← 限流计数器 + 会话缓存（未来）
```

### 实现 SQLite 历史记录（最小可行实现）

```python
# backend/app/data/history.py
import sqlite3
import json
from datetime import datetime

DB_PATH = "data/history.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS generations (
                session_id TEXT PRIMARY KEY,
                user_input TEXT NOT NULL,
                user_ip TEXT,
                html_content TEXT,
                status TEXT,
                steps INTEGER,
                cost_rmb REAL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_created ON generations(created_at)")

def save_generation(session_id, user_input, user_ip, html, status, steps, cost):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO generations VALUES (?,?,?,?,?,?,?,datetime('now'))",
            (session_id, user_input, user_ip, html, status, steps, cost),
        )

def get_history(limit=50):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row) for row in
            conn.execute("SELECT session_id, user_input, status, steps, cost_rmb, created_at FROM generations ORDER BY created_at DESC LIMIT ?", (limit,))
        ]

def get_by_id(session_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM generations WHERE session_id=?", (session_id,)).fetchone()
        return dict(row) if row else None
```

---

## 2. RateLimiter 零迁移成本改进

### 方案 A：定期持久化到文件（5 行代码）

```python
# rate_limiter.py —— 在 record_success 和 record_cost 后追加
import json, os

DUMP_PATH = "data/rate_limit_state.json"

async def _dump_to_file(self):
    async with self._lock:
        with open(DUMP_PATH, "w") as f:
            json.dump({
                "today": self._today,
                "trials": self._successful_trials,
                "spent": self._daily_spent,
                "total": self._total_generations,
            }, f)

async def _load_from_file(self):
    if os.path.exists(DUMP_PATH):
        with open(DUMP_PATH) as f:
            data = json.load(f)
            if data.get("today") == str(date.today()):
                self._successful_trials = data["trials"]
                self._daily_spent = data["spent"]
                self._total_generations = data["total"]
```

**收益**：服务重启后限流数据不丢失（同一天内）。**成本**：5 行代码，零依赖。

### 方案 B：IP 哈希分片（分布式友好）

```python
# 不需要——当前单机够用，未来直接切 Redis
```

---

## 3. ChromaDB "搜索素材自动入库" 代码流程

```python
# backend/app/knowledge/auto_index.py

from app.knowledge.vector_store import _get_collection
from app.knowledge.kb import get_event_by_keyword
import hashlib

async def index_search_results(query: str, results: list[dict]):
    """将搜索结果写入 ChromaDB，后续相似查询可以语义匹配。

    去重策略：URL 哈希作为 document ID，相同 URL 不重复写入。
    """
    col = _get_collection()
    if col is None:
        return  # ChromaDB 不可用，静默跳过

    ids, docs, metadatas = [], [], []
    for r in results:
        url = r.get("url", "")
        if not url:
            continue

        # 去重：URL SHA256 作为 ID
        doc_id = hashlib.sha256(url.encode()).hexdigest()[:32]

        # 检查是否已存在
        existing = col.get(ids=[doc_id])
        if existing and existing["ids"]:
            continue  # 已索引，跳过

        # 可搜索文本：标题 + snippet
        text = f"{r.get('title','')}。{r.get('snippet','')}"
        ids.append(doc_id)
        docs.append(text[:1000])
        metadatas.append({
            "title": r.get("title", ""),
            "url": url,
            "query": query,           # 记录搜索词，便于追溯
            "source": "tavily_search",
        })

    if ids:
        col.add(ids=ids, documents=docs, metadatas=metadatas)
        logger.info("ChromaDB 索引 %d 条新素材（%d 条去重跳过）",
                    len(ids), len(results) - len(ids))
```

**调用位置**：`orchestrator.py` 的 `_execute_tool("search")` 返回后：

```python
# orchestrator.py _execute_tool
elif tool_name == "search":
    result = await tool_search(...)
    ctx["material"].extend(result.get("results", []))

    # 搜索结果自动入库（异步，不阻塞主流程）
    import asyncio
    from app.knowledge.auto_index import index_search_results
    asyncio.create_task(index_search_results(
        params.get("query", ctx["user_input"]),
        result.get("results", []),
    ))

    return result
```

---

## 4. RateLimiter 接入 StateBackend

### 改动文件：`network/rate_limiter.py`

| 行号 | 当前代码 | 改为 |
|------|---------|------|
| 1 | 加 import | `from app.state import state` |
| 22-27 | `__init__` 里 `self._lock`, `self._successful_trials`, `self._daily_spent` | 保留 `self._lock`，删除内存 dict 初始化 |
| 53 | `return self._successful_trials.get(ip, 0)` | `return int(await state.get(f"rate:{ip}:{self._today}") or 0)` |
| 67-82 | `can_generate` 中 `self._daily_spent >= DAILY_BUDGET` | `float(await state.get("rate:daily_spent") or 0) >= DAILY_BUDGET` |
| 76-79 | `self._successful_trials.get(ip, 0) >= TRIALS_PER_IP` | `int(await state.get(f"rate:{ip}:{self._today}") or 0) >= TRIALS_PER_IP` |
| 86-92 | `record_success` 中 `self._successful_trials[ip] = ...` | `await state.incr(f"rate:{ip}:{self._today}")` + `await state.expire(f"rate:{ip}:{self._today}", 86400)` |
| 94-101 | `record_cost` 中 `self._daily_spent += amount` | `await state.incr("rate:daily_spent", amount)` + `await state.expire("rate:daily_spent", 86400)` |
| 31-43 | `_reset_if_new_day` | **整个方法删除**——StateBackend 的 TTL 自动过期替代日重置 |
| 22-23 | `self._today`, `self._total_generations` | 删除——不再需要 |

**迁移后 rate_limiter 变成无状态 + StateBackend 客户端。换 Redis 只需改 `STATE_BACKEND=redis` 一行配置。**

---

## 5. 1000 并发数据层改造路线

### Phase 1：100 并发（当前架构 + SQLite）

```
SQLite WAL 模式     ← 历史记录（读并发 100 OK）
Memory RateLimiter  ← 限流（单 worker OK）
ChromaDB 本地       ← 语义检索
```

### Phase 2：500 并发（加 Redis）

```
Redis              ← 限流 + 会话缓存
SQLite WAL         ← 历史记录（仍可用）
ChromaDB 本地      ← 语义检索
StateBackend       ← 全部走 state 抽象
```

### Phase 3：1000 并发（分布式）

```
Redis Cluster      ← 限流 + 分布式锁 + 消息队列
PostgreSQL         ← 历史记录（SQLite → PG 迁移）
ChromaDB Server    ← 独立向量检索服务
Caddy + 多 Worker  ← 水平扩展
```

### 关键监控指标

| 指标 | Phase 1 | Phase 2 | Phase 3 |
|------|---------|---------|---------|
| QPS | <10 | <50 | <200 |
| P99 延迟 | <60s | <45s | <30s |
| 数据存储 | 内存+文件 | +Redis | +PG |
| Worker 数 | 1 | 2-4 | 4-8 |
