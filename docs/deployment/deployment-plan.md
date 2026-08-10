# 生产级部署方案

> 2026-08-08  
> 目标平台：单台 VPS（2C4G，¥50-100/月）  
> 技术栈：Caddy + Docker Compose + GitHub Actions

---

## 一、架构图

```
Internet
    │
    ▼
Caddy (:80/:443)
    │ 自动 HTTPS（Let's Encrypt）
    │ Gzip 压缩
    │ WebSocket 升级
    │
    ├── /api/*   → backend:8000  (FastAPI)
    ├── /ws/*    → backend:8000  (WebSocket)
    ├── /metrics → backend:8000  (仅内网)
    └── /*       → 前端静态文件
```

---

## 二、Caddyfile（已创建）

`Caddyfile` 包含：
- 自动 HTTPS（Let's Encrypt 零配置）
- WebSocket 代理（Upgrade + Connection 头透传）
- Gzip + Zstd 压缩
- 安全头（X-Content-Type-Options、X-Frame-Options、Referrer-Policy）
- `/metrics` 端点 IP 白名单
- JSON 格式访问日志

### 首次部署

```bash
# 1. 修改 Caddyfile 中的域名
sed -i 's/time-pixel.example.com/你的真实域名/g' Caddyfile

# 2. 取消注释 tls 行（让 Caddy 自动获取证书）
# 编辑 Caddyfile，取消注释：tls your-email@example.com

# 3. 启动
docker-compose up -d
```

---

## 三、Docker Compose（已更新）

`docker-compose.yml` 包含：
- **Caddy**：反代 + HTTPS，挂载 Caddyfile + 前端构建产物
- **Backend**：FastAPI，挂载 logs + demos + data 目录
- **Redis**：注释状态，Phase 2 取消注释即可启用
- **Healthcheck**：`/api/health` 每 30 秒检查一次

---

## 四、Health 端点

| 端点 | 用途 | 返回 |
|------|------|------|
| `GET /api/health` | 综合状态 | `{"status":"healthy"\|"degraded", "checks":{...}}` |
| `GET /api/health/live` | K8s Liveness 探针 | `{"status":"alive"}` |
| `GET /api/health/ready` | K8s Readiness 探针 | `{"status":"ready"\|"not_ready", "checks":{...}}` |

**区别**：
- **Liveness**：进程是否存活 → 挂了就重启容器。这是最轻量的检查，不查任何依赖。
- **Readiness**：依赖是否就绪（API Key 配置了没、Playwright 浏览器装了没）→ 没就绪就不路由流量。这是启动时的检查。

**为什么 Liveness 不检查依赖？** 如果 API Key 配置错误，Readiness 失败 → 停止路由流量（正确行为）。但如果 Liveness 也查 API Key，容器会因为配置错误被反复重启（错误行为）——配置错误不是重启能解决的。

---

## 五、蓝绿部署方案

### 原理

```
蓝环境（当前生产）    绿环境（新版本）
  backend:8000         backend:8001
       ↑                    ↑
       └──── Caddy ─────────┘
              │
        路由到蓝 OR 绿
```

### 实现

```bash
# 1. 构建新镜像（不中断蓝环境）
docker build -t time-pixel:green ./backend

# 2. 启动绿环境（不同端口）
docker run -d --name backend-green \
  -p 8001:8000 \
  --env-file backend/.env \
  time-pixel:green

# 3. 健康检查绿环境
curl http://localhost:8001/api/health/ready
# → {"status": "ready"} ✅

# 4. 切换流量：修改 Caddyfile 端口 8000→8001
# Caddy 自动热重载配置

# 5. 观察 5 分钟——无异常

# 6. 停掉蓝环境
docker stop backend-blue && docker rm backend-blue

# 7. 绿变蓝（重命名）
docker rename backend-green backend-blue
```

### docker-compose 简化版

```yaml
# 临时添加绿环境到 docker-compose.yml
services:
  backend-green:
    build: ./backend
    restart: unless-stopped
    expose:
      - "8001"
    environment:
      - PORT=8001
    env_file:
      - ./backend/.env
    # ... 同 backend 配置
```

---

## 六、CI/CD Deploy Job

在 `.github/workflows/ci.yml` 末尾追加：

```yaml
  deploy:
    name: Deploy to Production
    needs: [test, docker]
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    environment: production  # GitHub 环境保护——需要审批

    steps:
      - uses: actions/checkout@v4

      # 1. 登录 Docker Registry
      - name: Login to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      # 2. 构建并推送镜像
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: ./backend
          push: true
          tags: |
            ghcr.io/${{ github.repository }}/backend:${{ github.sha }}
            ghcr.io/${{ github.repository }}/backend:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max

      # 3. SSH 到服务器 → 拉取新镜像 → 滚动更新
      - name: Deploy to server
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.DEPLOY_HOST }}
          username: ${{ secrets.DEPLOY_USER }}
          key: ${{ secrets.DEPLOY_SSH_KEY }}
          script: |
            cd /opt/time-pixel

            # 拉取最新镜像
            docker pull ghcr.io/${{ github.repository }}/backend:${{ github.sha }}

            # 启动绿环境（新版本）
            docker run -d --name backend-${{ github.sha }} \
              --network time-pixel_default \
              --env-file backend/.env \
              -v /opt/time-pixel/backend/logs:/app/logs \
              -v /opt/time-pixel/backend/demos:/app/demos \
              ghcr.io/${{ github.repository }}/backend:${{ github.sha }}

            # 等新容器健康检查通过
            for i in $(seq 1 30); do
              if curl -sf http://backend-${{ github.sha }}:8000/api/health/live; then
                break
              fi
              sleep 2
            done

            # 停掉旧容器
            docker stop backend 2>/dev/null || true
            docker rm backend 2>/dev/null || true

            # 新容器改名为 backend（无缝切换）
            docker rename backend-${{ github.sha }} backend
```

### 需要的 GitHub Secrets

| Secret | 值 | 说明 |
|--------|-----|------|
| `DEPLOY_HOST` | `123.45.67.89` | 服务器 IP |
| `DEPLOY_USER` | `root` | SSH 用户名 |
| `DEPLOY_SSH_KEY` | `-----BEGIN OPENSSH...` | SSH 私钥（推荐 Ed25519） |
| `GITHUB_TOKEN` | 自动提供 | GitHub Actions 内置 |

---

## 七、零停机更新检查清单

- [ ] 新版本镜像构建成功
- [ ] 新容器健康检查通过（`/api/health/live` + `/api/health/ready`）
- [ ] 蓝绿切换后观察 5 分钟（错误率、延迟、WebSocket 连接）
- [ ] 回滚方案就绪：`docker start backend`（旧容器还在）
- [ ] WebSocket 连接在切换期间的体验：Caddy 会断开旧连接（客户端有重连逻辑，3 次指数退避）

---

## 八、关键环境变量

| 变量 | 生产建议 | 说明 |
|------|---------|------|
| `DEEPSEEK_API_KEY` | 生产 Key，与开发不同 | 隔离计费 |
| `TAVILY_API_KEY` | 生产 Key | 搜索 API |
| `DAILY_BUDGET` | `5.0` | 上线初期保守设置 |
| `TRIALS_PER_IP` | `1` | 降低滥用风险 |
| `LOG_PROMPTS` | `0` | 生产绝不记录完整 prompt |
| `STATE_BACKEND` | `memory` | Phase 2 改为 `redis` |
| `MAX_CONNECTIONS` | `20` | 2C4G 服务器建议值 |
