#!/bin/bash
# start-palette.sh — 等后端就绪后启动悬浮小屏
#
# 用法：
#   ./scripts/start-palette.sh
#   DASH_URL=http://127.0.0.1:8787 ./scripts/start-palette.sh
#
# 说明：
#   · 需要 X11 图形会话（DISPLAY）；Wayland 下吸附/窗口控制不可用
#   · 已在运行则不重复启动
#   · 日志写到 data/logs/palette.log
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PY="$PROJECT_DIR/backend/.venv/bin/python"
TARGET="$PROJECT_DIR/scripts/quickpalette.py"
LOG_DIR="$PROJECT_DIR/data/logs"
LOG="$LOG_DIR/palette.log"
PID_FILE="$PROJECT_DIR/data/palette.pid"

if [ ! -x "$PY" ]; then
  echo "错误: 缺少 $PY，请先完成 backend/.venv 安装。" >&2
  exit 1
fi
if [ ! -f "$TARGET" ]; then
  echo "错误: 缺少 $TARGET" >&2
  exit 1
fi

if [ -z "${DISPLAY:-}" ]; then
  echo "错误: 没有 DISPLAY，悬浮小屏需要 X11 图形会话。" >&2
  echo "可在服务器桌面终端运行，或显式指定 DISPLAY=:0。" >&2
  exit 1
fi

if command -v pgrep >/dev/null 2>&1 && pgrep -f "$TARGET" >/dev/null 2>&1; then
  echo "悬浮小屏已在运行。"
  exit 0
fi

# 读端口
ENV_FILE="${DASH_ENV_FILE:-$PROJECT_DIR/backend/.env}"
ENV_PORT="$(grep -E '^[[:space:]]*(export[[:space:]]+)?DASH_PORT=' "$ENV_FILE" 2>/dev/null | tail -1 | sed -E 's/^[^=]*=//' || true)"
PORT="${DASH_PORT:-${ENV_PORT:-8787}}"
DASH_URL="${DASH_URL:-http://127.0.0.1:$PORT}"

mkdir -p "$LOG_DIR"
chmod 700 "$LOG_DIR"

echo "等待后端就绪: $DASH_URL/api/health"
READY=0
for _ in $(seq 1 30); do
  BODY="$(curl -fsS --max-time 2 "$DASH_URL/api/health" 2>/dev/null || true)"
  case "$BODY" in
    *'"ok":true'*) READY=1; break ;;
  esac
  sleep 1
done
if [ "$READY" -ne 1 ]; then
  echo "错误: 后端 30 秒内未就绪，未启动悬浮小屏。" >&2
  exit 1
fi

echo "启动悬浮小屏（日志: $LOG）"
if [ -n "${XAUTHORITY:-}" ]; then
  nohup env DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" DASH_URL="$DASH_URL" \
    "$PY" "$TARGET" >>"$LOG" 2>&1 &
else
  nohup env DISPLAY="$DISPLAY" DASH_URL="$DASH_URL" \
    "$PY" "$TARGET" >>"$LOG" 2>&1 &
fi
echo $! > "$PID_FILE"

sleep 1
if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "已启动，PID $(cat "$PID_FILE")"
else
  echo "启动失败，查看日志: $LOG" >&2
  tail -30 "$LOG" 2>/dev/null || true
  rm -f "$PID_FILE"
  exit 1
fi
