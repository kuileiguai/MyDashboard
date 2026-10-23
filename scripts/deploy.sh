#!/bin/bash
# deploy.sh — Deckpit 统一生命周期入口
#
# 用法：
#   ./scripts/deploy.sh                          # 安装/修复（P0 + P1）
#   ./scripts/deploy.sh upgrade [--no-build]     # 备份、更新依赖/dist、重启
#   ./scripts/deploy.sh backup [--output FILE]   # 备份 env + db + .ssh_key
#   ./scripts/deploy.sh restore <archive>        # 恢复备份并重启
#   ./scripts/deploy.sh uninstall [--purge] [--remove-files]
#   ./scripts/deploy.sh bundle [--output FILE]   # 打离线运行包（dist + wheels）
#   ./scripts/deploy.sh verify                   # 校验 venv 依赖 + dist 资源
#
# 安装常用参数：
#   --user USER        网页登录用户名（P0）
#   --generate         自动生成 24 位口令（P0）
#   --keep-password    复用 .env 里已有明文口令（P0）
#   --min-length N     口令最小长度，默认 6（P0）
#   --lan-cidr CIDR    UFW 放行网段（P0）
#   --ssh-port PORT    UFW 放行 SSH 端口（P0）
#   --no-docker        跳过 Docker 修复（P0）
#   --no-ufw           跳过 UFW（P0）
#   --no-systemd       跳过 P1，保持手动/PID 模式
#   --no-palette       不启动/不自启悬浮小屏
#   --no-linger        不开启 linger（P1）
#   --no-logrotate     不安装 logrotate（P1）
#   --offline          离线安装：用 vendor/wheels，不联网、不跑 npm
#   --host HOST        P0/P1 监听地址
#   --port PORT        P0/P1 端口
#   --yes              跳过确认
#   -h, --help         显示帮助
#
# 卸载语义：
#   默认：停服务、移除 systemd/autostart/logrotate，保留项目、data、.env
#   --purge：额外删除 data/dashboard.db、data/.ssh_key、backend/.env、data/logs
#   --remove-files：额外删除 backend/.venv、frontend/node_modules、frontend/dist
#   不会删除项目源码目录；Docker 组和 UFW 规则默认不自动回滚，会打印手动命令。
#
# 说明：
#   · 安装会先跑 P0，再跑 P1（systemd/自启/历史 1s）；
#   · 需要 backend/.venv 和 frontend/dist；缺失时本脚本会尝试用 uv/npm 补齐；
#   · P1 需要 systemd --user 可用，SSH 无 user bus 时请到桌面终端运行。
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
P0="$PROJECT_DIR/scripts/p0-setup.sh"
P1="$PROJECT_DIR/scripts/p1-setup.sh"
DECKPIT="$PROJECT_DIR/scripts/deckpit.sh"
ENV_FILE="${DASH_ENV_FILE:-$PROJECT_DIR/backend/.env}"
DATA_DIR="$PROJECT_DIR/data"
BACKUP_DIR="$DATA_DIR/backups"
UNIT="$HOME/.config/systemd/user/deckpit.service"
AUTOSTART="$HOME/.config/autostart/deckpit-palette.desktop"

ACTION="install"
case "${1:-}" in
  install|upgrade|backup|restore|uninstall|bundle|verify) ACTION="$1"; shift ;;
  --upgrade) ACTION="upgrade"; shift ;;
  --uninstall) ACTION="uninstall"; shift ;;
  --backup) ACTION="backup"; shift ;;
esac

P0_ARGS=()
P1_ARGS=()
NO_SYSTEMD=0
PALETTE="auto"
NO_PALETTE=0
YES=0
HOST=""
PORT=""
PURGE=0
REMOVE_FILES=0
NO_BUILD=0
OFFLINE=0
BACKUP_OUT=""
BUNDLE_OUT=""
RESTORE_FILE=""
LAST_BACKUP=""
WHEELHOUSE="$PROJECT_DIR/vendor/wheels"

die()  { printf '\n[错误] %s\n' "$*" >&2; exit 1; }
ok()   { printf '  [OK] %s\n' "$*"; }
warn() { printf '  [注意] %s\n' "$*"; }
step() { printf '\n== %s ==\n' "$*"; }

