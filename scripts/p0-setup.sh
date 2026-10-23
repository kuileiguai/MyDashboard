#!/bin/bash
# p0-setup.sh — Deckpit P0 一键加固
#
# 做四件事：
#   1. 设置 Deckpit 网页登录用户名和口令（写入 .env，600）
#   2. 收紧 data/、dashboard.db、.ssh_key 权限
#   3. Docker socket 恢复 root:docker 660，并把当前用户加入 docker 组
#   4. UFW 放行 SSH 和局域网 8787（只放行指定网段）
#   5. 检测到 DISPLAY 时启动悬浮小屏（--no-palette 可关闭）
#   最后重启后端并验证新口令。
#
# 用法：
#   ./scripts/p0-setup.sh                    # 交互式
#   ./scripts/p0-setup.sh --generate         # 自动生成 24 位口令
#   ./scripts/p0-setup.sh --yes --generate   # 非交互（全部采用默认）
#
# 可选参数：
#   --host HOST          监听地址，默认 0.0.0.0
#   --port PORT          端口，默认读 .env 的 DASH_PORT 或 8787
#   --lan-cidr CIDR      允许访问 8787 的网段，默认按主 IP 推算 /24
#   --ssh-port PORT      UFW 放行的 SSH 端口，默认自动探测 sshd
#   --user USER          指定网页登录用户名；交互式不传则询问（默认 admin）
#   --no-docker          跳过 Docker socket/组修复
#   --no-ufw             跳过 UFW
#   --no-restart         只改配置，不重启
#   --palette            强制启动悬浮小屏（默认有 DISPLAY 就启动）
#   --no-palette         跳过悬浮小屏
#   --keep-password      使用 .env 里已有的明文口令，不提示输入
#   --min-length N       新口令最小长度，默认 6
#   --yes                跳过确认
#   -h, --help           显示帮助
#
# 口令来源（任选其一）：
#   --keep-password                          复用 .env 里已有的明文口令
#   DASH_SETUP_PASSWORD_FILE=/path/to/file   从文件第一行读
#   DASH_SETUP_PASSWORD_STDIN=1              从 stdin 读
#   --generate                               自动生成
#
# 注意：
#   · 请用普通用户运行，不要用 root；脚本内部按需 sudo。
#   · 需要 backend/.venv 和 frontend/dist 已存在（先完成构建）。
#   · 会备份 .env 到同目录 .bak.<时间戳>。
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RUN_USER="$(id -un)"

YES=0
GENERATE=0
NO_DOCKER=0
NO_UFW=0
NO_RESTART=0
PALETTE=0
FORCE_PALETTE=0
NO_PALETTE=0
KEEP_PASSWORD=0
MIN_LEN=6
USER_SET=0
HOST="0.0.0.0"
PORT=""
LAN_CIDR=""
SSH_PORT=""
AUTH_USER=""

usage() {
  awk 'NR==1{next} /^set -Eeuo/{exit} /^#/{sub(/^# ?/,""); print} /^$/{print}' "$0"
  exit 0
}

die()  { printf '\n[错误] %s\n' "$*" >&2; exit 1; }
ok()   { printf '  [OK] %s\n' "$*"; }
warn() { printf '  [注意] %s\n' "$*"; }
step() { printf '\n== %s ==\n' "$*"; }

# 用给定用户名/口令调用登录接口，只输出 HTTP 状态码
login_code() {
  local user="$1" pass="$2" payload
  payload="$(AUTH_USER="$user" AUTH_PASS="$pass" python3 -c \
    'import json,os; print(json.dumps({"username":os.environ["AUTH_USER"],"password":os.environ["AUTH_PASS"]}))')"
  printf '%s' "$payload" | curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
    -X POST "http://127.0.0.1:${PORT}/api/auth/login" \
    -H 'Content-Type: application/json' --data-binary @- 2>/dev/null || true
}

