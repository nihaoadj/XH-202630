"""Versioned, platform-owned browser runtime and theme.

Assets store the final platform source, including the existing CSS override
order. Read relative to this module, normalizing checkout line endings to the
LF strings previously assembled here. Renderer, security and packaging keep
consuming the same public constants and embedded asset bytes.
"""

from pathlib import Path

RENDERER_VERSION = "2.2"
RUNTIME_VERSION = "2.2"
ALLOWED_SCENE_KINDS = {"intro", "explain", "example", "compare", "practice", "scenario", "quiz", "recap"}

_ASSET_DIR = Path(__file__).with_name("assets")
STYLE = (_ASSET_DIR / "theme.css").read_text(encoding="utf-8")
SCRIPT = (_ASSET_DIR / "runtime.js").read_text(encoding="utf-8")
