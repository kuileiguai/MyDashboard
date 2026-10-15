#!/bin/bash
# setup.sh — Deckpit 一站式部署向导
#
# 本服务会以「运行它的那个用户」的身份执行任意命令、读写文件、管理进程，
# 权限等级等同于把该用户的 shell 交出去。因此部署阶段必须一次配好：
#   系统依赖 · 运行环境 · 登录口令 · 监听范围 · 防火墙 · 开机自启
#
# 用法：
#   ./scripts/setup.sh                 # 交互式向导（每步都要确认）
#   DASH_SETUP_YES=1 ./scripts/setup.sh  # 非交互：全部采用推荐默认值
#
# 可用环境变量预置答案（非交互用）:
#   DASH_SETUP_HOST=0.0.0.0       监听地址（0.0.0.0 局域网 / 127.0.0.1 仅本机）
#   DASH_SETUP_PORT=8787
#   DASH_SETUP_USER=admin         登录用户名
#   DASH_SETUP_PASSWORD=xxx       不设则自动生成 20 位随机口令
#   DASH_SETUP_LAN_CIDR=192.168.0.0/24
#   DASH_SETUP_APT=1              允许用 sudo apt 安装缺失依赖
#   DASH_SETUP_UFW=1              允许用 sudo ufw 加防火墙规则
#   DASH_SETUP_SERVICE=1          安装并启用 systemd 用户服务
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${DASH_ENV_FILE:-$HOME/.config/deckpit.env}"
# unit 内容在下方按实际路径生成（$PROJECT_DIR 可能含空格，需 sd_escape）
UNIT_DST="$HOME/.config/systemd/user/deckpit.service"
LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

HOST_VAL="${DASH_SETUP_HOST:-}"
PORT_VAL="${DASH_SETUP_PORT:-8787}"
USER_VAL="${DASH_SETUP_USER:-}"
PASS_VAL="${DASH_SETUP_PASSWORD:-}"
LAN_CIDR="${DASH_SETUP_LAN_CIDR:-}"
YES="${DASH_SETUP_YES:-0}"

if [ -t 1 ]; then
  C_RED=$'\033[31m'; C_YEL=$'\033[33m'; C_GRN=$'\033[32m'; C_BLU=$'\033[36m'; C_BLD=$'\033[1m'; C_OFF=$'\033[0m'
else
  C_RED=""; C_YEL=""; C_GRN=""; C_BLU=""; C_BLD=""; C_OFF=""
fi

hdr() { printf '\n%s══ %s ══%s\n' "$C_BLU" "$*" "$C_OFF"; }
log() { printf '  %s\n' "$*"; }
ok()  { printf '  %s✓%s %s\n' "$C_GRN" "$C_OFF" "$*"; }
warn() { printf '  %s!%s %s\n' "$C_YEL" "$C_OFF" "$*"; }
err() { printf '  %s✗%s %s\n' "$C_RED" "$C_OFF" "$*"; }

