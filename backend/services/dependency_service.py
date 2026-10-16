"""系统依赖检查与安装服务

通过 pkexec（PolicyKit 图形界面）实现无终端密码输入的一键安装。
"""

import subprocess
import shutil


# 项目所需的系统工具清单
REQUIRED_TOOLS = {
    "wmctrl": {
        "package": "wmctrl",
        "description": "窗口管理工具 — 用于检测 Nautilus 窗口和外部终端",
        "used_by": ["文件管理器（Nautilus 窗口）", "终端中心（外部终端）"],
    },
    "xdotool": {
        "package": "xdotool",
        "description": "X11 自动化工具 — 用于向外部终端发送命令",
        "used_by": ["终端中心（外部终端发送命令）"],
    },
    "sshpass": {
        "package": "sshpass",
        "description": "非交互式 SSH 密码输入 — 在 SSH 管理里保存了主机密码后，一键连接需要",
        "used_by": ["SSH 连接（密码登录）"],
        "optional": True,   # 不强制：只有给主机存了密码时才用得上
    },
}


def check_dependencies() -> dict:
    """检查所有依赖工具的安装状态"""
    result = {"all_ok": True, "tools": {}}
    for name, info in REQUIRED_TOOLS.items():
        installed = shutil.which(name) is not None
        info_copy = dict(info)
        info_copy["installed"] = installed
        result["tools"][name] = info_copy
        if not installed and not info.get("optional"):
            result["all_ok"] = False
    return result


def get_missing_packages(include_optional: bool = False) -> list[str]:
    """返回未安装的包名列表

    Args:
        include_optional: 是否一并包含可选工具（如 sshpass）
    """
    deps = check_dependencies()
    return [
        info["package"]
        for name, info in deps["tools"].items()
        if not info["installed"] and (include_optional or not info.get("optional"))
    ]


def install_missing(pkexec: bool = True, include_optional: bool = False) -> dict:
    """安装缺失的系统依赖

    Args:
        pkexec: True 使用 pkexec（GUI 密码框），False 使用 sudo（需要终端）
        include_optional: 是否一并安装可选工具（如 sshpass）
    """
    missing = get_missing_packages(include_optional=include_optional)
    if not missing:
        return {"ok": True, "message": "所有依赖已安装", "installed": []}

    packages = " ".join(missing)

    if pkexec and shutil.which("pkexec"):
        # PolicyKit 图形界面，弹窗让用户输入密码
        cmd = ["pkexec", "apt-get", "install", "-y"] + missing
    else:
        # 回退到 sudo（需要终端）
        cmd = ["sudo", "apt-get", "install", "-y"] + missing

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=120,
            env={"DEBIAN_FRONTEND": "noninteractive", "PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
        )
        # 重新检查
        still_missing = get_missing_packages()
        return {
            "ok": proc.returncode == 0 and len(still_missing) == 0,
            "message": f"已安装: {packages}" if proc.returncode == 0 else f"安装失败（返回码 {proc.returncode}）",
            "stdout": proc.stdout[-500:],
            "stderr": proc.stderr[-500:],
            "installed": [p for p in missing if p not in still_missing],
            "still_missing": still_missing,
            "method": "pkexec" if pkexec else "sudo",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "安装超时（超过 120 秒）", "installed": [], "still_missing": missing}
    except FileNotFoundError:
        return {
            "ok": False,
            "message": "未找到 pkexec 或 sudo。请手动执行: sudo apt install -y " + packages,
            "installed": [],
            "still_missing": missing,
        }
    except Exception as e:
        return {"ok": False, "message": f"安装出错: {e}", "installed": [], "still_missing": missing}
