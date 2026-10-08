"""Controlled, atomic storage for interactive-courseware artifacts."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Tuple

from app.core.storage import file_storage


ALLOWED_EXTENSIONS = {"html", "zip", "scorm.zip", "xapi.zip"}


def save_courseware_html(
    learner_id: str, resource_id: str, content: bytes, *, release_id: str | None = None
) -> Tuple[str, int, str]:
    return save_courseware_artifact(learner_id, resource_id, content, "html", release_id=release_id)


def save_courseware_artifact(
    learner_id: str, resource_id: str, content: bytes, extension: str, *, release_id: str | None = None
) -> Tuple[str, int, str]:
    """Atomically save one artifact under the controlled courseware directory."""
    learner_component = Path(learner_id)
    resource_component = Path(resource_id)
    extension_component = Path(extension)
    release_component = Path(release_id) if release_id else None
    if (
        not learner_id
        or learner_component.name != learner_id
        or len(learner_component.parts) != 1
        or not resource_id
        or resource_component.name != resource_id
        or len(resource_component.parts) != 1
        or extension not in ALLOWED_EXTENSIONS
        or extension_component.name != extension
        or (release_id is not None and (not release_id or release_component.name != release_id
                                        or len(release_component.parts) != 1))
    ):
        raise ValueError("课件文件标识不安全")

    target_dir = file_storage._get_resources_dir() / "courseware" / learner_id / resource_id
    if release_id:
        target_dir = target_dir / "releases" / release_id
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = "index.html" if extension == "html" and release_id else f"{resource_id}.{extension}"
    target = target_dir / filename
    temporary = target_dir / f".{filename}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary, "xb") as handle:
            handle.write(content)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    relative_path = str(Path("data/generated_resources") / "courseware" / learner_id /
                        resource_id / "releases" / release_id / filename) if release_id else str(
                            Path("data/generated_resources") / "courseware" / learner_id / target.name)
    return relative_path, target.stat().st_size, hashlib.sha256(content).hexdigest()