usage() {
  awk 'NR==1{next} /^set -Eeuo/{exit} /^#/{sub(/^# ?/,""); print} /^$/{print}' "$0"
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    --user)
      P0_ARGS+=(--user "${2:-}"); shift 2 ;;
    --generate)
      P0_ARGS+=(--generate); shift ;;
    --keep-password)
      P0_ARGS+=(--keep-password); shift ;;
    --min-length)
      P0_ARGS+=(--min-length "${2:-}"); shift 2 ;;
    --lan-cidr)
      P0_ARGS+=(--lan-cidr "${2:-}"); shift 2 ;;
    --ssh-port)
      P0_ARGS+=(--ssh-port "${2:-}"); shift 2 ;;
    --no-docker)
      P0_ARGS+=(--no-docker); shift ;;
    --no-ufw)
      P0_ARGS+=(--no-ufw); shift ;;
    --no-restart)
      P0_ARGS+=(--no-restart); shift ;;
    --no-systemd)
      NO_SYSTEMD=1; shift ;;
    --palette)
      PALETTE=1; shift ;;
    --no-palette)
      NO_PALETTE=1; PALETTE=0; shift ;;
    --no-linger)
      P1_ARGS+=(--no-linger); shift ;;
    --no-logrotate)
      P1_ARGS+=(--no-logrotate); shift ;;
    --host)
      HOST="${2:-}"; P0_ARGS+=(--host "$HOST"); P1_ARGS+=(--host "$HOST"); shift 2 ;;
    --port)
      PORT="${2:-}"; P0_ARGS+=(--port "$PORT"); P1_ARGS+=(--port "$PORT"); shift 2 ;;
    --yes|-y)
      YES=1; P0_ARGS+=(--yes); P1_ARGS+=(--yes); shift ;;
    --no-build)
      NO_BUILD=1; shift ;;
    --offline)
      OFFLINE=1; shift ;;
    --purge)
      PURGE=1; shift ;;
    --remove-files)
      REMOVE_FILES=1; shift ;;
    --output)
      BACKUP_OUT="${2:-}"; BUNDLE_OUT="${2:-}"; shift 2 ;;
    --file)
      RESTORE_FILE="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    -*)
      die "未知参数: $1（用 --help 查看用法）" ;;
    *)
      if [ "$ACTION" = "restore" ] && [ -z "$RESTORE_FILE" ]; then
        RESTORE_FILE="$1"; shift
      elif [ "$ACTION" = "backup" ] && [ -z "$BACKUP_OUT" ]; then
        BACKUP_OUT="$1"; shift
      elif [ "$ACTION" = "bundle" ] && [ -z "$BUNDLE_OUT" ]; then
        BUNDLE_OUT="$1"; shift
      else
        die "未知参数: $1（用 --help 查看用法）"
      fi
      ;;
  esac
done

[ "$(id -u)" -ne 0 ] || die "请不要用 root 运行；用部署用户运行，脚本内部按需 sudo。"
[ -x "$P0" ] || die "缺少 scripts/p0-setup.sh"
[ -x "$P1" ] || die "缺少 scripts/p1-setup.sh"
[ -x "$DECKPIT" ] || die "缺少 scripts/deckpit.sh"

if [ -z "$PORT" ]; then
  PORT="$(grep -E '^[[:space:]]*(export[[:space:]]+)?DASH_PORT=' "$ENV_FILE" 2>/dev/null | tail -1 | sed -E 's/^[^=]*=//' || true)"
  PORT="${PORT:-8787}"
fi

