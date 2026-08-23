"""Create a redacted, local release-candidate manifest from acceptance evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.courseware.release_candidate import build_release_candidate_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluator", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--fault-matrix", type=Path, required=True)
    parser.add_argument("--journey", type=Path, required=True)
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--live-model", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_release_candidate_report(
        evaluator_path=args.evaluator, artifact_summary_path=args.artifacts,
        fault_matrix_path=args.fault_matrix, journey_summary_path=args.journey, browser_summary_path=args.browser,
        live_model_path=args.live_model,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["status"] == "LOCAL_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
