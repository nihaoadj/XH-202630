#!/usr/bin/env python3
"""Start the local Web, interactive-courseware Worker, and frontend processes.

This launcher deliberately uses only the Python standard library so that a
new contributor can run it before backend dependencies are installed.  It
does not install packages, ingest knowledge, or create a local ``.env`` unless
the corresponding explicit option is supplied.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
LOG_DIR = BACKEND / "logs"
STATE_FILE = LOG_DIR / "local-dev-processes.json"


def find_venv_python() -> Path | None:
    """Support standard venv layouts and this repository's portable layout."""
    candidates = (
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
        ROOT / ".venv" / "python.exe",
        ROOT / ".venv" / "python",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def wait_for_json(url: str, timeout_seconds: float) -> dict | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            time.sleep(0.5)
    return None


def launch(name: str, command: list[str], cwd: Path, log_handle) -> int:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    print(f"已启动 {name}（PID {process.pid}）。日志：{log_handle.name}")
    return process.pid


def require_command(command: str) -> str:
    resolved = shutil.which(command)
    if not resolved:
        raise RuntimeError(f"未找到命令：{command}")
    return resolved


def install_dependencies(python: Path) -> None:
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(BACKEND / "requirements.txt")], check=True)
    subprocess.run([require_command("npm"), "install"], cwd=FRONTEND, check=True)


def verify_runtime_dependencies(python: Path, include_frontend: bool) -> None:
    if subprocess.run([str(python), "-c", "import uvicorn"], check=False).returncode != 0:
        raise RuntimeError("后端依赖尚未安装。请先运行：python scripts/start_local.py --install --bootstrap")
    if include_frontend:
        require_command("npm")
        if not (FRONTEND / "node_modules").is_dir():
            raise RuntimeError("前端依赖尚未安装。请先运行：python scripts/start_local.py --install --bootstrap")


def bootstrap_environment(python: Path, initialize: bool) -> None:
    env_file = BACKEND / ".env"
    if not env_file.exists():
        shutil.copyfile(BACKEND / ".env.example", env_file)
        print(f"已创建本地配置：{env_file}。请填写 LLM_API_KEY 后再生成真实资源。")
    if initialize:
        subprocess.run([str(python), str(ROOT / "scripts" / "ingest_knowledge.py")], cwd=ROOT, check=True)
        subprocess.run([str(python), str(ROOT / "scripts" / "init_db.py")], cwd=ROOT, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一键启动本地 Web、互动课件 Worker 和前端")
    parser.add_argument("--install", action="store_true", help="安装后端与前端依赖；不会下载模型或初始化数据")
    parser.add_argument("--bootstrap", action="store_true", help="缺少 backend/.env 时从模板创建；可与 --initialize 合用")
    parser.add_argument("--initialize", action="store_true", help="显式入库知识库并初始化示例数据；可能耗时")
    parser.add_argument("--check", action="store_true", help="仅校验本地前置条件，不启动任何进程")
    parser.add_argument("--no-worker", action="store_true", help="不启动互动课件 Worker")
    parser.add_argument("--no-frontend", action="store_true", help="不启动 Vite 前端")
    parser.add_argument("--no-reload", action="store_true", help="后端不使用 Uvicorn reload")
    parser.add_argument("--host", default="127.0.0.1", help="Web 与前端监听地址，默认仅本机")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument("--worker-health-host", default="127.0.0.1", help="Worker 健康端点监听地址")
    parser.add_argument("--worker-health-port", type=int, default=8081)
    parser.add_argument("--startup-timeout", type=float, default=45.0, help="各健康检查最长等待秒数")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    python = find_venv_python()
    if python is None:
        print("未找到项目虚拟环境。请先创建 .venv 并安装依赖，详见 docs/deployment.md。", file=sys.stderr)
        return 2
    if not (BACKEND / ".env").exists() and not args.bootstrap:
        print("缺少 backend/.env。请复制 backend/.env.example 后填写配置，或显式传入 --bootstrap。", file=sys.stderr)
        return 2
    if args.install:
        install_dependencies(python)
    if args.bootstrap or args.initialize:
        bootstrap_environment(python, args.initialize)
    try:
        verify_runtime_dependencies(python, include_frontend=not args.no_frontend)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.check:
        print(f"前置条件可用：Python={python}" + (f"，npm={require_command('npm')}" if not args.no_frontend else ""))
        return 0
    if not args.no_frontend and args.backend_port != 8000:
        print("当前 Vite 代理固定指向 localhost:8000；启动前端时 backend-port 必须为 8000。", file=sys.stderr)
        return 2

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    pids: dict[str, int] = {}
    backend_url = f"http://{args.host}:{args.backend_port}"
    worker_url = f"http://{args.worker_health_host}:{args.worker_health_port}"

    if port_is_open(args.host, args.backend_port):
        print(f"后端端口 {args.backend_port} 已在使用；不会替换现有服务。")
    else:
        command = [str(python), "-m", "uvicorn", "app.main:app", "--host", args.host, "--port", str(args.backend_port)]
        if not args.no_reload:
            command.append("--reload")
        with (LOG_DIR / "local-backend.log").open("ab") as log_handle:
            pids["backend"] = launch("后端", command, BACKEND, log_handle)

    if not args.no_worker:
        if port_is_open(args.worker_health_host, args.worker_health_port):
            print(f"Worker 健康端口 {args.worker_health_port} 已在使用；不会替换现有 Worker。")
        else:
            command = [str(python), str(BACKEND / "scripts" / "courseware_worker.py"), "--health-host", args.worker_health_host, "--health-port", str(args.worker_health_port)]
            with (LOG_DIR / "local-courseware-worker.log").open("ab") as log_handle:
                pids["courseware_worker"] = launch("互动课件 Worker", command, ROOT, log_handle)

    if not args.no_frontend:
        if port_is_open(args.host, args.frontend_port):
            print(f"前端端口 {args.frontend_port} 已在使用；不会替换现有前端。")
        else:
            command = [require_command("npm"), "run", "dev", "--", "--host", args.host, "--port", str(args.frontend_port), "--strictPort"]
            with (LOG_DIR / "local-frontend.log").open("ab") as log_handle:
                pids["frontend"] = launch("前端", command, FRONTEND, log_handle)

    if pids:
        STATE_FILE.write_text(json.dumps({"pids": pids, "started_at": time.time()}, ensure_ascii=False, indent=2), encoding="utf-8")
    backend_health = wait_for_json(f"{backend_url}/health", args.startup_timeout)
    worker_health = None if args.no_worker else wait_for_json(f"{worker_url}/health/ready", args.startup_timeout)
    print(f"后端健康：{backend_health.get('status') if backend_health else '不可用'}（{backend_url}/health）")
    if not args.no_worker:
        print(f"课件 Worker：{worker_health.get('status') if worker_health else '未就绪'}（{worker_url}/health/ready）")
    if not args.no_frontend:
        print(f"前端地址：http://{args.host}:{args.frontend_port}")
    if pids:
        print(f"进程记录：{STATE_FILE}；停止时请按部署文档中的正常停机方式操作。")
    else:
        print("本次未创建新进程，因此未改写进程记录。")
    return 0 if backend_health and (args.no_worker or worker_health) else 1


if __name__ == "__main__":
    raise SystemExit(main())
