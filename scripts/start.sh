#!/bin/bash
# 生产模式：构建前端并仅运行后端（托管 dist）
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load nvm for Node 20
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
nvm use 20 > /dev/null 2>&1

echo "=== 构建前端 ==="
cd "$PROJECT_DIR/frontend"
npx vite build

echo "=== 启动后端 (FastAPI :8787，托管前端) ==="
cd "$PROJECT_DIR/backend"

# 端口占用检测：bind 失败前给出明确提示，避免无提示继续
if command -v ss >/dev/null 2>&1; then
  if ss -tln 2>/dev/null | grep -q ":8787 "; then
    echo "错误: 端口 8787 已被占用，请先停止已有服务后重试:" >&2
    ss -tlnp 2>/dev/null | grep ":8787 " >&2
    exit 1
  fi
fi

.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8787 &
BACKEND_PID=$!

# 可选：启动悬浮小屏（需图形会话 X11，默认关闭）
# 启用方式：DASH_PALETTE=1 ./scripts/start.sh
if [ "${DASH_PALETTE:-0}" = "1" ]; then
  sleep 2
  echo "=== 启动悬浮小屏 (quickpalette) ==="
  DISPLAY="${DISPLAY:-:0}" DASH_URL="http://127.0.0.1:8787" \
    .venv/bin/python "$PROJECT_DIR/scripts/quickpalette.py" &
  PALETTE_PID=$!
fi

cleanup() {
  echo "正在停止..."
  [ -n "${PALETTE_PID:-}" ] && kill "$PALETTE_PID" 2>/dev/null
  kill "$BACKEND_PID" 2>/dev/null
  wait
}
trap cleanup INT TERM
wait