# 验证某个旧口令已失效；如果它等于新口令则跳过
check_old_password() {
  local label="$1" pass="$2" code
  [ -n "$pass" ] || return 0
  [ "$pass" = "$PASSWORD" ] && return 0
  code="$(login_code "$AUTH_USER" "$pass")"
  case "$code" in
    200) die "$label 仍然有效；检查是否重启成功、是否还有另一个实例、或 DASH_ENV_FILE 是否指向别处" ;;
    401) ok "$label 已失效（401）" ;;
    429) die "登录失败次数过多，已被临时锁定（429）；等 5 分钟再重试" ;;
    *)   warn "$label 测试返回: ${code:-无响应}" ;;
  esac
}

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="${2:-}"; shift 2 ;;
    --port) PORT="${2:-}"; shift 2 ;;
    --lan-cidr) LAN_CIDR="${2:-}"; shift 2 ;;
    --ssh-port) SSH_PORT="${2:-}"; shift 2 ;;
    --user) AUTH_USER="${2:-}"; USER_SET=1; shift 2 ;;
    --no-docker) NO_DOCKER=1; shift ;;
    --no-ufw) NO_UFW=1; shift ;;
    --no-restart) NO_RESTART=1; shift ;;
    --palette) FORCE_PALETTE=1; shift ;;
    --no-palette) NO_PALETTE=1; shift ;;
    --keep-password) KEEP_PASSWORD=1; shift ;;
    --min-length) MIN_LEN="${2:-}"; shift 2 ;;
    --generate) GENERATE=1; shift ;;
    --yes|-y) YES=1; shift ;;
    -h|--help) usage ;;
    *) die "未知参数: $1（用 --help 查看用法）" ;;
  esac
done

case "$MIN_LEN" in
  ''|*[!0-9]*) die "--min-length 需要是数字。" ;;
esac
[ "$MIN_LEN" -ge 6 ] && [ "$MIN_LEN" -le 128 ] || die "--min-length 需要在 6..128 之间。"
[ "$KEEP_PASSWORD" -eq 1 ] && [ "$GENERATE" -eq 1 ] && die "--keep-password 和 --generate 不能同时用。"

if [ "$NO_PALETTE" -eq 1 ]; then
  PALETTE=0
elif [ "$FORCE_PALETTE" -eq 1 ]; then
  PALETTE=1
elif [ -n "${DISPLAY:-}" ]; then
  # 默认：有 X11 DISPLAY 就顺带启动悬浮小屏
  PALETTE=1
else
  PALETTE=0
fi
if [ "$PALETTE" -eq 1 ] && [ -z "${DISPLAY:-}" ]; then
  warn "没有 DISPLAY，悬浮小屏可能无法显示；用 --no-palette 可跳过。"
fi

# ── 0. 基本检查 ────────────────────────────────────────────────
[ "$(id -u)" -ne 0 ] || die "请不要用 root 运行；用部署用户运行，脚本内部会按需 sudo。"
[ -f "$PROJECT_DIR/backend/.venv/bin/uvicorn" ] || die "缺少 backend/.venv，请先完成 Python 依赖安装。"
[ -f "$PROJECT_DIR/frontend/dist/index.html" ] || die "缺少 frontend/dist/index.html，请先构建前端。"

for c in python3 curl; do
  command -v "$c" >/dev/null 2>&1 || die "缺少命令: $c"
done

