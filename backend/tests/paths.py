"""Stable filesystem anchors shared by tests in nested directories."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
KNOWLEDGE_BASE_ROOT = PROJECT_ROOT / "knowledge_base"
