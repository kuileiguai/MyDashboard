#!/bin/bash
# check-env.sh — 新机器部署前依赖预检
#
# 用法：
#   ./scripts/check-env.sh            # 只检查，输出 PASS/WARN/FAIL 和安装建议
#   ./scripts/check-env.sh --fix      # 检查后自动补齐无交互依赖（uv venv/npm/dist）
#
# 说明：
#   · 核心依赖：backend/.venv + frontend/dist（生产运行必需）
#   · 环境管理优先使用 uv（uv venv + uv pip）；不主动用系统 python3 建 venv
#   · 若 backend/.venv 缺失，提示用户用 uv 创建，不再自动代劳
#   · 可选依赖：按功能分组，缺失只给 WARN，不影响主服务
#   · apt 安装需要 sudo，脚本不自动执行，只打印建议命令
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/backend/.venv"
VENV_PY="$VENV_DIR/bin/python"
DIST_HTML="$PROJECT_DIR/frontend/dist/index.html"

FIX=0
[ "${1:-}" = "--fix" ] && FIX=1

# ── 输出样式 ──
if [ -t 1 ]; then
  C_RED=$'\033[31m'; C_YEL=$'\033[33m'; C_GRN=$'\033[32m'; C_BLU=$'\033[36m'; C_OFF=$'\033[0m'
else
  C_RED=""; C_YEL=""; C_GRN=""; C_BLU=""; C_OFF=""
fi
PASS_N=0; WARN_N=0; FAIL_N=0

log()  { printf '%s\n' "$*"; }
ok()   { PASS_N=$((PASS_N+1)); printf '  %s[PASS]%s %s\n' "$C_GRN" "$C_OFF" "$*"; }
warn() { WARN_N=$((WARN_N+1)); printf '  %s[WARN]%s %s\n' "$C_YEL" "$C_OFF" "$*"; }
fail() { FAIL_N=$((FAIL_N+1)); printf '  %s[FAIL]%s %s\n' "$C_RED" "$C_OFF" "$*"; }
hdr()  { printf '\n%s== %s ==%s\n' "$C_BLU" "$*" "$C_OFF"; }
tip()  { printf '       %s提示:%s %s\n' "$C_YEL" "$C_OFF" "$*"; }

