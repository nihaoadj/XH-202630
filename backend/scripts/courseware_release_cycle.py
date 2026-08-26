"""Assess a sanitized release-cycle event export; it never claims a full cycle ran."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.courseware.release_cycle import assess_release_cycle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True, help="sanitized list or {events:[...]} export")
    parser.add_argument("--metadata", type=Path, help="sanitized observation-window metadata JSON")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.events.read_text(encoding="utf-8"))
    events = payload.get("events", []) if isinstance(payload, dict) else payload
    if not isinstance(events, list):
        raise SystemExit("events export must be a JSON list or an object with events")
    metadata = json.loads(args.metadata.read_text(encoding="utf-8")) if args.metadata else {}
    report = assess_release_cycle(events, metadata=metadata)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["status"] == "LOCAL_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
