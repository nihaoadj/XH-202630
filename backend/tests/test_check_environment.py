import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from app.core import health as health_module


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "check_environment.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("check_environment", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_script(**environment):
    env = os.environ.copy()
    env.update(environment)
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result, json.loads(result.stdout)


def test_environment_script_exit_codes_for_required_modes():
    strict, strict_payload = run_script(
        APP_MODE="development",
        ALLOW_DEGRADED_GENERATION="false",
        LLM_API_KEY="",
    )
    demo, demo_payload = run_script(
        APP_MODE="demo",
        ALLOW_DEGRADED_GENERATION="true",
        LLM_API_KEY="",
    )
    production, production_payload = run_script(
        APP_MODE="production",
        ALLOW_DEGRADED_GENERATION="false",
        LLM_API_KEY="",
    )

    assert strict.returncode == 1
    assert strict_payload["status"] == "not_ready"
    assert demo.returncode == 2
    assert demo_payload["status"] == "degraded"
    assert production.returncode == 1
    assert production_payload["status"] == "not_ready"


def test_environment_script_ready_exit_code_without_mutating_environment(monkeypatch, capsys):
    module = load_script_module()
    original_environment = os.environ.copy()
    fake_report = SimpleNamespace(
        status="ready",
        model_dump=lambda **kwargs: {"status": "ready", "error_codes": []},
    )
    monkeypatch.setattr(health_module, "build_health_report", lambda *args, **kwargs: fake_report)

    assert module.main() == 0
    assert os.environ == original_environment
    assert json.loads(capsys.readouterr().out)["status"] == "ready"


def test_environment_script_never_echoes_key():
    secret = "environment-script-secret-key"
    result, payload = run_script(
        APP_MODE="demo",
        ALLOW_DEGRADED_GENERATION="true",
        LLM_API_KEY=secret,
    )

    assert result.returncode in {0, 2}
    assert secret not in result.stdout
    assert secret not in result.stderr
    assert "status" in payload


def test_embedding_health_check_does_not_use_network(monkeypatch):
    network_called = False

    def fail_on_network(*args, **kwargs):
        nonlocal network_called
        network_called = True
        raise AssertionError("network access")

    monkeypatch.setattr(
        "requests.sessions.Session.request",
        fail_on_network,
    )
    settings = health_module.Settings(_env_file=None, embedding_model="missing/test-model")

    result = health_module._check_embedding(settings)

    assert result.code == "EMBEDDING_MODEL_UNAVAILABLE"
    assert network_called is False
