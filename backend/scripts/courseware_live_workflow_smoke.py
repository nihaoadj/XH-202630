"""Run the bounded DeepSeek normal-path courseware workflow smoke."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.courseware.live_workflow_smoke import run_bounded_live_workflow


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--enable", action="store_true", help="explicitly authorize the bounded real-provider smoke")
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_bounded_live_workflow(
        config_path=args.config, enabled=args.enable, artifact_root=args.artifact_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if report["status"] in {"DONE", "LOCAL_READY"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
