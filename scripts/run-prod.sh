#!/bin/bash
# 生产模式（免 Node/nvm）：直接运行后端，托管已有的 frontend/dist
# 使用前请先在其他环境打包前端: cd frontend && npm install && npm run build
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DIST_DIR="$PROJECT_DIR/frontend/dist"

if [ ! -f "$DIST_DIR/index.html" ]; then
  echo "错误: 未找到 $DIST_DIR/index.html" >&2
  echo "请先在构建环境执行: cd frontend && npm install && npm run build" >&2
  echo "然后把 frontend/dist 复制到本机对应位置。" >&2
  exit 1
fi

cd "$PROJECT_DIR/backend"

# 监听地址：默认 0.0.0.0（局域网可访问，非本机来源需登录）；
# 只想本机访问就 DASH_HOST=127.0.0.1 ./scripts/run-prod.sh
DASH_HOST="${DASH_HOST:-0.0.0.0}"
PORT="${DASH_PORT:-8787}"
export DASH_HOST DASH_PORT="$PORT"

# 端口占用检测：bind 失败前给出明确提示，避免无提示继续
if command -v ss >/dev/null 2>&1; then
  if ss -tln 2>/dev/null | grep -q ":$PORT "; then
    echo "错误: 端口 $PORT 已被占用，请先停止已有服务后重试:" >&2
    ss -tlnp 2>/dev/null | grep ":$PORT " >&2
    exit 1
  fi
fi

echo "=== 启动后端 (FastAPI :$PORT，托管 frontend/dist) ==="
.venv/bin/uvicorn main:app --host "$DASH_HOST" --port "$PORT" &
BACKEND_PID=$!

# 可选：启动悬浮小屏（需图形会话 X11，默认关闭）
# 启用方式：DASH_PALETTE=1 ./scripts/run-prod.sh
if [ "${DASH_PALETTE:-0}" = "1" ]; then
  # 等待后端就绪（最多 30s），避免悬浮窗加载页面失败变成白板
  echo "=== 等待后端就绪 ==="
  ready=0
  for _ in $(seq 1 30); do
    if curl -s -o /dev/null --max-time 1 "http://127.0.0.1:$PORT/quickpalette" 2>/dev/null; then
      ready=1
      break
    fi
    sleep 1
  done
  if [ "$ready" = "1" ]; then
    echo "=== 启动悬浮小屏 (quickpalette) ==="
    DISPLAY="${DISPLAY:-:0}" DASH_URL="http://127.0.0.1:$PORT" \
      .venv/bin/python "$PROJECT_DIR/scripts/quickpalette.py" &
    PALETTE_PID=$!
  else
    echo "警告: 后端 30 秒内未就绪，跳过悬浮小屏启动" >&2
  fi
fi

LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

echo "监听: $DASH_HOST:$PORT"
echo "本机访问: http://localhost:$PORT"
[ -n "$LAN_IP" ] && [ "$DASH_HOST" = "0.0.0.0" ] && echo "局域网访问: http://$LAN_IP:$PORT"
if [ "$DASH_HOST" != "127.0.0.1" ] && [ -z "${DASH_AUTH_PASSWORD:-}" ] && [ -z "${DASH_AUTH_PASSWORD_HASH:-}" ]; then
  echo "" >&2
  echo "[警告] 未设置 DASH_AUTH_PASSWORD —— 非本机访问会被拒绝。" >&2
  echo "        开放远程登录: DASH_AUTH_PASSWORD='你的强密码' ./scripts/run-prod.sh" >&2
  echo "" >&2
fi
echo "按 Ctrl+C 停止"

cleanup() {
  echo "正在停止..."
  [ -n "${PALETTE_PID:-}" ] && kill "$PALETTE_PID" 2>/dev/null
  kill "$BACKEND_PID" 2>/dev/null
  wait
}
trap cleanup INT TERM
wait