ENV_FILE="${DASH_ENV_FILE:-$PROJECT_DIR/backend/.env}"
case "$ENV_FILE" in
  "~/"*) ENV_FILE="$HOME/${ENV_FILE#~/}" ;;
  /*) ;;
  *) ENV_FILE="$PROJECT_DIR/$ENV_FILE" ;;
esac
[ -f "$ENV_FILE" ] || die "配置文件不存在: $ENV_FILE"

# 从 config.py 读源码里的默认口令（不在脚本里重复写死，避免被误改）
CONFIG_DEFAULT_PASSWORD=""
if [ -f "$PROJECT_DIR/backend/config.py" ]; then
  CONFIG_DEFAULT_PASSWORD="$(python3 - "$PROJECT_DIR/backend/config.py" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r'AUTH_PASSWORD\s*=\s*_str\(\s*"DASH_AUTH_PASSWORD"\s*,\s*"([^"]*)"\s*\)', text)
print(m.group(1) if m else "")
PY
)"
fi

# 读现有端口/用户名（只读，不打印值）
ENV_PORT="$(grep -E '^[[:space:]]*(export[[:space:]]+)?DASH_PORT=' "$ENV_FILE" 2>/dev/null | tail -1 | sed -E 's/^[^=]*=//' || true)"
PORT="${PORT:-${ENV_PORT:-8787}}"
case "$PORT" in ''|*[!0-9]*) die "端口不合法: $PORT" ;; esac

if [ "$USER_SET" -eq 0 ]; then
  AUTH_USER="$(grep -E '^[[:space:]]*(export[[:space:]]+)?DASH_AUTH_USER=' "$ENV_FILE" 2>/dev/null | tail -1 | sed -E 's/^[^=]*=//' || true)"
  AUTH_USER="${AUTH_USER%\"}"; AUTH_USER="${AUTH_USER#\"}"
  AUTH_USER="${AUTH_USER:-admin}"
fi
case "$AUTH_USER" in
  ''|*[!A-Za-z0-9_.-]*)
    if [ "$USER_SET" -eq 1 ]; then
      die "用户名只能包含字母、数字、下划线、点和短横线。"
    fi
    warn "现有用户名不合法，回退为 admin"
    AUTH_USER="admin"
    ;;
esac

LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}' || true)"
LAN_IP="${LAN_IP:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
if [ -z "$LAN_CIDR" ] && [ -n "$LAN_IP" ]; then
  LAN_CIDR="$(printf '%s' "$LAN_IP" | awk -F. '{print $1"."$2"."$3".0/24"}')"
fi
LAN_CIDR="${LAN_CIDR:-192.168.0.0/24}"

# ── 1. 权限与 sudo ─────────────────────────────────────────────
NEED_SUDO=0
[ "$NO_DOCKER" -eq 0 ] && NEED_SUDO=1
[ "$NO_UFW" -eq 0 ] && NEED_SUDO=1
HAS_SUDO=0
if [ "$NEED_SUDO" -eq 1 ]; then
  step "检查 sudo"
  if sudo -v; then
    HAS_SUDO=1
    ok "sudo 可用"
  else
    die "需要 sudo 来修 Docker/UFW；如果不想改这两项，用 --no-docker --no-ufw 重跑。"
  fi
fi

# ── 2. 网页登录账号 ────────────────────────────────────────────
step "设置网页登录账号"
if [ "$USER_SET" -eq 0 ] && [ "$YES" -ne 1 ] && [ -t 0 ]; then
  read -rp "网页登录用户名 [$AUTH_USER]: " _input_user || true
  [ -n "${_input_user:-}" ] && AUTH_USER="$_input_user"
  unset _input_user
  case "$AUTH_USER" in
    ''|*[!A-Za-z0-9_.-]*) die "用户名只能包含字母、数字、下划线、点和短横线。" ;;
  esac
fi
ok "登录用户名: $AUTH_USER"

step "设置网页登录口令"
if [ "$KEEP_PASSWORD" -eq 1 ]; then
  if grep -qE '^[[:space:]]*(export[[:space:]]+)?DASH_AUTH_PASSWORD_HASH=' "$ENV_FILE"; then
    die "当前 .env 里 DASH_AUTH_PASSWORD_HASH 仍启用，会覆盖明文；请先注释 hash，或不要用 --keep-password。"
  fi
  PASSWORD="$(grep -E '^[[:space:]]*(export[[:space:]]+)?DASH_AUTH_PASSWORD=' "$ENV_FILE" 2>/dev/null | tail -1 | sed -E 's/^[^=]*=//' || true)"
  [ -n "$PASSWORD" ] || die "当前 .env 没有明文 DASH_AUTH_PASSWORD，无法 --keep-password；请设置明文，或不用该参数。"
  ok "使用 .env 中现有口令（长度 ${#PASSWORD}，不显示）"
elif [ "$GENERATE" -eq 1 ]; then
  PASSWORD="$(python3 -c 'import secrets,string; print("".join(secrets.choice(string.ascii_letters+string.digits) for _ in range(24)))')"
elif [ -n "${DASH_SETUP_PASSWORD_FILE:-}" ]; then
  [ -f "$DASH_SETUP_PASSWORD_FILE" ] || die "口令文件不存在: $DASH_SETUP_PASSWORD_FILE"
  IFS= read -r PASSWORD < "$DASH_SETUP_PASSWORD_FILE" || true
elif [ "${DASH_SETUP_PASSWORD_STDIN:-0}" = "1" ]; then
  IFS= read -r PASSWORD || true
elif [ -t 0 ]; then
  read -rsp "新口令（至少 ${MIN_LEN} 位，输入不显示）: " PASSWORD; echo
  read -rsp "再输一次: " PASSWORD2; echo
  [ "$PASSWORD" = "$PASSWORD2" ] || die "两次输入不一致。"
  unset PASSWORD2
else
  die "非交互模式需要 --generate，或设置 DASH_SETUP_PASSWORD_FILE / DASH_SETUP_PASSWORD_STDIN=1。"
fi

[ -n "$PASSWORD" ] || die "口令不能为空。"
# config.py 解析出的默认口令
if [ -n "$CONFIG_DEFAULT_PASSWORD" ] && [ "$PASSWORD" = "$CONFIG_DEFAULT_PASSWORD" ]; then
  die "不要使用 config.py 里的默认口令。"
fi
# 源码/历史里出现过的默认口令和明显弱口令
for bad in "123456" "12345678" "password" "admin" "000000" "111111"; do
  [ "$PASSWORD" != "$bad" ] || die "不要使用默认口令或常见弱口令，换一个。"
done
case "$PASSWORD" in
  *[[:space:]]*) die "口令不要包含空格。" ;;
  *\"*|*\'*) die "口令不要包含单双引号。" ;;
esac

[ "${#PASSWORD}" -ge "$MIN_LEN" ] || die "口令至少 $MIN_LEN 位。"
if [ "${#PASSWORD}" -lt 12 ]; then
  warn "口令只有 ${#PASSWORD} 位；8787 对局域网开放，建议至少 12 位（6 位可用，但风险较高）。"
fi
ok "口令长度 ${#PASSWORD}（不显示内容）"

# ── 3. 确认 ────────────────────────────────────────────────────
step "将要执行"
if [ "$NO_RESTART" -eq 1 ]; then
  PALETTE_DESC="跳过（未重启）"
elif [ "$PALETTE" -eq 1 ]; then
  PALETTE_DESC="启动（DISPLAY=${DISPLAY:-无}）"
else
  PALETTE_DESC="跳过"
fi
cat <<EOF
  配置:       $ENV_FILE
  登录用户:   $AUTH_USER
  监听:       $HOST:$PORT
  局域网网段: $LAN_CIDR
  备份:       $ENV_FILE.bak.<时间戳>
  权限:       data 700 / env,db,.ssh_key 600
  Docker:     $([ "$NO_DOCKER" -eq 1 ] && echo 跳过 || echo root:docker 660 + 加入 docker 组)
  UFW:        $([ "$NO_UFW" -eq 1 ] && echo 跳过 || echo 放行 SSH + $LAN_CIDR -> $PORT)
  重启后端:   $([ "$NO_RESTART" -eq 1 ] && echo 跳过 || echo 是)
  悬浮小屏:   $PALETTE_DESC
EOF
if [ "$YES" -ne 1 ]; then
  read -rp "继续? [y/N]: " ans
  case "$ans" in [Yy]*) ;; *) die "已取消。" ;; esac
fi

# ── 4. 备份并写配置 ────────────────────────────────────────────
step "备份并更新配置"
BACKUP="$ENV_FILE.bak.$(date +%Y%m%d-%H%M%S)"
cp -p "$ENV_FILE" "$BACKUP"
ok "已备份: $BACKUP"

NEW_PASSWORD="$PASSWORD" NEW_USER="$AUTH_USER" NEW_HOST="$HOST" NEW_PORT="$PORT" ENV_FILE="$ENV_FILE" python3 - <<'PY'
import os, re
from pathlib import Path

p = Path(os.environ["ENV_FILE"])
text = p.read_text(encoding="utf-8")
out = []
for line in text.splitlines():
    # 清掉旧的明文口令、hash、用户名、监听地址；后面统一追加
    if re.match(r"^\s*(?:export\s+)?DASH_AUTH_PASSWORD\s*=", line):
        continue
    if re.match(r"^\s*(?:export\s+)?DASH_AUTH_PASSWORD_HASH\s*=", line):
        out.append("# " + line.lstrip())
        continue
    if re.match(r"^\s*(?:export\s+)?DASH_AUTH_USER\s*=", line):
        continue
    if re.match(r"^\s*(?:export\s+)?DASH_HOST\s*=", line):
        continue
    if re.match(r"^\s*(?:export\s+)?DASH_PORT\s*=", line):
        continue
    out.append(line)

out.append("# P0 setup: 明文口令，文件权限 600；如需 hash 可自行替换")
out.append(f"DASH_AUTH_USER={os.environ['NEW_USER']}")
out.append(f"DASH_AUTH_PASSWORD={os.environ['NEW_PASSWORD']}")
out.append(f"DASH_HOST={os.environ['NEW_HOST']}")
out.append(f"DASH_PORT={os.environ['NEW_PORT']}")

p.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
p.chmod(0o600)
print("  [OK] 配置已更新并设为 600")
PY

# ── 5. 文件权限 ────────────────────────────────────────────────
step "收紧文件权限"
mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/data/logs"
chmod 700 "$PROJECT_DIR/data" "$PROJECT_DIR/data/logs"
[ -e "$PROJECT_DIR/data/dashboard.db" ] && chmod 600 "$PROJECT_DIR/data/dashboard.db"
[ -e "$PROJECT_DIR/data/.ssh_key" ] && chmod 600 "$PROJECT_DIR/data/.ssh_key"
chmod 600 "$ENV_FILE"
[ -d "$HOME/.config/deckpit" ] && chmod 700 "$HOME/.config/deckpit"
[ -f "$HOME/.config/deckpit/deckpit.env" ] && chmod 600 "$HOME/.config/deckpit/deckpit.env"
[ -f "$HOME/.config/deckpit.env" ] && chmod 600 "$HOME/.config/deckpit.env"
ok "权限已收紧"

# ── 6. Docker ──────────────────────────────────────────────────
if [ "$NO_DOCKER" -eq 0 ]; then
  step "修复 Docker socket"
  if [ -x "$SCRIPT_DIR/fix-docker-perms.sh" ]; then
    sudo "$SCRIPT_DIR/fix-docker-perms.sh" "$RUN_USER"
  else
    warn "未找到 fix-docker-perms.sh，使用内联命令"
    sudo chown root:docker /var/run/docker.sock
    sudo chmod 660 /var/run/docker.sock
    sudo usermod -aG docker "$RUN_USER"
  fi
  ok "socket 已恢复 root:docker 660"
  if docker ps >/dev/null 2>&1; then
    ok "当前会话已可执行 docker ps"
  else
    warn "当前会话还没有 docker 组；请注销重登，或另开终端执行 newgrp docker 后再 docker ps"
  fi
fi

# ── 7. UFW ─────────────────────────────────────────────────────
if [ "$NO_UFW" -eq 0 ]; then
  step "配置 UFW"
  command -v ufw >/dev/null 2>&1 || die "未安装 ufw；用 --no-ufw 跳过，或先 sudo apt install -y ufw"

  if [ -z "$SSH_PORT" ]; then
    SSH_PORT="$(sudo sshd -T 2>/dev/null | awk '/^port /{print $2; exit}' || true)"
  fi
  SSH_PORT="${SSH_PORT:-22}"

  # 先放行 SSH，避免启用 UFW 后把自己关在门外
  sudo ufw allow "$SSH_PORT/tcp" >/dev/null
  ok "已放行 SSH: $SSH_PORT/tcp"
  sudo ufw allow from "$LAN_CIDR" to any port "$PORT" proto tcp >/dev/null
  ok "已放行 $LAN_CIDR -> $PORT/tcp"

  UFW_STATUS="$(sudo ufw status 2>/dev/null || true)"
  if printf '%s' "$UFW_STATUS" | grep -q '^Status: active'; then
    ok "UFW 已是启用状态"
  else
    ENABLE_UFW=0
    if [ "$YES" -eq 1 ]; then
      ENABLE_UFW=1
    elif [ -t 0 ]; then
      read -rp "UFW 未启用，确认现在启用? [y/N]: " ans
      case "$ans" in [Yy]*) ENABLE_UFW=1 ;; *) warn "已跳过启用；规则已写入，启用后生效" ;; esac
    fi
    if [ "$ENABLE_UFW" -eq 1 ]; then
      sudo ufw --force enable
      ok "UFW 已启用"
    fi
  fi
  sudo ufw status numbered || true
fi

# ── 8. 重启后端 ────────────────────────────────────────────────
LOG_FILE="$PROJECT_DIR/data/logs/deckpit.log"
if [ "$NO_RESTART" -eq 0 ]; then
  step "重启后端"
  mkdir -p "$PROJECT_DIR/data/logs"

  if systemctl --user cat deckpit >/dev/null 2>&1; then
    systemctl --user restart deckpit || die "systemd 重启失败，请查看 journalctl --user -u deckpit -n 100"
    ok "已通过 systemd 重启 deckpit"
  else
    PID=""
    if command -v ss >/dev/null 2>&1; then
      if [ "$HAS_SUDO" -eq 1 ]; then
        PID="$(sudo ss -tlnp "sport = :$PORT" 2>/dev/null | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | head -1 || true)"
      else
        PID="$(ss -tlnp "sport = :$PORT" 2>/dev/null | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | head -1 || true)"
      fi
    fi
    if [ -z "$PID" ] && command -v lsof >/dev/null 2>&1; then
      if [ "$HAS_SUDO" -eq 1 ]; then
        PID="$(sudo lsof -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1 || true)"
      else
        PID="$(lsof -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1 || true)"
      fi
    fi

    if [ -n "$PID" ]; then
      echo "  停止旧进程 PID=$PID"
      if [ "$HAS_SUDO" -eq 1 ]; then sudo kill "$PID" 2>/dev/null || true; else kill "$PID" 2>/dev/null || true; fi
      for _ in $(seq 1 10); do
        kill -0 "$PID" 2>/dev/null || break
        sleep 1
      done
      if kill -0 "$PID" 2>/dev/null; then
        echo "  旧进程未退出，SIGKILL"
        if [ "$HAS_SUDO" -eq 1 ]; then sudo kill -9 "$PID" 2>/dev/null || true; else kill -9 "$PID" 2>/dev/null || true; fi
      fi
    fi

    if [ "$HAS_SUDO" -eq 1 ]; then
      PORT_STATE="$(sudo ss -tln "sport = :$PORT" 2>/dev/null || true)"
    else
      PORT_STATE="$(ss -tln "sport = :$PORT" 2>/dev/null || true)"
    fi
    case "$PORT_STATE" in
      *LISTEN*) die "端口 $PORT 仍被占用，请手动停止后重试。" ;;
    esac

    echo "  启动后端（日志: $LOG_FILE）"
    (
      cd "$PROJECT_DIR"
      nohup env DASH_PALETTE="$PALETTE" DASH_HOST="$HOST" DASH_PORT="$PORT" \
        bash ./scripts/run-prod.sh >>"$LOG_FILE" 2>&1 &
      echo $! > "$PROJECT_DIR/data/deckpit.pid"
    )
    ok "已启动，PID 文件: data/deckpit.pid"
  fi

  step "等待后端就绪"
  READY=0
  for _ in $(seq 1 30); do
    if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/api/auth/status" >/dev/null 2>&1; then
      READY=1
      break
    fi
    sleep 1
  done
  if [ "$READY" -ne 1 ]; then
    echo "启动失败，最近日志：" >&2
    tail -50 "$LOG_FILE" 2>/dev/null || journalctl --user -u deckpit -n 50 --no-pager 2>/dev/null || true
    die "后端未在 30 秒内就绪"
  fi
  ok "后端已就绪"

  if [ "$PALETTE" -eq 1 ]; then
    sleep 2
    if command -v pgrep >/dev/null 2>&1 && pgrep -f "$PROJECT_DIR/scripts/quickpalette.py" >/dev/null 2>&1; then
      ok "悬浮小屏已启动"
    else
      warn "悬浮小屏未检测到；查看 $LOG_FILE 里的 quickpalette 输出"
    fi
  fi
fi

# ── 9. 验证 ────────────────────────────────────────────────────
step "验证"
if [ "$NO_RESTART" -eq 1 ]; then
  warn "已跳过重启和在线验证；新口令将在下次启动后生效"
else
  check_old_password "config.py 默认口令" "$CONFIG_DEFAULT_PASSWORD"
  check_old_password "旧默认口令 Kamfu@2026" "Kamfu@2026"
  check_old_password "旧默认口令 12345678" "12345678"

  NEW_CODE="$(login_code "$AUTH_USER" "$PASSWORD")"
  case "$NEW_CODE" in
    200) ok "新口令登录成功（200）" ;;
    429) die "新口令测试被临时锁定（429）；等 5 分钟再重试" ;;
    *)   die "新口令登录失败（${NEW_CODE:-无响应}）；请检查 .env、是否重启、是否锁定了来源" ;;
  esac

  if [ -n "$LAN_IP" ]; then
    LAN_STATUS="$(curl -s --max-time 5 "http://$LAN_IP:$PORT/api/auth/status" 2>/dev/null || true)"
    if printf '%s' "$LAN_STATUS" | grep -q '"local":false'; then
      ok "局域网入口可访问: http://$LAN_IP:$PORT（需要登录）"
    else
      warn "局域网入口状态异常: ${LAN_STATUS:-无响应}"
    fi
  fi
fi

echo ""
stat -c '  %a %U:%G %n' "$ENV_FILE" "$PROJECT_DIR/data" "$PROJECT_DIR/data/dashboard.db" "$PROJECT_DIR/data/.ssh_key" 2>/dev/null || true

# ── 10. 总结 ───────────────────────────────────────────────────
step "完成"
cat <<EOF
  本机访问:   http://127.0.0.1:$PORT
  局域网访问: http://${LAN_IP:-<本机IP>}:$PORT
  登录用户:   $AUTH_USER
  配置文件:   $ENV_FILE
  备份文件:   $BACKUP
  日志文件:   $LOG_FILE
  悬浮小屏:   $PALETTE_DESC
EOF
if [ "$GENERATE" -eq 1 ]; then
  echo ""
  echo "  生成的口令: $PASSWORD"
  echo "  请立即保存；脚本退出后不会再次显示。"
fi
echo ""
warn "如果 Docker 仍 permission denied：注销重登，或 newgrp docker。"
warn "如果浏览器登录失败：用无痕窗口，用户名 $AUTH_USER，确认没有自动填充旧密码。"
warn "如果 systemd unit 用了不同的 DASH_ENV_FILE，确认它和脚本改的 $ENV_FILE 是同一个文件。"
