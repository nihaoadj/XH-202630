"""Inspect a real, isolated Edge page without relying on --dump-dom stdout."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.parse import urlsplit

import httpx
import psutil
from websockets.exceptions import ConnectionClosed
from websockets.legacy.client import connect


_STARTUP_TIMEOUT_SECONDS = 10


def _uses_profile(arguments: list[str], profile: Path) -> bool:
    expected = os.path.normcase(os.path.abspath(profile))
    values = []
    for index, argument in enumerate(arguments):
        if argument.startswith("--user-data-dir="):
            values.append(argument.partition("=")[2])
        elif argument == "--user-data-dir" and index + 1 < len(arguments):
            values.append(arguments[index + 1])
    return bool(values) and all(
        value and os.path.normcase(os.path.abspath(value)) == expected for value in values
    )


def _is_isolated_edge(process: psutil.Process, profile: Path) -> bool:
    try:
        return (process.name().lower() in {"msedge.exe", "msedge"}
                and _uses_profile(process.cmdline(), profile))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def _profile_processes(profile: Path) -> list[psutil.Process]:
    return [process for process in psutil.process_iter() if _is_isolated_edge(process, profile)]


def _terminate_detached_edge(profile: Path) -> None:
    """Only stop Edge trees with this exact fresh profile, not other browsers."""
    owned: set[psutil.Process] = set()
    for candidate in _profile_processes(profile):
        # Process objects retain PID/create-time identity; never terminate by name.
        if not _is_isolated_edge(candidate, profile):
            continue
        try:
            descendants = candidate.children(recursive=True)
            if _is_isolated_edge(candidate, profile):
                owned.update(descendants)
                owned.add(candidate)
        except psutil.NoSuchProcess:
            continue
    for candidate in owned:
        try:
            candidate.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(list(owned), timeout=2)
    for candidate in alive:
        try:
            candidate.kill()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(alive, timeout=2)
    if alive or _profile_processes(profile):
        raise RuntimeError("Isolated Edge profile still has running processes")


def _debug_endpoint(profile: Path) -> tuple[int, str]:
    lines = (profile / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()
    port = int(lines[0])
    if not 0 < port < 65536 or not lines[1].startswith("/devtools/browser/"):
        raise ValueError("Invalid isolated-browser debugging endpoint")
    return port, f"ws://127.0.0.1:{port}{lines[1]}"


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=.2):
            return True
    except OSError:
        return False


def _record_error(message: dict, errors: list[str]) -> None:
    params = message.get("params", {})
    if message.get("method") == "Runtime.exceptionThrown":
        details = params["exceptionDetails"]
        errors.append(str(details.get("exception", {}).get("description") or details.get("text")))
    elif message.get("method") == "Runtime.consoleAPICalled" and params.get("type") == "error":
        errors.append(" ".join(str(item.get("value", item.get("description", ""))) for item in params["args"]))


async def _inspect_page(page_url: str, target: Path) -> dict:
    errors: list[str] = []
    async with connect(page_url, open_timeout=3, close_timeout=1, max_size=2**22) as websocket:
        next_id = 0

        async def command(method: str, params: dict | None = None):
            nonlocal next_id
            next_id += 1
            await asyncio.wait_for(
                websocket.send(json.dumps({"id": next_id, "method": method, "params": params or {}})),
                timeout=5,
            )
            deadline = time.monotonic() + 5
            while True:
                raw = await asyncio.wait_for(websocket.recv(), timeout=max(.01, deadline - time.monotonic()))
                message = json.loads(raw)
                _record_error(message, errors)
                if message.get("id") == next_id:
                    if "error" in message:
                        raise RuntimeError(f"CDP {method} failed: {message['error']}")
                    return message.get("result", {})
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"CDP {method} did not respond")

        await command("Page.enable")
        await command("Runtime.enable")
        navigation = await command("Page.navigate", {"url": target.resolve().as_uri()})
        if navigation.get("errorText"):
            raise RuntimeError(f"Browser navigation failed: {navigation['errorText']}")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = await command("Runtime.evaluate", {
                "expression": """({readyState:document.readyState, url:location.href,
                    progress:document.querySelector('.progress')?.textContent || '',
                    sceneCount:document.querySelectorAll('.scene').length,
                    activeSceneCount:document.querySelectorAll('.scene.active').length})""",
                "returnByValue": True,
            })
            if result.get("exceptionDetails"):
                raise RuntimeError(f"DOM inspection failed: {result['exceptionDetails']}")
            state = result.get("result", {}).get("value", {})
            if state.get("readyState") == "complete" and state.get("url") == target.resolve().as_uri():
                return {**state, "errors": errors}
            await asyncio.sleep(.05)
        raise TimeoutError("Generated page did not finish loading")


async def _close_browser(browser_url: str, port: int) -> None:
    try:
        async with connect(browser_url, open_timeout=2, close_timeout=1) as websocket:
            await asyncio.wait_for(websocket.send(json.dumps({"id": 1, "method": "Browser.close"})), timeout=2)
            try:
                await asyncio.wait_for(websocket.recv(), timeout=2)
            except ConnectionClosed:
                pass
    except (OSError, ConnectionClosed, TimeoutError):
        # Browser.close may close the socket before acknowledging the command.
        # The port check below still makes a leaked browser a test failure.
        pass
    deadline = time.monotonic() + 3
    while _port_open(port) and time.monotonic() < deadline:
        await asyncio.sleep(.05)
    if _port_open(port):
        raise RuntimeError("Isolated browser debugging endpoint did not close")


async def _read_edge_page(edge: str, target: Path, profile: Path) -> dict:
    profile.mkdir(parents=True, exist_ok=False)
    port = None
    browser_url = None
    stderr_path = profile.parent / f"{profile.name}.stderr.log"
    with stderr_path.open("wb") as stderr:
        process = subprocess.Popen(
            [edge, "--headless=new", "--disable-gpu", "--disable-extensions", "--no-first-run",
             "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
             f"--user-data-dir={profile.resolve()}", "about:blank"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=stderr,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            start_new_session=os.name != "nt",
        )
        try:
            deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                try:
                    port, browser_url = _debug_endpoint(profile)
                    break
                except (OSError, ValueError, IndexError):
                    # Windows Edge can detach its real browser from the
                    # launcher; a successful launcher exit is not readiness.
                    await asyncio.sleep(.05)
            else:
                raise TimeoutError(f"Edge CDP startup timed out: {stderr_path.read_text(encoding='utf-8', errors='replace')[-2000:]}")
            with httpx.Client(trust_env=False, timeout=3) as client:
                response = client.get(f"http://127.0.0.1:{port}/json/list")
                response.raise_for_status()
                page = next(item for item in response.json() if item.get("type") == "page")
            page_url = page["webSocketDebuggerUrl"]
            endpoint = urlsplit(page_url)
            if endpoint.hostname != "127.0.0.1" or endpoint.port != port:
                raise ValueError("Page is not in the isolated browser")
            return await _inspect_page(page_url, target)
        finally:
            try:
                if browser_url is None:
                    try:
                        port, browser_url = _debug_endpoint(profile)
                    except (OSError, ValueError, IndexError):
                        pass
                if browser_url is not None:
                    await _close_browser(browser_url, port)
            finally:
                try:
                    if browser_url is None or _port_open(port):
                        await asyncio.to_thread(_terminate_detached_edge, profile)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=3)


def read_edge_page(edge: str, target: Path, profile: Path) -> dict:
    """Return actual DOM state and JavaScript errors, then close our browser."""
    return asyncio.run(_read_edge_page(edge, target, profile))
