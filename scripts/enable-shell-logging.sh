#!/bin/bash
# enable-shell-logging.sh — 开启终端输出记录（文本镜像的数据源）
#
# 原理：在 shell 启动配置里加一段守卫代码，让每个**交互式 shell** 套一层
#       `script -q -f`，把该终端看到的全部输出实时落到 ~/.deckpit/logs。
#       面板读日志交给 xterm.js 渲染 —— 得到的是真正的文本（可复制、可回滚）。
#
# 为什么需要它：已存在的终端输出流无法事后读取（pty 消费者唯一），
#       所以只能"事前记录"。开发人员照常新建终端即可，无需改变习惯。
#
# 用法：
#   ./scripts/enable-shell-logging.sh              # 安装（自动备份原配置）
#   ./scripts/enable-shell-logging.sh --uninstall  # 卸载（同时备份）
#   ./scripts/enable-shell-logging.sh --status     # 查看状态
#
# 生效条件：重新打开终端（当前已开着的终端不会被记录）。
# 临时跳过单个终端：DECKPIT_TERM_LOG_OFF=1 打开终端，或终端里 export 后再 exec $SHELL。
set -u

MARK_BEGIN='# >>> Deckpit 终端输出记录 (deckpit-term-log) >>>'
MARK_END='# <<< Deckpit 终端输出记录 (deckpit-term-log) <<<'
LOG_DIR="$HOME/.deckpit/logs"

if [ -t 1 ]; then
  C_GRN=$'\033[32m'; C_YEL=$'\033[33m'; C_RED=$'\033[31m'; C_BLD=$'\033[1m'; C_OFF=$'\033[0m'
else
  C_GRN=""; C_YEL=""; C_RED=""; C_BLD=""; C_OFF=""
fi

ok()   { printf '  %s✓%s %s\n' "$C_GRN" "$C_OFF" "$*"; }
warn() { printf '  %s!%s %s\n' "$C_YEL" "$C_OFF" "$*"; }
err()  { printf '  %s✗%s %s\n' "$C_RED" "$C_OFF" "$*"; }

# 需要写入的启动配置文件：按当前 shell 自动识别
detect_rc() {
  case "$(basename "${SHELL:-}")" in
    bash) printf '%s' "$HOME/.bashrc" ;;
    zsh)  printf '%s' "$HOME/.zshrc" ;;
    *)
      if   [ -f "$HOME/.bashrc" ]; then printf '%s' "$HOME/.bashrc"
      elif [ -f "$HOME/.zshrc" ];  then printf '%s' "$HOME/.zshrc"
      else printf '%s' "$HOME/.profile"; fi
      ;;
  esac
}

RC_FILE="$(detect_rc)"

read -r -d '' SNIPPET <<'EOF' || true
# >>> Deckpit 终端输出记录 (deckpit-term-log) >>>
# 把交互式 shell 的输出实时记录到 ~/.deckpit/logs，
# 面板据此以文本形式只读回放终端内容（可复制、可回滚，不是截图）。
# 卸载: ./scripts/enable-shell-logging.sh --uninstall
if [ -z "$DECKPIT_TERM_LOG" ] && [ -t 1 ] && [ -z "$DECKPIT_TERM_LOG_OFF" ] && command -v script >/dev/null 2>&1; then
  export DECKPIT_TERM_LOG=1
  mkdir -p "$HOME/.deckpit/logs"
  DECKPIT_LOG_FILE="$HOME/.deckpit/logs/term-$(date +%Y%m%d-%H%M%S)-$$.log"
  export DECKPIT_LOG_FILE
  exec script -q -f "$DECKPIT_LOG_FILE" "${SHELL:-/bin/bash}"
fi
if [ -n "$DECKPIT_LOG_FILE" ] && [ ! -f "${DECKPIT_LOG_FILE%.log}.meta.json" ]; then
  _dp_cwd="$(printf '%s' "$PWD" | sed 's/\\/\\\\/g; s/"/\\"/g')"
  ( umask 077
    printf '{"pid":%s,"cwd":"%s","started":"%s","shell":"%s"}\n' \
      "$$" "$_dp_cwd" "$(date -Iseconds)" "${SHELL:-$0}" \
      > "${DECKPIT_LOG_FILE%.log}.meta.json" )
  unset _dp_cwd
