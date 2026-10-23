#!/bin/bash
# deckpit.sh — Deckpit 生命周期管理
#
# 用法：
#   ./scripts/deckpit.sh start [--palette|--no-palette]
#   ./scripts/deckpit.sh stop
#   ./scripts/deckpit.sh restart [--palette|--no-palette]
#   ./scripts/deckpit.sh status
#   ./scripts/deckpit.sh logs [-f]
#   ./scripts/deckpit.sh doctor
#   ./scripts/deckpit.sh palette start|stop|status
#   ./scripts/deckpit.sh open
#
# 说明：
#   · 已安装 systemd user unit（deckpit.service）时优先走 systemctl --user；
#     否则回退到 PID/端口方式，兼容 P0 的 nohup 启动。
#   · 自动检测 DISPLAY：有图形会话时 start 会顺带启动悬浮小屏。
#   · status 退出码：0 运行 / 3 停止 / 4 异常。
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${DASH_ENV_FILE:-$PROJECT_DIR/backend/.env}"
case "$ENV_FILE" in
  "~/"*) ENV_FILE="$HOME/${ENV_FILE#~/}" ;;
  /*) ;;
  *) ENV_FILE="$PROJECT_DIR/$ENV_FILE" ;;
esac

ENV_PORT="$(grep -E '^[[:space:]]*(export[[:space:]]+)?DASH_PORT=' "$ENV_FILE" 2>/dev/null | tail -1 | sed -E 's/^[^=]*=//' || true)"
ENV_HOST="$(grep -E '^[[:space:]]*(export[[:space:]]+)?DASH_HOST=' "$ENV_FILE" 2>/dev/null | tail -1 | sed -E 's/^[^=]*=//' || true)"
PORT="${DASH_PORT:-${ENV_PORT:-8787}}"
HOST="${DASH_HOST:-${ENV_HOST:-0.0.0.0}}"
LOG_DIR="$PROJECT_DIR/data/logs"
LOG_FILE="$LOG_DIR/deckpit.log"
PID_FILE="$PROJECT_DIR/data/deckpit.pid"
PALETTE_PID="$PROJECT_DIR/data/palette.pid"
UNIT="deckpit.service"
BASE_URL="http://127.0.0.1:$PORT"

die()  { printf '\n[错误] %s\n' "$*" >&2; exit 1; }
ok()   { printf '  [OK] %s\n' "$*"; }
warn() { printf '  [注意] %s\n' "$*"; }
step() { printf '\n== %s ==\n' "$*"; }

has_unit() {
  systemctl --user cat deckpit >/dev/null 2>&1
}

port_state() {
  ss -tln "sport = :$PORT" 2>/dev/null || true
}

listening() {
  case "$(port_state)" in
    *LISTEN*) return 0 ;;
    *) return 1 ;;
  esac
}

port_pid() {
  local pid=""
  pid="$(ss -tlnp "sport = :$PORT" 2>/dev/null | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | head -1 || true)"
  if [ -z "$pid" ] && command -v lsof >/dev/null 2>&1; then
    pid="$(lsof -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1 || true)"
  fi
  printf '%s' "$pid"
}

health() {
  local body
  body="$(curl -fsS --max-time 2 "$BASE_URL/api/health" 2>/dev/null || true)"
  case "$body" in
    *'"ok":true'*) printf '%s' "$body" ;;
    *) printf '' ;;
  esac
}

wait_health() {
  local _
  for _ in $(seq 1 30); do
    if [ -n "$(health)" ]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

rotate_log() {
  mkdir -p "$LOG_DIR"
  chmod 700 "$LOG_DIR" 2>/dev/null || true
  if [ -f "$LOG_FILE" ]; then
    local size
    size="$(stat -c '%s' "$LOG_FILE" 2>/dev/null || echo 0)"
    if [ "${size:-0}" -gt 20971520 ]; then
      mv "$LOG_FILE" "$LOG_FILE.$(date +%Y%m%d-%H%M%S)"
    fi
  fi
}

stop_palette() {
  local pid=""
  if [ -f "$PALETTE_PID" ]; then
    pid="$(cat "$PALETTE_PID" 2>/dev/null || true)"
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
    rm -f "$PALETTE_PID"
  fi
  if command -v pgrep >/dev/null 2>&1; then
    for pid in $(pgrep -f "$PROJECT_DIR/scripts/quickpalette.py" 2>/dev/null || true); do
      kill "$pid" 2>/dev/null || true
    done
  fi
}

start_palette() {
  local mode="${1:-auto}"
  [ "$mode" = "no" ] && return 0
  if [ "$mode" = "auto" ] && [ -z "${DISPLAY:-}" ]; then
    return 0
  fi
  if [ -z "${DISPLAY:-}" ]; then
    warn "没有 DISPLAY，跳过悬浮小屏"
    return 0
  fi
  "$PROJECT_DIR/scripts/start-palette.sh"
}

cmd_start() {
  local palette_mode="auto"
  while [ $# -gt 0 ]; do
    case "$1" in
      --palette) palette_mode="yes"; shift ;;
      --no-palette) palette_mode="no"; shift ;;
      *) die "start 未知参数: $1" ;;
    esac
  done

  if listening; then
    if [ -z "$(health)" ]; then
      die "端口 $PORT 在监听，但 /api/health 不可用；可能是旧实例或另一个进程，先运行 ./scripts/deckpit.sh stop"
    fi
    ok "已在运行: $BASE_URL"
    start_palette "$palette_mode" || warn "悬浮小屏启动失败"
    return 0
  fi

  rotate_log
  if has_unit; then
    systemctl --user start "$UNIT"
    ok "已通过 systemd 启动 $UNIT"
  else
    echo "启动后端（日志: $LOG_FILE）"
    (
      cd "$PROJECT_DIR"
      nohup env DASH_ENV_FILE="$ENV_FILE" DASH_HOST="$HOST" DASH_PORT="$PORT" DASH_PALETTE=0 \
        bash ./scripts/run-prod.sh >>"$LOG_FILE" 2>&1 &
      echo $! > "$PID_FILE"
    )
    ok "已启动，PID 文件: data/deckpit.pid"
  fi

  if ! wait_health; then
    command -v systemctl >/dev/null 2>&1 && has_unit && journalctl --user -u "$UNIT" -n 50 --no-pager 2>/dev/null || true
    tail -50 "$LOG_FILE" 2>/dev/null || true
    die "后端 30 秒内未就绪"
  fi
  ok "后端已就绪: $BASE_URL"
  start_palette "$palette_mode" || warn "悬浮小屏启动失败，查看 data/logs/palette.log"
}

cmd_stop() {
  if has_unit; then
    systemctl --user stop "$UNIT" || true
    ok "已停止 systemd 服务 $UNIT"
  else
    local pid=""
    pid="$(port_pid)"
    if [ -z "$pid" ] && [ -f "$PID_FILE" ]; then
      pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    fi
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo "停止 PID $pid"
      kill "$pid" 2>/dev/null || true
      for _ in $(seq 1 10); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
      done
      if kill -0 "$pid" 2>/dev/null; then
        echo "未退出，SIGKILL"
        kill -9 "$pid" 2>/dev/null || true
      fi
    fi
    rm -f "$PID_FILE"
  fi

  stop_palette
  if listening; then
    die "端口 $PORT 仍被占用，请手动检查: ss -tlnp 'sport = :$PORT'"
  fi
  ok "已停止，端口 $PORT 已释放"
}

cmd_restart() {
  cmd_stop
  sleep 1
  cmd_start "$@"
}

cmd_status() {
  local running=0
  if listening; then
    running=1
  fi
  if has_unit; then
    echo "systemd: $(systemctl --user is-active "$UNIT" 2>/dev/null || true)"
  else
    echo "systemd: 未安装（PID/端口模式）"
  fi
  echo "监听:    $HOST:$PORT"
  echo "配置:    $ENV_FILE"
  if [ "$running" -eq 1 ]; then
    echo "端口:    LISTEN"
    local pid h
    pid="$(port_pid)"
    if [ -z "$pid" ] && [ -f "$PID_FILE" ]; then
      pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    fi
    echo "PID:     ${pid:-未知}"
    h="$(health)"
    if [ -n "$h" ]; then
      echo "健康:    $h"
    else
      echo "健康:    端口在监听，但 /api/health 不可用"
    fi
  else
    echo "端口:    未监听"
  fi
  if command -v pgrep >/dev/null 2>&1 && pgrep -f "$PROJECT_DIR/scripts/quickpalette.py" >/dev/null 2>&1; then
    echo "小屏:    运行中"
  else
    echo "小屏:    未运行"
  fi

  if [ "$running" -eq 1 ] && [ -n "$(health)" ]; then
    return 0
  elif [ "$running" -eq 1 ]; then
    return 4
  else
    return 3
  fi
}

cmd_logs() {
  local follow=0
  [ "${1:-}" = "-f" ] || [ "${1:-}" = "--follow" ] && follow=1
  if has_unit; then
    if [ "$follow" -eq 1 ]; then
      journalctl --user -u "$UNIT" -f
    else
      journalctl --user -u "$UNIT" -n 200 --no-pager
    fi
  else
    if [ "$follow" -eq 1 ]; then
      tail -n 200 -f "$LOG_FILE"
    else
      tail -n 200 "$LOG_FILE"
    fi
  fi
}

cmd_doctor() {
  step "配置"
  if [ -f "$ENV_FILE" ]; then
    stat -c '  %a %U:%G %n' "$ENV_FILE"
    grep -E '^[[:space:]]*(export[[:space:]]+)?DASH_(HOST|PORT|AUTH_USER)=' "$ENV_FILE" | sed -E 's/=.*/=<set>/' || true
  else
    warn "配置文件不存在: $ENV_FILE"
  fi

  step "端口"
  ss -tlnp "sport = :$PORT" 2>/dev/null || true

  step "健康"
  local h
  h="$(health)"
  if [ -n "$h" ]; then ok "$h"; else warn "无响应"; fi

  step "systemd"
  if has_unit; then
    systemctl --user status "$UNIT" --no-pager 2>/dev/null | head -12 || true
  else
    warn "未安装 $UNIT（可用 ./scripts/p1-setup.sh 安装）"
  fi

  step "悬浮小屏"
  if command -v pgrep >/dev/null 2>&1 && pgrep -af "$PROJECT_DIR/scripts/quickpalette.py" 2>/dev/null; then
    ok "进程存在"
  else
    warn "未运行"
  fi

  step "Docker"
  if docker ps >/dev/null 2>&1; then ok "docker ps 正常"; else warn "docker ps 失败（需要重登/ newgrp docker）"; fi
}

cmd_palette() {
  local action="${1:-status}"
  case "$action" in
    start) "$PROJECT_DIR/scripts/start-palette.sh" ;;
    stop) stop_palette; ok "悬浮小屏已停止" ;;
    status)
      if command -v pgrep >/dev/null 2>&1 && pgrep -af "$PROJECT_DIR/scripts/quickpalette.py" 2>/dev/null; then
        return 0
      else
        echo "悬浮小屏未运行"
        return 1
      fi
      ;;
    *) die "palette 只支持 start|stop|status" ;;
  esac
}

case "${1:-}" in
  start) shift; cmd_start "$@" ;;
  stop) cmd_stop ;;
  restart) shift; cmd_restart "$@" ;;
  status) cmd_status ;;
  logs) shift; cmd_logs "$@" ;;
  doctor) cmd_doctor ;;
  palette) shift; cmd_palette "$@" ;;
  open) xdg-open "$BASE_URL" >/dev/null 2>&1 || true ;;
  ""|-h|--help)
    awk 'NR==1{next} /^set -Eeuo/{exit} /^#/{sub(/^# ?/,""); print} /^$/{print}' "$0"
    ;;
  *) die "未知命令: $1（用 --help 查看用法）" ;;
esac