ensure_runtime() {
  local update_deps="${1:-0}"
  local build_frontend="${2:-auto}"
  local venv="$PROJECT_DIR/backend/.venv"

  if [ "$OFFLINE" -eq 1 ]; then
    [ -d "$WHEELHOUSE" ] || die "离线模式缺少 $WHEELHOUSE；请使用 deploy.sh bundle 生成离线包。"
    if [ ! -x "$venv/bin/python" ]; then
      step "离线创建 backend/.venv"
      command -v python3 >/dev/null 2>&1 || die "缺少 python3，无法创建 venv。"
      python3 -m venv "$venv" || die "创建 venv 失败；确认系统已安装 python3-venv。"
    fi
    if [ "$update_deps" -eq 1 ] || [ ! -x "$venv/bin/uvicorn" ]; then
      step "从 wheelhouse 安装 Python 依赖"
      local pip_args=(--no-index --find-links "$WHEELHOUSE" -r "$PROJECT_DIR/backend/requirements.txt")
      [ "$update_deps" -eq 1 ] && pip_args+=(--upgrade)
      "$venv/bin/python" -m pip install "${pip_args[@]}"
    fi
    if [ ! -f "$PROJECT_DIR/frontend/dist/index.html" ]; then
      die "离线包缺少 frontend/dist；请在联网机器上先执行 npm run build 再 bundle。"
    fi
    return 0
  fi

  if [ ! -x "$venv/bin/python" ]; then
    step "创建 backend/.venv"
    command -v uv >/dev/null 2>&1 || die "缺少 uv；先安装 uv 或手动创建 backend/.venv。"
    (cd "$PROJECT_DIR/backend" && uv venv .venv && uv pip install --no-cache --python .venv/bin/python -r requirements.txt)
  elif [ "$update_deps" -eq 1 ] || [ ! -x "$venv/bin/uvicorn" ]; then
    step "安装/更新 Python 依赖"
    if command -v uv >/dev/null 2>&1; then
      (cd "$PROJECT_DIR/backend" && uv pip install --no-cache --python .venv/bin/python -r requirements.txt)
    else
      (cd "$PROJECT_DIR/backend" && .venv/bin/python -m pip install -r requirements.txt)
    fi
  fi

  if [ "$build_frontend" = "1" ] || { [ "$build_frontend" = "auto" ] && [ ! -f "$PROJECT_DIR/frontend/dist/index.html" ]; }; then
    step "构建前端 dist"
    command -v npm >/dev/null 2>&1 || die "缺少 npm；先安装 Node >= 18，或手动构建 frontend/dist。"
    local npm_cache="$PROJECT_DIR/.npm-cache"
    mkdir -p "$npm_cache/_logs"
    chmod 700 "$npm_cache"
    (
      cd "$PROJECT_DIR/frontend"
      export npm_config_cache="$npm_cache"
      export npm_config_logs_dir="$npm_cache/_logs"
      if [ -f package-lock.json ]; then npm ci; else npm install; fi
      npm run build
    )
  fi
}

verify_runtime() {
  local venv="$PROJECT_DIR/backend/.venv"

  step "校验 Python 运行环境"
  [ -x "$venv/bin/python" ] || die "缺少 $venv/bin/python"
  "$venv/bin/python" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(f"Python 版本过低: {sys.version.split()[0]}，需要 >= 3.10")
mods = ["fastapi", "uvicorn", "websockets", "psutil", "aiosqlite", "pynvml", "httpx", "multipart"]
missing = []
for name in mods:
    try:
        __import__(name)
    except Exception as exc:
        missing.append(f"{name}: {exc}")
if missing:
    raise SystemExit("缺少 Python 依赖:\n  " + "\n  ".join(missing))
print(f"  [OK] Python {sys.version.split()[0]}，核心依赖齐全")
PY

  step "校验前端 dist"
  local dist="$PROJECT_DIR/frontend/dist"
  [ -f "$dist/index.html" ] || die "缺少 $dist/index.html"
  "$venv/bin/python" - "$dist" <<'PY'
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
html = (root / "index.html").read_text(encoding="utf-8")
refs = re.findall(r'(?:src|href)="(/[^"]+)"', html)
missing = [r for r in refs if not (root / r.lstrip("/")).is_file()]
if missing:
    raise SystemExit("dist 缺少资源:\n  " + "\n  ".join(missing))
print(f"  [OK] dist/index.html，引用资源 {len(refs)} 个都存在")
PY
}