# 交互确认：$1 提示语，$2 默认值(Y/N)；非交互模式直接返回默认值
confirm() {
  local prompt="$1" def="${2:-Y}" ans
  if [ "$YES" = "1" ]; then
    [ "$def" = "Y" ] && return 0 || return 1
  fi
  if [ ! -t 0 ]; then
    [ "$def" = "Y" ] && return 0 || return 1
  fi
  printf '  %s [Y/n]: ' "$prompt"
  read -r ans || ans=""
  [ -z "$ans" ] && ans="$def"
  case "$ans" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

ask() {
  local prompt="$1" def="$2" ans
  if [ "$YES" = "1" ] || [ ! -t 0 ]; then printf '%s' "$def"; return; fi
  printf '  %s [%s]: ' "$prompt" "$def"
  read -r ans || ans=""
  [ -z "$ans" ] && ans="$def"
  printf '%s' "$ans"
}

random_password() {
  LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom 2>/dev/null | head -c 20
  printf '\n'
}

# systemd 的 ExecStart/WorkingDirectory 不支持裸空格，需转义为 \x20
sd_escape() { printf '%s' "$1" | sed 's/ /\\x20/g'; }

# ── 0. 权限等级告知 ──────────────────────────────────────────────
hdr "0. 权限等级确认"
log "Deckpit 会以运行它的用户身份：执行任意 shell 命令、读写该用户有权访问的文件、"
log "结束任意进程、管理 systemd 用户服务与 Docker。权限等同于交出该用户的终端。"
log ""
if [ "$(id -u)" = "0" ]; then
  err "当前以 root 运行 —— 服务将拥有 root shell，风险极高。"
  if ! confirm "仍要继续？强烈建议改用普通用户" N; then
    log "已中止。请改用普通用户重新执行本脚本。"
    exit 1
  fi
else
  ok "运行用户: $(id -un)（非 root，符合预期）"
fi
if id -nG "$USER" 2>/dev/null | grep -qw docker; then
  warn "当前用户在 docker 组 —— 等同 root 权限（可挂载宿主机根目录），请知悉。"
fi

# ── 1. 依赖预检 ──────────────────────────────────────────────────
hdr "1. 依赖预检"
if [ -x "$SCRIPT_DIR/check-env.sh" ]; then
  bash "$SCRIPT_DIR/check-env.sh" || true
else
  warn "未找到 scripts/check-env.sh，跳过预检"
fi

# 缺失的 apt 包（命令 -> 包名）
need_pkgs=""
for pair in "ss:iproute2" "curl:curl" "xdotool:xdotool" "wmctrl:wmctrl" "xprop:x11-utils" "tmux:tmux"; do
  cmd="${pair%%:*}"; pkg="${pair##*:}"
  command -v "$cmd" >/dev/null 2>&1 || need_pkgs="$need_pkgs $pkg"
done
need_pkgs="$(echo "$need_pkgs" | tr -s ' ')"

if [ -n "$need_pkgs" ]; then
  hdr "1.1 系统依赖安装"
  warn "缺失:$need_pkgs"
  log "  其中 tmux = 远程接管外部终端；wmctrl/xdotool/xprop = 外部终端窗口控制；ss = 端口监控"
  if [ "${DASH_SETUP_APT:-}" = "1" ] || confirm "执行 sudo apt install -y$need_pkgs ?" Y; then
    if sudo apt install -y $need_pkgs; then
      ok "系统依赖安装完成"
    else
      err "安装失败，可稍后手动执行: sudo apt install -y$need_pkgs"
    fi
  else
    warn "已跳过，相关功能将不可用"
  fi
else
  ok "系统依赖齐全"
fi

# ── 2. 运行环境（venv / dist） ───────────────────────────────────
hdr "2. 运行环境"
if [ ! -x "$PROJECT_DIR/backend/.venv/bin/python" ] || [ ! -f "$PROJECT_DIR/frontend/dist/index.html" ]; then
  if confirm "自动补齐 backend/.venv 与 frontend/dist（./scripts/check-env.sh --fix）?" Y; then
    bash "$SCRIPT_DIR/check-env.sh" --fix || true
  else
    warn "已跳过；未完成前服务无法启动"
  fi
else
  ok "backend/.venv 与 frontend/dist 均已就绪"
fi

# ── 3. 安全配置：监听范围 + 登录口令 ─────────────────────────────
hdr "3. 监听范围"
log "  1) 0.0.0.0 —— 局域网内其他机器可访问，但非本机来源必须登录（推荐）"
log "  2) 127.0.0.1 —— 仅服务器本机可访问，无需登录"
if [ -z "$HOST_VAL" ]; then
  HOST_VAL="$(ask '选择 1 或 2' 1)"
  case "$HOST_VAL" in
    2|127.0.0.1) HOST_VAL="127.0.0.1" ;;
    *) HOST_VAL="0.0.0.0" ;;
  esac
fi
ok "监听地址: $HOST_VAL"

hdr "3.1 登录口令（非本机访问时使用）"
[ -z "$USER_VAL" ] && USER_VAL="$(ask '登录用户名' admin)"
if [ -f "$ENV_FILE" ] && [ -z "$PASS_VAL" ]; then
  if confirm "已存在 $ENV_FILE，重新生成随机口令？" N; then
    PASS_VAL="$(random_password)"
  else
    PASS_VAL="$(grep -E '^DASH_AUTH_PASSWORD=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2-)"
    [ -z "$PASS_VAL" ] && PASS_VAL="$(random_password)"
  fi
fi
[ -z "$PASS_VAL" ] && PASS_VAL="$(random_password)"

