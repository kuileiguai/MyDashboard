"""FastAPI 入口"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from routers import commands, files, ports, terminal, system, logs, env, ssh, dashboard
from ws import terminal_ws, monitor_ws, log_ws


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    from database import get_db
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT COUNT(*) as c FROM commands")
        if row[0]["c"] == 0:
            await _seed_commands(db)
        row2 = await db.execute_fetchall("SELECT COUNT(*) as c FROM file_templates")
        if row2[0]["c"] == 0:
            await _seed_templates(db)

    # 启动后台监控采样任务
    import asyncio
    from services.monitor_service import _monitor_loop
    monitor_task = asyncio.create_task(_monitor_loop())

    # 启动 shell 历史自动同步任务
    from services.history_sync import history_sync_loop
    history_task = asyncio.create_task(history_sync_loop())

    yield

    # 关闭后台任务
    monitor_task.cancel()
    history_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass
    try:
        await history_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Dev Dashboard", version="1.0.0", lifespan=lifespan)

# CORS —— 开发时允许 5173
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST 路由
app.include_router(commands.router, prefix="/api/commands", tags=["M1-Commands"])
app.include_router(files.router, prefix="/api/files", tags=["M2-Files"])
app.include_router(ports.router, prefix="/api", tags=["M3-Ports"])
app.include_router(terminal.router, prefix="/api/terminal", tags=["M4-Terminal"])
app.include_router(system.router, prefix="/api/system", tags=["M5-System"])
app.include_router(logs.router, prefix="/api/logs", tags=["M6-Logs"])
app.include_router(env.router, prefix="/api/env", tags=["M7-Env"])
app.include_router(ssh.router, prefix="/api/ssh", tags=["M8-SSH"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["M9-Dashboard"])

# WebSocket 路由
app.websocket("/ws/terminal/{session_id}")(terminal_ws.websocket_endpoint)
app.websocket("/ws/system/monitor")(monitor_ws.websocket_endpoint)
app.websocket("/ws/logs/tail")(log_ws.websocket_endpoint)

# 生产环境：托管前端 dist（SPA fallback：非文件路径回退 index.html）
dist_path = Path(__file__).parent.parent / "frontend" / "dist"
if dist_path.exists():
    _dist_root = dist_path.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path:
            candidate = (_dist_root / full_path).resolve()
            # 防目录穿越，仅允许 dist 目录内的真实文件
            if candidate.is_file() and candidate.is_relative_to(_dist_root):
                return FileResponse(candidate)
        index = _dist_root / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(404, "Not found")


async def _seed_commands(db):
    """预置 50+ 常用命令"""
    seeds = [
        ("文件操作", "ls -la", "列出当前目录所有文件（含隐藏文件）", '[{"flag":"-l","meaning":"长格式显示"},{"flag":"-a","meaning":"显示所有文件包括隐藏"}]', '["ls -la /var/log"]'),
        ("文件操作", "find . -name '*.py'", "递归查找当前目录下所有 .py 文件", '[{"flag":"-name","meaning":"按文件名模式匹配"}]', '["find /home -name \\"*.log\\" -mtime -7"]'),
        ("文件操作", "du -sh *", "查看当前目录各文件/文件夹大小", '[{"flag":"-s","meaning":"汇总"},{"flag":"-h","meaning":"人类可读格式"}]', '["du -sh /var/log/* | sort -h"]'),
        ("文件操作", "df -h", "查看磁盘分区使用情况", '[{"flag":"-h","meaning":"人类可读格式"}]', '["df -h /home"]'),
        ("文件操作", "tar -czvf archive.tar.gz dir/", "压缩目录为 tar.gz", '[{"flag":"-c","meaning":"创建归档"},{"flag":"-z","meaning":"gzip压缩"},{"flag":"-v","meaning":"详细输出"},{"flag":"-f","meaning":"指定文件名"}]', '["tar -xzvf archive.tar.gz"]'),
        ("文件操作", "chmod +x script.sh", "给脚本添加执行权限", '[{"flag":"+x","meaning":"添加执行权限"}]', '["chmod 755 script.sh", "chmod -R 755 dir/"]'),
        ("文件操作", "ln -s /target /link", "创建符号链接", '[{"flag":"-s","meaning":"创建软链接"}]', '["ln -sf /new/target /link"]'),
        ("文件操作", "rsync -avz src/ dst/", "高效同步目录", '[{"flag":"-a","meaning":"归档模式"},{"flag":"-v","meaning":"详细"},{"flag":"-z","meaning":"压缩传输"}]', '["rsync -avz --delete src/ user@host:dst/"]'),
        ("网络", "ss -tlnp", "查看所有 TCP 监听端口", '[{"flag":"-t","meaning":"仅TCP"},{"flag":"-l","meaning":"监听中"},{"flag":"-n","meaning":"数字格式端口"},{"flag":"-p","meaning":"显示进程"}]', '["ss -tlnp | grep :8080", "ss -ulnp"]'),
        ("网络", "curl -X GET http://localhost:8080/api", "发送 HTTP GET 请求", '[{"flag":"-X","meaning":"指定方法"},{"flag":"-H","meaning":"自定义头"},{"flag":"-d","meaning":"POST数据"}]', '["curl -X POST -H \\"Content-Type: application/json\\" -d \\"{}\\" url"]'),
        ("网络", "ping -c 4 8.8.8.8", "测试网络连通性", '[{"flag":"-c","meaning":"发送包数"}]', '["ping -c 10 google.com"]'),
        ("网络", "nslookup example.com", "DNS 查询", '[]', '["dig example.com", "host example.com"]'),
        ("网络", "iptables -L -n", "查看防火墙规则", '[{"flag":"-L","meaning":"列出规则"},{"flag":"-n","meaning":"数字格式"}]', '["iptables -L -n -v"]'),
        ("进程", "ps aux", "查看所有进程", '[{"flag":"a","meaning":"所有用户"},{"flag":"u","meaning":"用户格式"},{"flag":"x","meaning":"含无终端进程"}]', '["ps aux | grep python", "ps aux --sort=-%mem | head -20"]'),
        ("进程", "htop", "交互式进程监控", '[]', '["top -c"]'),
        ("进程", "kill -9 PID", "强制结束进程", '[{"flag":"-9","meaning":"SIGKILL 强制终止"}]', '["kill -15 PID  (SIGTERM)", "killall -9 process_name"]'),
        ("进程", "nice -n 10 command", "以低优先级运行命令", '[{"flag":"-n","meaning":"nice值，-20最高，19最低"}]', '["renice -n 10 -p PID"]'),
        ("磁盘", "ncdu", "交互式磁盘使用分析", '[]', '["ncdu /home", "ncdu -x /  (不跨文件系统)"]'),
        ("磁盘", "iotop -o", "查看磁盘 I/O 最高的进程", '[{"flag":"-o","meaning":"仅显示有I/O的进程"}]', '["iotop -b -n 1"]'),
        ("磁盘", "lsblk", "列出所有块设备", '[]', '["lsblk -f  (含文件系统)", "blkid"]'),
        ("AI相关", "nvidia-smi", "查看 GPU 状态", '[]', '["nvidia-smi -l 1", "watch -n 2 nvidia-smi"]'),
        ("AI相关", "python -c 'import torch; print(torch.cuda.is_available())'", "检查 PyTorch CUDA 可用性", '[]', '["python -c \\"import torch; print(torch.cuda.device_count())\\""]'),
        ("AI相关", "pip list | grep torch", "查看已安装的 torch 相关包", '[]', '["conda list | grep torch"]'),
        ("AI相关", "python train.py --batch_size 32 --lr 0.001", "启动训练脚本（示例）", '[{"flag":"--batch_size","meaning":"批次大小"},{"flag":"--lr","meaning":"学习率"}]', '["python train.py --epochs 100"]'),
        ("Docker", "docker ps", "列出运行中的容器", '[]', '["docker ps -a", "docker ps --format \\"table {{.Names}}\\t{{.Status}}\\""]'),
        ("Docker", "docker logs -f container_name", "实时查看容器日志", '[{"flag":"-f","meaning":"follow 实时跟踪"}]', '["docker logs --tail 100 container_name"]'),
        ("Docker", "docker exec -it container_name bash", "进入容器 shell", '[{"flag":"-it","meaning":"交互式终端"},{"flag":"-e","meaning":"设置环境变量"}]', '["docker exec container_name cat /etc/hosts"]'),
        ("Docker", "docker-compose up -d", "启动 docker-compose 服务（后台）", '[{"flag":"-d","meaning":"后台运行"},{"flag":"--build","meaning":"重新构建"}]', '["docker-compose down", "docker-compose restart service_name"]'),
        ("Docker", "docker system prune -a", "清理未使用的镜像/容器/网络", '[{"flag":"-a","meaning":"清理所有未使用对象"}]', '["docker image prune", "docker volume prune"]'),
        ("Docker", "docker build -t name:tag .", "构建 Docker 镜像", '[{"flag":"-t","meaning":"镜像名:标签"},{"flag":"-f","meaning":"指定Dockerfile"}]', '["docker build --no-cache -t name ."]'),
        ("Git", "git log --oneline -20", "查看最近 20 条提交", '[{"flag":"--oneline","meaning":"单行显示"},{"flag":"-20","meaning":"最近20条"}]', '["git log --graph --all --oneline"]'),
        ("Git", "git diff HEAD~1", "查看最近一次变更", '[]', '["git diff --staged", "git diff main..feature"]'),
        ("Git", "git stash pop", "恢复最近一次暂存", '[]', '["git stash list", "git stash save \\"message\\""]'),
        ("Git", "git rebase -i HEAD~3", "交互式合并最近 3 条提交", '[{"flag":"-i","meaning":"交互模式"},{"flag":"HEAD~3","meaning":"最近3条"}]', '["git rebase main"]'),
        ("Git", "git remote -v", "查看远程仓库地址", '[{"flag":"-v","meaning":"详细模式"}]', '["git remote add origin url", "git remote set-url origin new_url"]'),
        ("系统管理", "systemctl status service_name", "查看服务状态", '[]', '["systemctl --user status service_name", "systemctl list-units --state=failed"]'),
        ("系统管理", "journalctl -u service_name -f", "实时查看服务日志", '[{"flag":"-u","meaning":"指定服务"},{"flag":"-f","meaning":"follow"}]', '["journalctl --user -u service_name --since today"]'),
        ("系统管理", "uname -a", "查看系统内核信息", '[{"flag":"-a","meaning":"全部信息"}]', '["lsb_release -a", "hostnamectl"]'),
        ("系统管理", "free -h", "查看内存使用", '[{"flag":"-h","meaning":"人类可读"}]', '["free -h -s 2  (每2秒刷新)"]'),
        ("系统管理", "uptime", "系统运行时间与负载", '[]', '["cat /proc/loadavg"]'),
        ("系统管理", "lscpu", "查看 CPU 信息", '[]', '["cat /proc/cpuinfo | grep \\"model name\\""]'),
        ("环境/Python", "python -m venv venv", "创建 Python 虚拟环境", '[]', '["source venv/bin/activate", "deactivate"]'),
        ("环境/Python", "conda create -n env_name python=3.11", "创建 Conda 环境", '[{"flag":"-n","meaning":"环境名称"},{"flag":"python=","meaning":"Python版本"}]', '["conda activate env_name", "conda env list"]'),
        ("环境/Python", "pip install -r requirements.txt", "批量安装 Python 依赖", '[{"flag":"-r","meaning":"从文件读取"}]', '["pip freeze > requirements.txt", "pip install package==1.0.0"]'),
        ("环境/Node", "nvm use 18", "切换 Node 版本", '[]', '["nvm ls", "nvm install 20", "node -v"]'),
        ("环境/Node", "npm install", "安装项目依赖", '[]', '["npm ci  (生产构建)", "npm update"]'),
        ("SSH", "ssh user@host -p 2222", "SSH 连接远程主机", '[{"flag":"-p","meaning":"端口"},{"flag":"-i","meaning":"指定密钥"}]', '["ssh -i ~/.ssh/id_rsa user@host"]'),
        ("SSH", "scp file.txt user@host:/path/", "复制文件到远程主机", '[]', '["scp -r dir/ user@host:/path/", "scp user@host:/path/file.txt ."]'),
        ("SSH", "ssh-keygen -t ed25519", "生成 SSH 密钥对", '[{"flag":"-t","meaning":"密钥类型"},{"flag":"-C","meaning":"注释"}]', '["ssh-copy-id user@host"]'),
        ("实用工具", "grep -r 'pattern' .", "递归搜索文本", '[{"flag":"-r","meaning":"递归"},{"flag":"-i","meaning":"忽略大小写"},{"flag":"-n","meaning":"显示行号"}]', '["grep -rn --include=\\n*.py\\n \\ndef main\\n ."]'),
        ("实用工具", "wc -l file.txt", "统计文件行数", '[{"flag":"-l","meaning":"行数"},{"flag":"-c","meaning":"字节数"}]', '["find . -name \\n*.py\\n | xargs wc -l"]'),
        ("实用工具", "history | grep 'search'", "搜索命令历史", '[]', '["history | tail -50"]'),
        ("实用工具", "alias ll='ls -alF'", "创建命令别名", '[]', '["alias  (查看所有别名)", "unalias ll"]'),
        ("实用工具", "watch -n 2 'command'", "每 2 秒执行一次命令", '[{"flag":"-n","meaning":"间隔秒数"}]', '["watch -d \\"ss -tlnp\\""]'),
    ]
    for cat, cmd, desc, params, examples in seeds:
        await db.execute(
            "INSERT INTO commands (category, command, description, params_json, examples_json) VALUES (?,?,?,?,?)",
            (cat, cmd, desc, params, examples),
        )
    await db.commit()


async def _seed_templates(db):
    """预置文件模板"""
    templates = [
        ("Python Script", ".py", "#!/usr/bin/env python3\n\"\"\"Module docstring.\"\"\"\n\nimport sys\n\ndef main():\n    pass\n\nif __name__ == \"__main__\":\n    main()\n"),
        ("Shell Script", ".sh", "#!/bin/bash\nset -euo pipefail\n\n"),
        ("Dockerfile", "Dockerfile", "FROM python:3.11-slim\n\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install -r requirements.txt\nCOPY . .\n\nCMD [\"python\", \"main.py\"]\n"),
        (".env", ".env", "# Environment variables\n"),
        ("docker-compose.yml", ".yml", "version: \"3.8\"\nservices:\n  app:\n    build: .\n    ports:\n      - \"8080:8080\"\n    volumes:\n      - .:/app\n"),
        ("Makefile", "Makefile", ".PHONY: help install test run clean\n\nhelp:\n\t@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = \":.*?## \"}; {printf \"\\033[36m%-15s\\033[0m %s\\n\", $$1, $$2}'\n\ninstall: ## Install dependencies\n\tpip install -r requirements.txt\n\ntest: ## Run tests\n\tpytest\n\nrun: ## Run the app\n\tpython main.py\n\nclean: ## Clean artifacts\n\trm -rf __pycache__ .pytest_cache\n"),
        ("README.md", ".md", "# Project\n\n## Setup\n\n```bash\npip install -r requirements.txt\n```\n\n## Usage\n\n```bash\npython main.py\n```\n"),
        ("setup.py", ".py", "from setuptools import setup, find_packages\n\nsetup(\n    name=\"project\",\n    version=\"0.1.0\",\n    packages=find_packages(),\n    install_requires=[],\n)\n"),
    ]
    for name, ext, content in templates:
        await db.execute(
            "INSERT INTO file_templates (name, extension, content) VALUES (?,?,?)",
            (name, ext, content),
        )
    await db.commit()
