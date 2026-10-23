#!/bin/bash
# fix-docker-perms.sh — 把 Docker socket 恢复为标准 root:docker 660，
# 并把指定普通用户加入 docker 组（Docker 免 sudo）。
#
# 用法：
#   sudo ./scripts/fix-docker-perms.sh [用户名]
#   sudo ./scripts/fix-docker-perms.sh kamfu
#
# 说明：
#   · 默认使用 SUDO_USER；直接以 root 登录时必须显式传用户名。
#   · 只改 socket 属主/权限和用户组，不重启 Docker、不改 daemon.json。
#   · docker 组等价于 root（可挂载宿主机根目录），只给可信用户。
#   · 组变更对“新登录会话”生效；执行完需要注销重登，或 newgrp docker。
set -euo pipefail

TARGET_USER="${1:-${SUDO_USER:-}}"
SOCKET="/var/run/docker.sock"

if [ "$(id -u)" -ne 0 ]; then
  echo "错误: 请用 sudo 运行，例如: sudo $0 ${SUDO_USER:-kamfu}" >&2
  exit 1
fi

if [ -z "$TARGET_USER" ] || [ "$TARGET_USER" = "root" ]; then
  echo "错误: 请指定普通用户名（不要给 root 加 docker 组）。" >&2
  echo "用法: sudo $0 <用户名>" >&2
  exit 1
fi

if ! getent passwd "$TARGET_USER" >/dev/null 2>&1; then
  echo "错误: 用户不存在: $TARGET_USER" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "错误: 未找到 docker 命令，请先安装 Docker。" >&2
  exit 1
fi

if [ ! -S "$SOCKET" ]; then
  echo "错误: 未找到 $SOCKET，Docker daemon 可能没有运行。" >&2
  echo "请先启动 Docker: sudo systemctl start docker" >&2
  exit 1
fi

if ! getent group docker >/dev/null 2>&1; then
  echo ">>> docker 组不存在，创建..."
  groupadd docker
fi

BEFORE_OWNER="$(stat -c '%U:%G' "$SOCKET")"
BEFORE_MODE="$(stat -c '%a' "$SOCKET")"
echo "当前 socket: $SOCKET  $BEFORE_OWNER $BEFORE_MODE"
echo "目标用户:   $TARGET_USER"
echo ""

echo ">>> 恢复 socket 属主/权限: root:docker 660"
chown root:docker "$SOCKET"
chmod 660 "$SOCKET"

# 检查用户是否已在 docker 组（这里查的是组数据库，不是当前会话）
if id -nG "$TARGET_USER" | tr ' ' '\n' | grep -qx docker; then
  echo ">>> 用户 $TARGET_USER 已在 docker 组，跳过 usermod"
else
  echo ">>> 把 $TARGET_USER 加入 docker 组"
  usermod -aG docker "$TARGET_USER"
fi

AFTER="$(stat -c '%U:%G %a' "$SOCKET")"
echo ""
echo "完成。"
echo "  socket: $AFTER"
echo "  组:     $(getent group docker)"
echo ""
echo "下一步（必须做，否则当前会话仍没有 docker 组）："
echo "  1) 注销并重新登录，或"
echo "  2) 临时进入带 docker 组的子 shell: newgrp docker"
echo ""
echo "验证："
echo "  id -nG | tr ' ' '\\n' | grep -x docker"
echo "  docker ps"
echo ""
echo "安全提醒：docker 组等价于 root。只给可信用户，不要给 nobody/nogroup。"
echo "如需回滚 socket 权限："
echo "  sudo chown $BEFORE_OWNER $SOCKET && sudo chmod $BEFORE_MODE $SOCKET"
