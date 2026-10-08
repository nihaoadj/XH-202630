"""Run or validate the opt-in interactive-courseware live-model acceptance."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.courseware.live_model import run_fake_provider_acceptance, run_live_model_acceptance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true", help="run the local fake-provider contract and metrics acceptance")
    parser.add_argument("--config", type=Path, help="versioned non-secret provider/pricing JSON for a manual real run")
    parser.add_argument("--enable", action="store_true", help="explicitly authorize the manual real-provider invocation")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_fake_provider_acceptance() if args.fake else run_live_model_acceptance(config_path=args.config, enabled=args.enable)
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    return 0 if report["status"] in {"LOCAL_READY", "DONE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