fi
# <<< Deckpit 终端输出记录 (deckpit-term-log) <<<
EOF

backup() {
  local src="$1" dst
  dst="$src.deckpit-backup-$(date +%Y%m%d-%H%M%S)"
  cp -p "$src" "$dst" && ok "已备份 $src -> $dst"
}

do_install() {
  printf '%s终端输出记录安装%s\n' "$C_BLD" "$C_OFF"
  echo "  目标配置: $RC_FILE"
  echo "  日志目录: $LOG_DIR"

  if ! command -v script >/dev/null 2>&1; then
    err "缺少 script 命令（util-linux），请先安装: sudo apt install -y util-linux"
    exit 1
  fi

  mkdir -p "$LOG_DIR"
  chmod 700 "$LOG_DIR"
  ok "日志目录已就绪（权限 700）"

  [ -f "$RC_FILE" ] || { touch "$RC_FILE"; warn "$RC_FILE 不存在，已创建"; }

  if grep -Fq "$MARK_BEGIN" "$RC_FILE"; then
    warn "$RC_FILE 中已存在记录钩子，跳过（如需重装请先 --uninstall）"
  else
    backup "$RC_FILE"
    printf '\n%s\n' "$SNIPPET" >> "$RC_FILE"
    ok "已写入记录钩子"
  fi

  echo ""
  printf '  %s生效方式:%s 重新打开一个终端窗口（当前已开着的终端不会被记录）\n' "$C_BLD" "$C_OFF"
  echo "  验证: 新开终端执行 echo hello，然后 ./scripts/enable-shell-logging.sh --status 应能看到日志"
  echo ""
  warn "注意: 终端里输入的密码、token 也会进日志（文件权限 600，仅本人可读）"
  warn "      日志会持续增长，可定期清理: rm ~/.deckpit/logs/term-*.log*"
}

do_uninstall() {
  printf '%s终端输出记录卸载%s\n' "$C_BLD" "$C_OFF"
  if [ ! -f "$RC_FILE" ]; then
    warn "$RC_FILE 不存在，无需卸载"; return
  fi
  if ! grep -Fq "$MARK_BEGIN" "$RC_FILE"; then
    warn "$RC_FILE 中没有记录钩子，无需卸载"; return
  fi
  backup "$RC_FILE"
  sed -i "/$(printf '%s' "$MARK_BEGIN" | sed 's/[]\/$*.^[]/\\&/g')/,/$(printf '%s' "$MARK_END" | sed 's/[]\/$*.^[]/\\&/g')/d" "$RC_FILE"
  ok "已从 $RC_FILE 移除记录钩子"
  echo ""
  echo "  已记录的日志保留在 $LOG_DIR，如需清空:"
  echo "    rm -f ~/.deckpit/logs/term-*.log ~/.deckpit/logs/term-*.meta.json"
  echo "  重新打开终端后不再记录。"
}

do_status() {
  printf '%s终端输出记录状态%s\n' "$C_BLD" "$C_OFF"
  if [ -f "$RC_FILE" ] && grep -Fq "$MARK_BEGIN" "$RC_FILE"; then
    ok "钩子已安装: $RC_FILE"
  else
    err "钩子未安装: $RC_FILE（运行本脚本不带参数即可安装）"
  fi
  echo "  当前 shell: ${SHELL:-未知}"
  echo "  script 命令: $(command -v script || echo 缺失)"
  echo "  日志目录: $LOG_DIR"
  if [ -d "$LOG_DIR" ]; then
    n=$(find "$LOG_DIR" -maxdepth 1 -name 'term-*.log' 2>/dev/null | wc -l)
    echo "  已记录会话: $n"
    find "$LOG_DIR" -maxdepth 1 -name 'term-*.log' -printf '    %f  (%s 字节)\n' 2>/dev/null | head -10
  else
    warn "日志目录不存在（尚未产生记录）"
  fi
}

case "${1:-}" in
  --uninstall|-u) do_uninstall ;;
  --status|-s)    do_status ;;
  "")             do_install ;;
  *)
    echo "用法: $0 [--uninstall | --status]"
    exit 1
    ;;
esac
