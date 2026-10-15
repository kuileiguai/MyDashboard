#!/bin/bash
# 开发模式：同时启动后端 (8787) 和前端 Vite dev server (5173)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load nvm for Node 20
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
nvm use 20 > /dev/null 2>&1

# 开发模式下远程请求经由 Vite 代理转发，来源 IP 只能从 X-Forwarded-For 还原，
# 故后端开启 TRUST_PROXY；后端本身仍只监听 127.0.0.1，避免被绕过代理直连。
export DASH_TRUST_PROXY=1
DASH_HOST="${DASH_HOST:-0.0.0.0}"

echo "=== 启动后端 (FastAPI :8787，仅本机监听) ==="
cd "$PROJECT_DIR/backend"
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8787 --reload &
BACKEND_PID=$!

echo "=== 启动前端 (Vite :5173) ==="
cd "$PROJECT_DIR/frontend"
npx vite --host "$DASH_HOST" &
FRONTEND_PID=$!

# 可选：启动悬浮小屏（需图形会话 X11，默认关闭）
# 启用方式：DASH_PALETTE=1 ./scripts/dev.sh
if [ "${DASH_PALETTE:-0}" = "1" ]; then
  sleep 2
  echo "=== 启动悬浮小屏 (quickpalette) ==="
  DISPLAY="${DISPLAY:-:0}" DASH_URL="http://127.0.0.1:5173" \
    "$PROJECT_DIR/backend/.venv/bin/python" "$PROJECT_DIR/scripts/quickpalette.py" &
  PALETTE_PID=$!
fi

LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

echo ""
echo "前端: http://localhost:5173"
[ -n "$LAN_IP" ] && [ "$DASH_HOST" = "0.0.0.0" ] && echo "局域网: http://$LAN_IP:5173"
echo "后端: http://localhost:8787（仅本机，远程请走 Vite 端口）"
echo "API文档: http://localhost:8787/docs"
if [ -z "${DASH_AUTH_PASSWORD:-}" ] && [ -z "${DASH_AUTH_PASSWORD_HASH:-}" ]; then
  echo "[警告] 未设置 DASH_AUTH_PASSWORD —— 非本机访问会被拒绝。" >&2
fi
[ -n "${PALETTE_PID:-}" ] && echo "悬浮小屏: 已启动（快捷键 Ctrl+Shift+Space）"
echo ""
echo "按 Ctrl+C 停止所有服务"

cleanup() {
  echo "正在停止..."
  kill $BACKEND_PID 2>/dev/null
  kill $FRONTEND_PID 2>/dev/null
  [ -n "${PALETTE_PID:-}" ] && kill $PALETTE_PID 2>/dev/null
  wait
}
trap cleanup INT TERM
wait
