"""Run versioned test suites without enabling live models. Standard library only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "tests/suites.json"


def load_catalog(path: Path = CATALOG) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    ids = [item["id"] for item in data["suites"]]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError("suite IDs must be unique and nonempty")
    for name, members in data["profiles"].items():
        if not members or set(members) - set(ids):
            raise ValueError(f"invalid profile: {name}")
    return data


def select_suites(catalog: dict, profile: str | None, suite_ids: list[str]) -> list[dict]:
    requested = list(catalog["profiles"][profile]) if profile else []
    requested.extend(suite_ids)
    by_id = {item["id"]: item for item in catalog["suites"]}
    if not requested or set(requested) - set(by_id):
        raise ValueError("select a known profile or suite (use --list)")
    return [by_id[item] for item in dict.fromkeys(requested)]


def safe_environment(output: Path) -> dict[str, str]:
    env = dict(os.environ)
    temp = output / "temp"
    temp.mkdir(parents=True, exist_ok=True)
    env.update(RUN_LIVE_LLM="0", COURSEWARE_LIVE_EVAL="0", PYTHONIOENCODING="utf-8",
               TEST_BROWSER_REQUIRED="1", COURSEWARE_BROWSER_REQUIRED="1", PYTHON=sys.executable,
               TEST_RUN_OUTPUT=str(output))
    env.update(TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp))
    env["PYTHONPATH"] = str(ROOT / "backend") + os.pathsep + env.get("PYTHONPATH", "")
    return env


def command_for(suite: dict, output: Path) -> list[str]:
    replacements = {"python": sys.executable, "node": shutil.which("node") or "node", "output": str(output)}
    command = [arg.format(**replacements) for arg in suite["command"]]
    if command[1:3] == ["-m", "pytest"]:
        command.extend([f"--basetemp={output / (suite['id'] + '-temp')}",
                        "-o", f"cache_dir={output / (suite['id'] + '-cache')}"])
    return command


def stop_process(process: subprocess.Popen) -> None:
    """Terminate only the process tree started for this suite."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def run_suite(suite: dict, output: Path, env: dict[str, str]) -> dict:
    command = command_for(suite, output)
    cwd = (ROOT / suite.get("cwd", ".")).resolve()
    log = output / f"{suite['id']}.log"
    result = {"id": suite["id"], "purpose": suite["purpose"], "evidence_type": suite["evidence_type"],
              "command": command, "cwd": str(cwd), "status": "ERROR", "exit_code": None,
              "log": str(log), "duration_seconds": 0.0}
    start = time.monotonic()
    with log.open("w", encoding="utf-8") as stream:
        try:
            options = ({"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
                       if os.name == "nt" else {"start_new_session": True})
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream,
                                       stderr=subprocess.STDOUT, **options)
            try:
                result["exit_code"] = process.wait(timeout=suite["timeout_seconds"])
                result["status"] = "PASS" if result["exit_code"] == 0 else "FAIL"
            except subprocess.TimeoutExpired:
                stop_process(process)
                result["status"] = "TIMEOUT"
                result["exit_code"] = process.returncode
            except KeyboardInterrupt:
                stop_process(process)
                raise
        except OSError as error:
            # Do not echo arbitrary exception text or environment values.
            result["error_type"] = type(error).__name__
            stream.write(f"Unable to start suite: {type(error).__name__}\n")
    result["duration_seconds"] = round(time.monotonic() - start, 3)
    junit = output / f"{suite['id']}.xml"
    if junit.exists():
        try:
            cases = list(ET.parse(junit).getroot().iter("testcase"))
            result["junit"] = {"path": str(junit), "tests": len(cases),
                               "failures": sum(item.find("failure") is not None for item in cases),
                               "errors": sum(item.find("error") is not None for item in cases),
                               "skipped": sum(item.find("skipped") is not None for item in cases)}
        except ET.ParseError:
            result["junit_error"] = "invalid_xml"
            if result["status"] == "PASS":
                result["status"] = "ERROR"
    return result


def git_identity() -> dict:
    def read(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10)
    try:
        sha, status = read(["rev-parse", "HEAD"]), read(["status", "--porcelain"])
        return {"sha": sha.stdout.strip() if sha.returncode == 0 else None,
                "dirty": bool(status.stdout) if status.returncode == 0 else None}
    except (OSError, subprocess.TimeoutExpired):
        return {"sha": None, "dirty": None}


def write_summary(output: Path, summary: dict) -> None:
    summary["artifacts"] = [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                            for path in sorted(output.iterdir()) if path.is_file() and path.name not in {"summary.json", "summary.md"}]
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 测试执行报告", "", f"状态：{summary['status']}；真实模型：关闭", "",
             "| 套件 | 证据类型 | 状态 | 退出码 | 秒 | 日志 |", "|---|---|---|---|---|---|"]
    for item in summary["results"]:
        lines.append(f"| {item['id']} | {item['evidence_type']} | {item['status']} | {item['exit_code']} | "
                     f"{item['duration_seconds']} | [{item['id']}.log]({item['id']}.log) |")
    lines += ["", "各专项的跳过数以 JUnit/日志为准；离线、构建与浏览器通过不能代替真实模型统计、CI 或部署验收。"]
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    catalog = load_catalog()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--profile", choices=list(catalog["profiles"]))
    parser.add_argument("--suite", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.list:
        for name, members in catalog["profiles"].items():
            print(f"{name}: {', '.join(members)}")
        for item in catalog["suites"]:
            print(f"{item['id']} [{item['evidence_type']}]: {item['purpose']}")
        return 0
    try:
        suites = select_suites(catalog, args.profile, args.suite)
    except ValueError as error:
        parser.error(str(error))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = (args.output or ROOT / "output/test-runs" / f"{stamp}-{uuid4().hex[:8]}").resolve()
    if args.dry_run:
        for item in suites:
            print(json.dumps({"suite": item["id"], "command": command_for(item, output),
                              "cwd": str(ROOT / item.get("cwd", ".")), "live_models": "disabled"}, ensure_ascii=False))
        return 0
    # Avoid mixing evidence from separate executions, including partial previous runs.
    if output.exists() and any(output.iterdir()):
        parser.error("output directory must be empty; choose a new path")
    output.mkdir(parents=True, exist_ok=True)
    summary = {"schema_version": "1.0", "started_at": datetime.now(timezone.utc).isoformat(),
               "git": git_identity(), "catalog_sha256": hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
               "profile": args.profile, "live_models": "disabled", "status": "RUNNING", "results": []}
    env = safe_environment(output)
    stopped = False
    for suite in suites:
        if stopped:
            result = {"id": suite["id"], "evidence_type": suite["evidence_type"], "status": "NOT_RUN",
                      "exit_code": None, "duration_seconds": 0.0}
        else:
            print(f"RUN {suite['id']}", flush=True)
            result = run_suite(suite, output, env)
            print(f"{result['status']} {suite['id']} (exit={result['exit_code']}, {result['duration_seconds']}s)", flush=True)
        summary["results"].append(result)
        stopped = stopped or (args.fail_fast and result["status"] != "PASS")
        write_summary(output, summary)
    summary["status"] = "PASS" if all(item["status"] == "PASS" for item in summary["results"]) else "FAIL"
    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_summary(output, summary)
    print(f"Report: {output / 'summary.json'}")
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
