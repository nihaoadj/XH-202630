"""Emit deterministic HTML/ZIP evidence for the courseware quality job."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.courseware.packaging import package_courseware
from app.core.courseware.renderer import render_courseware


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from app.core.courseware.evaluation import build_deterministic_fixture

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    artifacts = []
    covered_cases = []
    for index, case in enumerate(manifest.get("cases") or []):
        case_id = str(case.get("id", "fixture"))
        covered_cases.append(case_id)
        if case.get("artifact_policy") == "forbidden":
            artifacts.append({"case": case_id, "format": "none", "status": "not_applicable"})
            continue
        document, _snapshots = build_deterministic_fixture(case)
        if not document.get("scenes"):
            # Admission/release rejection is evidence too.  Record the case
            # explicitly without inventing a file or hash that was never
            # produced.
            artifacts.append({"case": case_id, "format": "none", "status": "not_applicable"})
            continue
        prefix = f"{index:02d}-{case_id}"
        try:
            html = render_courseware(document)
        except Exception as exc:
            artifacts.append({"case": case_id, "format": "html", "status": "blocked", "error_type": type(exc).__name__})
            continue
        html_path = args.output / f"{prefix}.html"
        html_path.write_bytes(html)
        artifacts.append({"case": case_id, "format": "html", "status": "produced", "path": html_path.name, "sha256": hashlib.sha256(html).hexdigest()})
        for package_format in ("zip", "scorm", "xapi"):
            package, package_manifest = package_courseware(html, resource_id=f"ci-courseware-{index}", title=document["title"], package_format=package_format)
            package_path = args.output / (f"{prefix}.zip" if package_format == "zip" else f"{prefix}.{package_format}.zip")
            package_path.write_bytes(package)
            artifacts.append({"case": case_id, "format": package_format, "status": "produced", "path": package_path.name, "sha256": hashlib.sha256(package).hexdigest(), "manifest": package_manifest})
    (args.output / "artifact-summary.json").write_text(
        json.dumps({"schema_version": "1.1", "case_count": len(covered_cases), "covered_cases": covered_cases, "artifacts": artifacts}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