do_backup() {
  [ -f "$ENV_FILE" ] || die "配置文件不存在，无法备份: $ENV_FILE"
  mkdir -p "$BACKUP_DIR"
  chmod 700 "$BACKUP_DIR"

  local dest="$BACKUP_OUT"
  if [ -z "$dest" ]; then
    dest="$BACKUP_DIR/deckpit-$(date +%Y%m%d-%H%M%S).tar.gz"
  fi
  case "$dest" in
    /*) ;;
    *) dest="$PROJECT_DIR/$dest" ;;
  esac

  local tmp
  tmp="$(mktemp -d)"
  cp -p "$ENV_FILE" "$tmp/env"
  [ -f "$DATA_DIR/dashboard.db" ] && cp -p "$DATA_DIR/dashboard.db" "$tmp/dashboard.db"
  [ -f "$DATA_DIR/.ssh_key" ] && cp -p "$DATA_DIR/.ssh_key" "$tmp/.ssh_key"
  {
    echo "created=$(date -Iseconds)"
    echo "project=$PROJECT_DIR"
    echo "version=$(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  } > "$tmp/manifest.txt"

  tar -czf "$dest" -C "$tmp" .
  chmod 600 "$dest"
  rm -rf "$tmp"
  LAST_BACKUP="$dest"
  ok "备份: $LAST_BACKUP"
}

do_verify() {
  verify_runtime
  step "运行状态"
  "$DECKPIT" status || true
}

do_bundle() {
  [ "$OFFLINE" -eq 0 ] || die "bundle 不能和 --offline 同时用；bundle 需要在联网机器上生成。"
  ensure_runtime 1 1
  verify_runtime

  step "准备离线运行包"
  local tmp
  tmp="$(mktemp -d)"
  local bundle="$tmp/deckpit"
  mkdir -p "$bundle/backend" "$bundle/frontend" "$bundle/scripts" "$bundle/vendor/wheels"

  tar -cf "$tmp/source.tar" \
    -C "$PROJECT_DIR" \
    --exclude='backend/.venv' \
    --exclude='backend/.env' \
    --exclude='backend/.env.bak.*' \
    --exclude='backend/__pycache__' \
    --exclude='backend/.pytest_cache' \
    --exclude='frontend/node_modules' \
    --exclude='frontend/src' \
    --exclude='scripts/__pycache__' \
    --exclude='scripts/dev.sh' \
    --exclude='scripts/check-env.sh' \
    --exclude='data' \
    backend frontend/dist scripts
  tar -xf "$tmp/source.tar" -C "$bundle"
  rm -f "$tmp/source.tar"

  for f in README.md DEPLOY-FULL-CHECKLIST.md; do
    [ -f "$PROJECT_DIR/$f" ] && cp -p "$PROJECT_DIR/$f" "$bundle/"
  done
  [ -f "$PROJECT_DIR/backend/.env.example" ] && cp -p "$PROJECT_DIR/backend/.env.example" "$bundle/backend/"

  step "下载 Python wheels"
  "$PROJECT_DIR/backend/.venv/bin/python" -m pip download \
    -r "$PROJECT_DIR/backend/requirements.txt" \
    -d "$bundle/vendor/wheels"

  cat > "$bundle/OFFLINE-README.md" <<'EOF'
# Deckpit 离线包

## 目标机器需要预装

- Python >= 3.10（含 venv/ensurepip）
- 系统命令：iproute2、curl、util-linux、tmux、wmctrl、xdotool、x11-utils、ffmpeg、sshpass、ufw、policykit-1、mesa-utils
- 悬浮小屏额外需要：python3-gi、python3-gi-cairo、gir1.2-gtk-3.0、gir1.2-webkit2-4.0（24.04 用 4.1）

系统包不在 wheelhouse 里，需要目标机器提前装好；本包只保证 Python 依赖和前端 dist 不需要联网。

## 安装

```bash
tar xzf deckpit-offline-*.tar.gz
cd deckpit
./scripts/deploy.sh --offline
```

`--offline` 会：

- 用 `vendor/wheels` 创建 `backend/.venv` 并安装依赖（`pip --no-index`）
- 直接使用包内 `frontend/dist`，不运行 npm
- 继续执行 P0/P1（口令、权限、Docker、UFW、systemd）

## 注意

- wheelhouse 与构建机器的 OS/Python 小版本绑定；目标机器最好同为 Ubuntu x86_64 + 相同 Python 版本。
- 包内不含 `backend/.env`、`data/dashboard.db`、`data/.ssh_key`；这些需要在目标机器重新生成/配置。
- `frontend/dist` 是已构建产物，不需要目标机器安装 Node。
EOF

  local dest="${BUNDLE_OUT:-$PROJECT_DIR/release/deckpit-offline-$(date +%Y%m%d-%H%M%S).tar.gz}"
  case "$dest" in
    /*) ;;
    *) dest="$PROJECT_DIR/$dest" ;;
  esac
  mkdir -p "$(dirname "$dest")"
  tar -czf "$dest" -C "$tmp" deckpit
  chmod 600 "$dest"
  rm -rf "$tmp"
  ok "离线包: $dest"
  echo "  目标机器解压后执行: ./scripts/deploy.sh --offline"
}

do_restore() {
  [ -n "$RESTORE_FILE" ] || die "用法: ./scripts/deploy.sh restore <archive>"
  [ -f "$RESTORE_FILE" ] || die "备份不存在: $RESTORE_FILE"
  tar -tzf "$RESTORE_FILE" >/dev/null 2>&1 || die "不是有效的 tar.gz: $RESTORE_FILE"

  step "恢复前备份当前数据"
  BACKUP_OUT=""
  do_backup || warn "当前数据备份失败，继续恢复"

  step "停止服务"
  "$DECKPIT" stop || true

  step "解包并恢复"
  local tmp
  tmp="$(mktemp -d)"
  tar -xzf "$RESTORE_FILE" -C "$tmp"
  [ -f "$tmp/env" ] || { rm -rf "$tmp"; die "备份里缺少 env"; }
  cp -p "$tmp/env" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  [ -f "$tmp/dashboard.db" ] && cp -p "$tmp/dashboard.db" "$DATA_DIR/dashboard.db"
  [ -f "$tmp/.ssh_key" ] && cp -p "$tmp/.ssh_key" "$DATA_DIR/.ssh_key"
  chmod 600 "$DATA_DIR/dashboard.db" "$DATA_DIR/.ssh_key" 2>/dev/null || true
  rm -rf "$tmp"
  ok "已恢复配置和数据"

  step "启动"
  "$DECKPIT" start --no-palette || die "启动失败，检查日志"
  "$DECKPIT" status || true
}

do_upgrade() {
  [ -f "$ENV_FILE" ] || die "配置文件不存在: $ENV_FILE"

  step "升级前备份"
  BACKUP_OUT=""
  do_backup

  if [ "$NO_BUILD" -eq 1 ]; then
    [ -f "$PROJECT_DIR/frontend/dist/index.html" ] || die "--no-build 但 frontend/dist 不存在"
    ensure_runtime 1 0
    warn "--no-build：跳过前端构建，dist 使用现有产物"
  else
    ensure_runtime 1 1
  fi
  verify_runtime

  step "重启后端"
  local palette_arg="--no-palette"
  if [ "$PALETTE" = "1" ]; then
    palette_arg="--palette"
  elif [ "$PALETTE" = "auto" ] && [ -n "${DISPLAY:-}" ] && [ "$NO_PALETTE" -eq 0 ]; then
    palette_arg=""
  fi
  # shellcheck disable=SC2086
  "$DECKPIT" restart $palette_arg || die "重启失败"

  step "验收"
  if "$DECKPIT" status; then
    ok "升级完成"
  else
    warn "升级后健康检查失败；可恢复备份: $LAST_BACKUP"
    warn "  ./scripts/deploy.sh restore $LAST_BACKUP"
    exit 1
  fi
}

do_uninstall() {
  step "卸载 Deckpit 系统集成"
  if [ "$PURGE" -eq 1 ] && [ "$YES" -ne 1 ]; then
    read -rp "将删除 data/dashboard.db、data/.ssh_key、backend/.env、data/logs，确认? [y/N]: " ans
    case "$ans" in [Yy]*) ;; *) die "已取消。" ;; esac
  fi

  "$DECKPIT" stop || true

  if systemctl --user cat deckpit >/dev/null 2>&1; then
    systemctl --user disable --now deckpit.service 2>/dev/null || true
  fi
  rm -f "$UNIT" "$HOME/.config/systemd/user/default.target.wants/deckpit.service"
  systemctl --user daemon-reload 2>/dev/null || true
  ok "已移除 systemd unit"

  rm -f "$AUTOSTART"
  ok "已移除桌面自启"

  if [ -f /etc/logrotate.d/deckpit ]; then
    if sudo -n rm -f /etc/logrotate.d/deckpit 2>/dev/null; then
      ok "已移除 /etc/logrotate.d/deckpit"
    else
      warn "需要 sudo 删除 /etc/logrotate.d/deckpit；手动执行: sudo rm -f /etc/logrotate.d/deckpit"
    fi
  fi

  if [ "$PURGE" -eq 1 ]; then
    rm -f "$DATA_DIR/dashboard.db" "$DATA_DIR/.ssh_key" "$ENV_FILE"
    rm -rf "$DATA_DIR/logs"
    ok "已删除数据、.ssh_key、backend/.env、logs"
  else
    ok "已保留 data/、backend/.env"
  fi

  if [ "$REMOVE_FILES" -eq 1 ]; then
    rm -rf "$PROJECT_DIR/backend/.venv" "$PROJECT_DIR/frontend/node_modules" "$PROJECT_DIR/frontend/dist"
    ok "已删除 .venv / node_modules / dist"
  fi

  step "未自动回滚的系统项"
  cat <<EOF
  · Docker 组/socket：$(getent group docker 2>/dev/null || echo 'docker 组不存在')
    如需回滚，手动处理 /var/run/docker.sock 和 docker 组成员。
  · UFW 8787 规则：
    sudo ufw delete allow from <你的网段> to any port $PORT proto tcp
  · linger（如果开过）：
    sudo loginctl disable-linger $USER
  · 项目源码目录：$PROJECT_DIR（未删除）
EOF
}

do_install() {
  ensure_runtime 0 auto
  verify_runtime

  if [ ! -f "$ENV_FILE" ]; then
    step "初始化配置文件"
    [ -f "$PROJECT_DIR/backend/.env.example" ] || die "缺少 backend/.env.example，无法初始化 .env"
    cp -p "$PROJECT_DIR/backend/.env.example" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    ok "已从 .env.example 生成 $ENV_FILE"
  fi

  if [ "$NO_SYSTEMD" -eq 0 ]; then
    if ! systemctl --user show-environment >/dev/null 2>&1; then
      die "P1 需要 systemd --user；当前不可用。请到桌面终端运行，或加 --no-systemd 只做 P0。"
    fi
  fi

  if [ "$NO_SYSTEMD" -eq 0 ]; then
    P0_ARGS+=(--no-palette)
    if [ "$NO_PALETTE" -eq 1 ]; then
      P1_ARGS+=(--no-palette)
    fi
  else
    if [ "$PALETTE" = "1" ]; then
      P0_ARGS+=(--palette)
    elif [ "$NO_PALETTE" -eq 1 ]; then
      P0_ARGS+=(--no-palette)
    fi
  fi

  step "阶段 1/2：P0 安全加固"
  "$P0" "${P0_ARGS[@]}"
  ok "P0 完成"

  if [ "$NO_SYSTEMD" -eq 1 ]; then
    step "完成（已跳过 P1）"
    cat <<EOF
  P0 已完成，当前仍是手动/PID 模式。
  启动: ./scripts/deckpit.sh start
  状态: ./scripts/deckpit.sh status
  以后要装 systemd: ./scripts/p1-setup.sh
EOF
    return 0
  fi

  step "阶段 2/2：P1 systemd / 自启 / 历史 1s"
  if ! "$P1" "${P1_ARGS[@]}"; then
    echo ""
    warn "P1 失败。可先手动回退启动："
    warn "  ./scripts/deckpit.sh start"
    warn "查看日志："
    warn "  tail -80 $PROJECT_DIR/data/logs/deckpit.log"
    exit 1
  fi
  ok "P1 完成"

  step "验收"
  set +e
  "$DECKPIT" status
  STATUS_RC=$?
  set -e
  echo ""
  if [ "$STATUS_RC" -eq 0 ]; then
    ok "deckpit 运行正常"
  else
    warn "deckpit status 返回 $STATUS_RC（0 运行 / 3 停止 / 4 异常）"
  fi

  step "完成"
  cat <<EOF
  本机:   http://127.0.0.1:$PORT
  管理:   ./scripts/deckpit.sh status|restart|logs -f|doctor
  小屏:   ./scripts/deckpit.sh palette start|stop|status
EOF
}

case "$ACTION" in
  install) do_install ;;
  upgrade) do_upgrade ;;
  backup) do_backup ;;
  restore) do_restore ;;
  uninstall) do_uninstall ;;
  bundle) do_bundle ;;
  verify) do_verify ;;
  *) die "未知动作: $ACTION" ;;
esac
