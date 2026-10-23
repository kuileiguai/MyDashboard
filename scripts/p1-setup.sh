#!/bin/bash
# p1-setup.sh — Deckpit P1：systemd + 开机自启 + 历史 1s + 小屏自启 + 日志轮转
#
# 用法：
#   ./scripts/p1-setup.sh
#   ./scripts/p1-setup.sh --no-palette
#   ./scripts/p1-setup.sh --no-linger --no-logrotate
#
# 说明：
#   · 用普通用户运行；安装的是 systemd --user 服务，不是系统级服务。
#   · 会先停掉 P0 的 nohup 实例，再启用 deckpit.service。
#   · 需要 systemd --user 可用；SSH 无 user bus 时请到桌面终端运行。
#   · 悬浮小屏通过 XDG autostart 启动，不塞进 systemd。
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${DASH_ENV_FILE:-$PROJECT_DIR/backend/.env}"
USER_NAME="$(id -un)"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/deckpit.service"
AUTOSTART_DIR="$HOME/.config/autostart"
AUTOSTART="$AUTOSTART_DIR/deckpit-palette.desktop"
LOG_DIR="$PROJECT_DIR/data/logs"
LOG_FILE="$LOG_DIR/deckpit.log"

YES=0
NO_PALETTE=0
NO_LINGER=0
NO_LOGROTATE=0
HOST=""
PORT=""

usage() {
  awk 'NR==1{next} /^set -Eeuo/{exit} /^#/{sub(/^# ?/,""); print} /^$/{print}' "$0"
  exit 0
}

die()  { printf '\n[错误] %s\n' "$*" >&2; exit 1; }
ok()   { printf '  [OK] %s\n' "$*"; }
warn() { printf '  [注意] %s\n' "$*"; }
step() { printf '\n== %s ==\n' "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="${2:-}"; shift 2 ;;
    --port) PORT="${2:-}"; shift 2 ;;
    --no-palette) NO_PALETTE=1; shift ;;
    --no-linger) NO_LINGER=1; shift ;;
    --no-logrotate) NO_LOGROTATE=1; shift ;;
    --yes|-y) YES=1; shift ;;
    -h|--help) usage ;;
    *) die "未知参数: $1（用 --help 查看用法）" ;;
  esac
done

[ "$(id -u)" -ne 0 ] || die "请不要用 root 运行；用部署用户运行。"
[ -f "$ENV_FILE" ] || die "配置文件不存在: $ENV_FILE"
[ -x "$PROJECT_DIR/backend/.venv/bin/uvicorn" ] || die "缺少 backend/.venv，请先完成依赖安装。"
[ -f "$PROJECT_DIR/frontend/dist/index.html" ] || die "缺少 frontend/dist，请先构建前端。"
[ -x "$PROJECT_DIR/scripts/deckpit.sh" ] || die "缺少 scripts/deckpit.sh"

if ! systemctl --user show-environment >/dev/null 2>&1; then
  die "systemd --user 不可用；请在服务器桌面登录终端运行，或先确认 XDG_RUNTIME_DIR/DBUS_SESSION_BUS_ADDRESS。"
fi

ENV_PORT="$(grep -E '^[[:space:]]*(export[[:space:]]+)?DASH_PORT=' "$ENV_FILE" 2>/dev/null | tail -1 | sed -E 's/^[^=]*=//' || true)"
ENV_HOST="$(grep -E '^[[:space:]]*(export[[:space:]]+)?DASH_HOST=' "$ENV_FILE" 2>/dev/null | tail -1 | sed -E 's/^[^=]*=//' || true)"
HOST="${HOST:-${ENV_HOST:-0.0.0.0}}"
PORT="${PORT:-${ENV_PORT:-8787}}"
case "$PORT" in ''|*[!0-9]*) die "端口不合法: $PORT" ;; esac

sd_escape() { printf '%s' "$1" | sed 's/ /\\x20/g'; }

step "将要执行"
cat <<EOF
  项目:       $PROJECT_DIR
  配置:       $ENV_FILE
  监听:       $HOST:$PORT
  systemd:    ~/.config/systemd/user/deckpit.service
  开机自启:   $([ "$NO_LINGER" -eq 1 ] && echo 跳过 || echo enable-linger)
  悬浮小屏:   $([ "$NO_PALETTE" -eq 1 ] && echo 跳过 || echo XDG autostart)
  日志轮转:   $([ "$NO_LOGROTATE" -eq 1 ] && echo 跳过 || echo /etc/logrotate.d/deckpit)
EOF
if [ "$YES" -ne 1 ]; then
  read -rp "继续? [y/N]: " ans
  case "$ans" in [Yy]*) ;; *) die "已取消。" ;; esac
fi

step "停止当前实例"
"$PROJECT_DIR/scripts/deckpit.sh" stop || true
mkdir -p "$LOG_DIR"
chmod 700 "$LOG_DIR"