# ── 系统基本信息 ──
hdr "系统信息"
os_name=$( (grep -E '^(NAME|VERSION)=' /etc/os-release 2>/dev/null | tr '\n' ' ' ) || echo "未知")
log "  OS: $os_name"
arch=$(uname -m)
log "  ARCH: $arch"
[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && session="有图形会话" || session="无图形会话（headless）"
log "  图形: $session (DISPLAY=${DISPLAY:-无} WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-无})"

# ── 1. Python 环境（uv 优先） ──
hdr "1. Python 环境（核心必需，uv 管理）"
if command -v uv >/dev/null 2>&1; then
  uv_ver=$(uv --version 2>/dev/null | awk '{print $2}')
  ok "uv $uv_ver（本机 Python 环境管理工具）"
else
  fail "未找到 uv（本项目要求用 uv 管理 Python 环境）"
  tip "安装 uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

hdr "1.1 backend 虚拟环境（backend/.venv，核心必需）"
if [ -x "$VENV_PY" ]; then
  py_ver=$("$VENV_PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
  if "$VENV_PY" -c 'import sys; exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    ok "backend/.venv 存在，Python $py_ver（后端要求 >=3.10）"
  else
    fail "backend/.venv 内 Python 版本过低: $py_ver（需 >=3.10，推荐 3.11+）"
    tip "重建: uv venv --python 3.11 backend/.venv && uv pip install --python backend/.venv/bin/python -r backend/requirements.txt"
  fi
else
  fail "backend/.venv 不存在"
  tip "请用 uv 创建: cd backend && uv venv .venv && uv pip install -r requirements.txt"
  tip "（或用 ./scripts/check-env.sh --fix 让脚本用 uv 自动创建）"
fi

hdr "1.2 backend Python 依赖（核心必需）"
if [ -x "$VENV_PY" ]; then
  missing=""
  for m in fastapi uvicorn websockets psutil aiosqlite pynvml python_multipart; do
    "$VENV_PY" -c "import $m" 2>/dev/null || missing="$missing $m"
  done
  if [ -z "$missing" ]; then
    ok "venv 内核心依赖齐全（fastapi/uvicorn/websockets/psutil/aiosqlite/pynvml/multipart）"
  else
    fail "venv 内缺失依赖:$missing"
    tip "cd backend && uv pip install -r requirements.txt"
  fi
else
  fail "venv 不存在，无法检查依赖（先解决 1.1 节）"
fi

# ── 2. 前端产物 ──
hdr "2. 前端 dist（生产运行必需）"
if [ -f "$DIST_HTML" ]; then
  ok "frontend/dist/index.html 已存在（可直接生产运行，无需 Node）"
  node_need=0
else
  fail "frontend/dist 缺失，无法生产运行"
  node_need=1
  tip "有 Node 的机器上执行: cd frontend && npm install && npm run build"
  tip "或本机 Node>=18 时运行 ./scripts/check-env.sh --fix 自动构建"
fi

if [ "$node_need" = "1" ] || [ "${CHECK_NODE:-1}" = "1" ]; then
  if command -v node >/dev/null 2>&1; then
    nv=$(node -v 2>/dev/null | sed 's/^v//')
    major=${nv%%.*}
    if [ "${major:-0}" -ge 18 ]; then
      ok "node $nv（>=18，可构建前端）"
    else
      warn "node $nv 过旧（Vite 5 需 >=18）"
      tip "推荐 nvm: curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash"
    fi
  else
    if [ "$node_need" = "1" ]; then
      fail "未找到 node（当前需要构建前端）"
      tip "推荐 nvm: curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash"
    else
      ok "未安装 node（dist 已存在，运行无需 Node）"
    fi
  fi
fi

# ── 3. 外部系统命令 ──
hdr "3. 外部命令"
# 核心：后端监控/端口模块必须
for cmd in ss curl; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "命令 $cmd"
  else
    fail "命令 $cmd 缺失（后端系统监控/端口模块需要）"
    [ "$cmd" = "ss" ] && tip "Ubuntu: sudo apt install -y iproute2"
    [ "$cmd" = "curl" ] && tip "Ubuntu: sudo apt install -y curl"
  fi
done
# 可选：外部终端控制 / 悬浮窗定位
for cmd in xdotool wmctrl xprop; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "命令 $cmd（外部终端控制）"
  else
    warn "命令 $cmd 缺失（外部终端控制/悬浮窗定位将不可用）"
    tip "Ubuntu: sudo apt install -y xdotool wmctrl x11-utils"
  fi
done
# 可选：悬浮窗 GL 探测
if command -v glxinfo >/dev/null 2>&1; then
  ok "命令 glxinfo（悬浮窗 GPU 探测）"
else
  warn "命令 glxinfo 缺失（悬浮窗将回退软件渲染）"
  tip "Ubuntu: sudo apt install -y mesa-utils"
fi
# 可选：Docker 模块
if command -v docker >/dev/null 2>&1; then
  ok "命令 docker（Docker 模块）"
else
  warn "命令 docker 缺失（Docker 模块不可用，不影响其他功能）"
  tip "见 https://docs.docker.com/engine/install/ubuntu/"
fi
# 可选：GPU 监控
if command -v nvidia-smi >/dev/null 2>&1; then
  ok "命令 nvidia-smi（GPU 监控）"
else
  warn "命令 nvidia-smi 缺失（无 NVIDIA 卡时属正常）"
fi
# 可选：终端/文件工具
for cmd in tmux lsblk; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "命令 $cmd"
  else
    warn "命令 $cmd 缺失（对应功能不可用）"
    [ "$cmd" = "tmux" ] && tip "Ubuntu: sudo apt install -y tmux"
    [ "$cmd" = "lsblk" ] && tip "Ubuntu: sudo apt install -y util-linux"
  fi
done

# ── 4. 端口 ──
hdr "4. 端口 8787"
if command -v ss >/dev/null 2>&1; then
  if ss -tln 2>/dev/null | grep -q ":8787 "; then
    fail "端口 8787 已被占用"
    ss -tlnp 2>/dev/null | grep ":8787 " >&2
  else
    ok "端口 8787 空闲"
  fi
else
  warn "无 ss，跳过端口检查（请确认 8787 未被占用）"
fi

# ── 5. 悬浮小屏 quickpalette（可选） ──
hdr "5. 悬浮小屏 quickpalette（可选，DASH_PALETTE=1 时需要）"
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  ok "检测到图形会话"
else
  warn "无图形会话：quickpalette 无法显示窗口，请在有桌面的机器上运行"
fi
if [ -x "$VENV_PY" ]; then
  if "$VENV_PY" -c "import webview" 2>/dev/null; then
    ok "venv 内 pywebview 已安装"
  else
    fail "venv 内缺少 pywebview"
    tip "./scripts/check-env.sh --fix 可自动安装"
  fi
  if "$VENV_PY" -c "import gi" 2>/dev/null || "$VENV_PY" -c "import qtpy, PyQt5" 2>/dev/null; then
    ok "pywebview 的 GUI 后端可用（GTK 或 Qt）"
  else
    fail "缺少 GUI 后端：gtk(gi) 与 qt 均不可用"
    tip "方案A(Qt): cd backend && uv pip install --python .venv/bin/python \"pywebview[qt]\""
    tip "方案B(GTK): sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.0（24.04 用 -4.1）后重建 venv: cd backend && uv venv --system-site-packages .venv && uv pip install -r requirements.txt"
  fi
  for m in pynput pystray PIL; do
    if "$VENV_PY" -c "import $m" 2>/dev/null; then
      ok "可选依赖 $m（快捷键/托盘）"
    else
      warn "可选依赖 $m 缺失（全局快捷键/托盘降级，不影响悬浮窗）"
      tip "cd backend && uv pip install --python .venv/bin/python pynput pystray Pillow"
    fi
  done
else
  warn "venv 不存在，跳过 quickpalette 检查（先解决第 1.1 节）"
fi

# ── 6. --fix 自动修复 ──
if [ "$FIX" = "1" ]; then
  hdr "6. --fix 自动修复"
  # 6.1 venv + 后端依赖（uv）
  if [ ! -x "$VENV_PY" ]; then
    echo ">>> 用 uv 创建 backend/.venv ..."
    if (cd "$PROJECT_DIR/backend" && uv venv .venv); then
      echo ">>> 用 uv 安装后端依赖 ..."
      (cd "$PROJECT_DIR/backend" && uv pip install --python .venv/bin/python -r requirements.txt) && echo "OK: 后端依赖安装完成"
    else
      echo "错误: uv venv 创建失败（请先安装 uv: curl -LsSf https://astral.sh/uv/install.sh | sh）" >&2
    fi
  elif ! "$VENV_PY" -c "import fastapi, uvicorn" 2>/dev/null; then
    echo ">>> 用 uv 补齐后端依赖 ..."
    (cd "$PROJECT_DIR/backend" && uv pip install --python .venv/bin/python -r requirements.txt) && echo "OK: 后端依赖安装完成"
  fi
  # 6.2 前端 dist
  if [ ! -f "$DIST_HTML" ]; then
    if command -v node >/dev/null 2>&1 && [ "$(node -v 2>/dev/null | sed 's/^v//;s/\..*//')" -ge 18 ] 2>/dev/null; then
      echo ">>> 构建前端 ..."
      (cd "$PROJECT_DIR/frontend" && npm install && npm run build) && echo "OK: 前端构建完成"
    else
      echo "错误: 需要 Node>=18 才能构建前端，请先安装（或用其他机器打包后复制 dist）" >&2
    fi
  fi
  # 6.3 quickpalette 可选 Python 依赖（非 GUI 后端部分）
  if [ -x "$VENV_PY" ]; then
    if ! "$VENV_PY" -c "import webview, pynput, pystray, PIL" 2>/dev/null; then
      echo ">>> 安装 quickpalette 可选依赖（pywebview/pynput/pystray/Pillow）..."
      (cd "$PROJECT_DIR/backend" && uv pip install --python .venv/bin/python pywebview pynput pystray Pillow) && echo "OK: quickpalette 依赖安装完成"
    fi
  fi
  hdr "修复完成，请重新运行本脚本确认"
else
  hdr "安装建议（汇总）"
  log "  核心（必装）:"
  log "    1) 安装 uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
  log "    2) 创建环境: cd backend && uv venv .venv && uv pip install -r requirements.txt"
  log "    3) 系统命令: sudo apt install -y iproute2 curl"
  log "  悬浮窗 GUI 后端（二选一）:"
  log "    A. Qt:  cd backend && uv pip install --python .venv/bin/python \"pywebview[qt]\""
  log "    B. GTK(Ubuntu 22.04): sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.0"
  log "                    (24.04): sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1"
  log "    GTK 方案需重建 venv: cd backend && uv venv --system-site-packages .venv && uv pip install -r requirements.txt"
  log "  悬浮窗/终端控制（可选）:"
  log "    sudo apt install -y xdotool wmctrl x11-utils mesa-utils"
  log "    cd backend && uv pip install --python .venv/bin/python pynput pystray Pillow"
  log "  其余可选: docker / tmux / nvidia 驱动"
  log ""
  log "  自动补齐（无 sudo 部分）: ./scripts/check-env.sh --fix"
fi

# ── 汇总 ──
printf '\n%s════════ 汇总 ════════%s\n' "$C_BLU" "$C_OFF"
printf '  PASS %d | WARN %d | FAIL %d\n' "$PASS_N" "$WARN_N" "$FAIL_N"
if [ "$FAIL_N" -gt 0 ]; then
  printf '  结果: %s有 FAIL，请先处理后再启动服务%s\n' "$C_RED" "$C_OFF"
  exit 1
elif [ "$WARN_N" -gt 0 ]; then
  printf '  结果: %s有 WARN（可选功能降级，主服务可启动）%s\n' "$C_YEL" "$C_OFF"
  exit 0
else
  printf '  结果: %s全部通过，可直接启动%s\n' "$C_GRN" "$C_OFF"
  exit 0
fi
