#!/usr/bin/env bash
# lumen-web — 一键启动 LobeChat 前端，接真实后端（默认 localhost:8001）
#
# 用法:
#   ./scripts/lumen-web.sh setup     # 首次：检查 Postgres + 建库 + 跑 migration
#   ./scripts/lumen-web.sh           # 启动 Vite(9876) + Next(3210)
#
# 环境变量可覆盖:
#   LOBE_CHAT_DIR    LobeChat 目录（默认 ~/Desktop/lobe-chat）
#   BACKEND_URL      后端地址（默认 http://localhost:8001）
#   PGPASSWORD       Postgres 密码（默认 postgres）
#
# 注意：LobeChat 本地裸 Postgres 需要去掉 pg_search/vector 扩展的 patch，
#       详见 docs/LOBE_CHAT_SETUP.md。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOBE_CHAT_DIR="${LOBE_CHAT_DIR:-$HOME/Desktop/lobe-chat}"
BACKEND_URL="${BACKEND_URL:-http://localhost:8001}"
PGPASSWORD="${PGPASSWORD:-postgres}"
SECRET_FILE="$ROOT/backend/.lumen-secret"
DB_NAME="lobechat"

# Postgres bin（winget 版默认路径；系统 PATH 有 psql 则优先）
if command -v psql >/dev/null 2>&1; then
  PG_BIN="$(dirname "$(command -v psql)")"
else
  PG_BIN="/c/Program Files/PostgreSQL/16/bin"
fi

echo "🔌 LobeChat: $LOBE_CHAT_DIR"
echo "🎯 后端:    $BACKEND_URL"

# ── KEY_VAULTS_SECRET（LobeChat DB 加密密钥；无则生成）──
[ -f "$SECRET_FILE" ] || { openssl rand -base64 32 > "$SECRET_FILE"; echo "🔑 已生成密钥 → $SECRET_FILE"; }
SECRET="$(cat "$SECRET_FILE")"

# ── setup: 数据库准备（首次/迁移后）──
if [ "${1:-}" = "setup" ]; then
  echo "📦 准备数据库 $DB_NAME ..."
  "$PG_BIN/psql" -U postgres -h localhost -lqt | cut -d \| -f 1 | grep -qw "$DB_NAME" || {
    "$PG_BIN/psql" -U postgres -h localhost -c "CREATE DATABASE $DB_NAME;"
    echo "  ✅ 已建库"
  }
  echo "  ✅ 库就绪，跑 migration（若报 pg_search/vector 错误，说明缺 patch，见 docs/LOBE_CHAT_SETUP.md）..."
  (cd "$LOBE_CHAT_DIR" && KEY_VAULTS_SECRET="$SECRET" \
    DATABASE_DRIVER=node \
    DATABASE_URL="postgresql://postgres:$PGPASSWORD@localhost:5432/$DB_NAME" \
    MIGRATION_DB=1 pnpm run db:migrate)
  echo "✅ migration 完成"
  exit 0
fi

# ── 启动 ──
cd "$LOBE_CHAT_DIR"
[ -d node_modules ] || { echo "📦 首次运行，安装依赖（可能很久）..."; pnpm install; }

# Vite（auth SPA，LobeChat 认证页由它提供）
SPA_PORT=9876 pnpm exec vite &
VITE_PID=$!
trap 'kill "$VITE_PID" 2>/dev/null || true' EXIT

# Next.js 主 Web 端：DeepSeek/OpenAI proxy 都指向真实后端网关
KEY_VAULTS_SECRET="$SECRET" \
DATABASE_DRIVER=node \
DATABASE_URL="postgresql://postgres:$PGPASSWORD@localhost:5432/$DB_NAME" \
S3_ACCESS_KEY_ID=test S3_SECRET_ACCESS_KEY=test \
S3_ENDPOINT="http://localhost:9000" S3_BUCKET="$DB_NAME" S3_ENABLE_PATH_STYLE=1 \
DEEPSEEK_API_KEY=sk-lumen DEEPSEEK_PROXY_URL="$BACKEND_URL/v1" \
OPENAI_API_KEY=sk-lumen OPENAI_PROXY_URL="$BACKEND_URL/v1" \
pnpm exec next dev -p 3210