step "安装 systemd user unit"
mkdir -p "$UNIT_DIR"
if [ -f "$UNIT" ]; then
  BACKUP="$UNIT.bak.$(date +%Y%m%d-%H%M%S)"
  cp -p "$UNIT" "$BACKUP"
  ok "已备份旧 unit: $BACKUP"
fi

cat > "$UNIT" <<EOF
[Unit]
Description=Deckpit
After=network-online.target
Wants=network-online.target
StartLimitBurst=5
StartLimitIntervalSec=60

[Service]
Type=simple
WorkingDirectory=$(sd_escape "$PROJECT_DIR/backend")
Environment=DASH_ENV_FILE=$(sd_escape "$ENV_FILE")
Environment=PYTHONUNBUFFERED=1
ExecStart=$(sd_escape "$PROJECT_DIR/backend/.venv/bin/uvicorn") main:app --host $HOST --port $PORT
Restart=on-failure
RestartSec=3
TimeoutStopSec=15
KillMode=control-group

[Install]
WantedBy=default.target
EOF
chmod 644 "$UNIT"
systemctl --user daemon-reload
systemctl --user enable --now deckpit.service
ok "已启用 deckpit.service"

step "等待后端就绪"
READY=0
for _ in $(seq 1 30); do
  BODY="$(curl -fsS --max-time 2 "http://127.0.0.1:$PORT/api/health" 2>/dev/null || true)"
  case "$BODY" in
    *'"ok":true'*) READY=1; break ;;
  esac
  sleep 1
done
if [ "$READY" -ne 1 ]; then
  journalctl --user -u deckpit -n 80 --no-pager 2>/dev/null || true
  die "deckpit.service 30 秒内未就绪"
fi
ok "后端已就绪: http://127.0.0.1:$PORT"

step "历史同步间隔 = 1s"
curl -s -X POST "http://127.0.0.1:$PORT/api/commands/history/config" \
  -H 'Content-Type: application/json' \
  -d '{"interval":1}' >/dev/null && ok "已设置 1 秒" || warn "设置失败，可稍后在界面调整"

step "开机自启 / linger"
if [ "$NO_LINGER" -eq 1 ]; then
  warn "已跳过 linger"
else
  LINGER="$(loginctl show-user "$USER_NAME" -p Linger 2>/dev/null || true)"
  if printf '%s' "$LINGER" | grep -q 'Linger=yes'; then
    ok "linger 已开启"
  elif sudo -n loginctl enable-linger "$USER_NAME" 2>/dev/null; then
    ok "已开启 linger（免密 sudo）"
  else
    warn "需要 sudo 开启 linger；手动执行: sudo loginctl enable-linger $USER_NAME"
  fi
fi

step "悬浮小屏自启"
if [ "$NO_PALETTE" -eq 1 ]; then
  warn "已跳过"
else
  mkdir -p "$AUTOSTART_DIR"
  if [ -f "$AUTOSTART" ]; then
    cp -p "$AUTOSTART" "$AUTOSTART.bak.$(date +%Y%m%d-%H%M%S)"
  fi
  cat > "$AUTOSTART" <<EOF
[Desktop Entry]
Type=Application
Name=Deckpit Palette
Comment=Deckpit 悬浮小屏
Exec="$PROJECT_DIR/scripts/start-palette.sh"
Terminal=false
X-GNOME-Autostart-enabled=true
OnlyShowIn=GNOME;
EOF
  chmod 644 "$AUTOSTART"
  ok "已写入 $AUTOSTART"
  if [ -n "${DISPLAY:-}" ]; then
    "$PROJECT_DIR/scripts/start-palette.sh" || warn "当前会话启动小屏失败，查看 data/logs/palette.log"
  else
    warn "当前没有 DISPLAY，登录桌面后由 autostart 启动"
  fi
fi

step "日志轮转"
if [ "$NO_LOGROTATE" -eq 1 ]; then
  warn "已跳过"
elif command -v logrotate >/dev/null 2>&1; then
  if sudo -n tee /etc/logrotate.d/deckpit >/dev/null 2>&1 <<EOF
"$LOG_DIR"/*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}
EOF
  then
    ok "已写入 /etc/logrotate.d/deckpit"
  else
    warn "需要 sudo 写 /etc/logrotate.d/deckpit；可稍后手动配置"
  fi
else
  warn "未安装 logrotate，跳过"
fi

step "完成"
cat <<EOF
  管理命令:
    ./scripts/deckpit.sh status
    ./scripts/deckpit.sh restart
    ./scripts/deckpit.sh logs -f
    ./scripts/deckpit.sh palette start|stop
  本机:   http://127.0.0.1:$PORT
  局域网: http://$(hostname -I 2>/dev/null | awk '{print $1}'):$PORT
EOF