mkdir -p "$(dirname "$ENV_FILE")"
cat > "$ENV_FILE" <<EOF
# Deckpit 部署配置（由 scripts/setup.sh 生成，权限 600）
DASH_HOST=$HOST_VAL
DASH_PORT=$PORT_VAL
DASH_AUTH_USER=$USER_VAL
DASH_AUTH_PASSWORD=$PASS_VAL
EOF
chmod 600 "$ENV_FILE"
ok "已写入 $ENV_FILE（权限 600）"
if [ "$HOST_VAL" != "127.0.0.1" ] && [ -z "$(grep -E '^DASH_AUTH_PASSWORD=.+' "$ENV_FILE")" ]; then
  err "未设置口令，非本机访问会被拒绝"
fi

# ── 4. 防火墙 ────────────────────────────────────────────────────
hdr "4. 防火墙"
if [ "$HOST_VAL" = "127.0.0.1" ]; then
  ok "仅本机监听，无需放行端口"
elif ! command -v ufw >/dev/null 2>&1; then
  warn "未安装 ufw，跳过；请自行确保 $PORT_VAL 只对内网开放"
else
  if [ -z "$LAN_CIDR" ] && [ -n "$LAN_IP" ]; then
    LAN_CIDR="$(printf '%s' "$LAN_IP" | awk -F. '{print $1"."$2"."$3".0/24"}')"
  fi
  LAN_CIDR="$(ask '允许访问的来源网段' "${LAN_CIDR:-192.168.0.0/24}")"
  log "  将执行: sudo ufw allow from $LAN_CIDR to any port $PORT_VAL"
  if [ "${DASH_SETUP_UFW:-}" = "1" ] || confirm "添加该规则（只放行内网，不放行公网）?" Y; then
    if sudo ufw allow from "$LAN_CIDR" to any port "$PORT_VAL"; then
      ok "防火墙规则已添加"
    else
      err "添加失败，可手动执行上述命令"
    fi
  else
    warn "已跳过。注意：未配防火墙时端口对同网段所有机器开放"
  fi
fi

# ── 5. systemd 用户服务 ──────────────────────────────────────────
hdr "5. 开机自启（systemd 用户服务）"
if ! command -v systemctl >/dev/null 2>&1; then
  warn "无 systemd，跳过；可用 ./scripts/run-prod.sh 前台运行"
else
  if [ "${DASH_SETUP_SERVICE:-}" = "1" ] || confirm "安装 ~/.config/systemd/user/deckpit.service 并设为开机自启?" Y; then
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$UNIT_DST" <<EOF
[Unit]
Description=Deckpit — Linux 开发者工作台
After=default.target

[Service]
WorkingDirectory=$(sd_escape "$PROJECT_DIR/backend")
Environment=DASH_HOST=$HOST_VAL
Environment=DASH_PORT=$PORT_VAL
EnvironmentFile=-$(sd_escape "$ENV_FILE")
ExecStart=$(sd_escape "$PROJECT_DIR/backend/.venv/bin/uvicorn") main:app --host \${DASH_HOST} --port \${DASH_PORT}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable deckpit.service && ok "已设为开机自启"
    if [ "${DASH_SETUP_SERVICE:-}" = "1" ] || confirm "立即启动服务?" Y; then
      systemctl --user restart deckpit.service && ok "服务已启动"
      sleep 2
      systemctl --user is-active deckpit.service
    fi
    log ""
    log "  常用命令:"
    log "    systemctl --user status deckpit"
    log "    journalctl --user -u deckpit -f"
    log "  注销后仍要保持运行（服务器场景）: sudo loginctl enable-linger $USER"
  else
    warn "已跳过自启；手动启动: DASH_AUTH_PASSWORD=... ./scripts/run-prod.sh"
  fi
fi

# ── 6. 总结 ──────────────────────────────────────────────────────
hdr "部署完成"
log "  本机访问:   http://localhost:$PORT_VAL"
[ -n "$LAN_IP" ] && [ "$HOST_VAL" = "0.0.0.0" ] && log "  局域网访问: http://$LAN_IP:$PORT_VAL"
log ""
printf '  %s登录账号:%s %s\n' "$C_BLD" "$C_OFF" "$USER_VAL"
printf '  %s登录口令:%s %s\n' "$C_BLD" "$C_OFF" "$PASS_VAL"
log ""
warn "请立即保存口令（不会再次显示）。修改方式: 编辑 $ENV_FILE 后"
log "  systemctl --user restart deckpit"
log ""
warn "安全提醒: 该面板等同当前用户的终端权限——不要用 root 运行、不要暴露到公网、"
log "  口令不要用弱密码、离开时记得在系统托盘退出或关闭服务。"
exit 0
