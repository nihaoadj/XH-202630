"""Deterministic ZIP, SCORM 1.2, and xAPI package exporters."""

import hashlib
import html
import io
import json
import zipfile
from typing import Any

from app.core.courseware.runtime import RENDERER_VERSION, RUNTIME_VERSION


def package_courseware(
    artifact: bytes, *, resource_id: str, title: str, package_format: str
) -> tuple[bytes, dict[str, Any]]:
    if package_format not in {"zip", "scorm", "xapi"}:
        raise ValueError("不支持的课件包格式")
    manifest = {
        "schema_version": "1.0", "resource_id": resource_id, "title": title,
        "format": package_format, "entrypoint": "index.html",
        "renderer_version": RENDERER_VERSION, "runtime_version": RUNTIME_VERSION,
        "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
    }
    output = io.BytesIO()
    timestamp = (2026, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        def write(name: str, content: str | bytes) -> None:
            info = zipfile.ZipInfo(name, timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)

        write("index.html", artifact)
        write("manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        if package_format == "scorm":
            escaped_title = html.escape(title, quote=True)
            write("imsmanifest.xml", (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<manifest identifier="courseware" version="1.0" '
                'xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2" '
                'xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2">'
                f'<organizations default="org"><organization identifier="org"><title>{escaped_title}</title>'
                '<item identifier="item" identifierref="resource"><title>' + escaped_title + '</title></item>'
                '</organization></organizations><resources><resource identifier="resource" type="webcontent" '
                'adlcp:scormtype="sco" href="index.html"><file href="index.html"/>'
                '<file href="manifest.json"/></resource></resources></manifest>'
            ))
        elif package_format == "xapi":
            activity_id = f"urn:courseware:{resource_id}"
            write("tincan.xml", (
                '<?xml version="1.0" encoding="utf-8"?><tincan xmlns="http://projecttincan.com/tincan.xsd">'
                f'<activities><activity id="{html.escape(activity_id, quote=True)}" type="http://adlnet.gov/expapi/activities/course">'
                f'<name lang="zh-CN">{html.escape(title)}</name><launch lang="zh-CN">index.html</launch>'
                '</activity></activities></tincan>'
            ))
    return output.getvalue(), manifest
