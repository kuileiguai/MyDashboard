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
  # 等待后端就绪（最多 30s），避免悬浮窗加载页面失败变成白板
  echo "=== 等待后端就绪 ==="
  ready=0
  for _ in $(seq 1 30); do
    if curl -s -o /dev/null --max-time 1 "http://127.0.0.1:8787/quickpalette" 2>/dev/null; then
      ready=1
      break
    fi
    sleep 1
  done
  if [ "$ready" = "1" ]; then
    echo "=== 启动悬浮小屏 (quickpalette) ==="
    DISPLAY="${DISPLAY:-:0}" DASH_URL="http://127.0.0.1:8787" \
      .venv/bin/python "$PROJECT_DIR/scripts/quickpalette.py" &
    PALETTE_PID=$!
  else
    echo "警告: 后端 30 秒内未就绪，跳过悬浮小屏启动" >&2
  fi
fi

cleanup() {
  echo "正在停止..."
  [ -n "${PALETTE_PID:-}" ] && kill "$PALETTE_PID" 2>/dev/null
  kill "$BACKEND_PID" 2>/dev/null
  wait
}
trap cleanup INT TERM
wait
