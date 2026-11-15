"""Asset extraction preserves pre-T13 bytes across cwd and checkout formats."""

import hashlib
import runpy
from pathlib import Path

import pytest

from app.core.courseware import runtime

PUBLIC_CONSTANTS = ("RENDERER_VERSION", "RUNTIME_VERSION", "ALLOWED_SCENE_KINDS", "STYLE", "SCRIPT")


@pytest.mark.parametrize("name,expected_hash", [
    ("STYLE", "f290f4ecd175fc6e40b4d07db0538ec8700699a563dedc9c2ca4d3e70eb21516"),
    ("SCRIPT", "1373c22e1029928139ba0e002d0344a4396fca2d2f2227264e5baf084a4fb5f2"),
])
def test_platform_assets_preserve_pre_extraction_bytes(name, expected_hash):
    assert hashlib.sha256(getattr(runtime, name).encode("utf-8")).hexdigest() == expected_hash


def test_assets_load_without_repository_working_directory(tmp_path, monkeypatch):
    runtime_path = Path(runtime.__file__).resolve()
    monkeypatch.chdir(tmp_path)
    loaded = runpy.run_path(str(runtime_path))

    for name in PUBLIC_CONSTANTS:
        assert loaded[name] == getattr(runtime, name)


def test_crlf_checkout_keeps_original_lf_runtime(tmp_path):
    copied_runtime = tmp_path / "runtime.py"
    copied_runtime.write_text(Path(runtime.__file__).read_text(encoding="utf-8"), encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    for name, value in (("theme.css", runtime.STYLE), ("runtime.js", runtime.SCRIPT)):
        (assets / name).write_bytes(value.replace("\n", "\r\n").encode("utf-8"))

    loaded = runpy.run_path(str(copied_runtime))

    for name in PUBLIC_CONSTANTS:
        assert loaded[name] == getattr(runtime, name)
