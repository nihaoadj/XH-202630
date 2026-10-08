"""Explicitly freeze local sources AFTER reviewing knowledge and gold annotations."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.reports.competition_evidence import build_source_snapshot, confined_path
from app.services.reports.competition_suite import default_suite_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=default_suite_path())
    args = parser.parse_args()
    suite = json.loads(args.suite.read_text(encoding="utf-8"))
    root = args.suite.parent
    claims = json.loads(confined_path(root, suite["files"]["claims"]).read_text(encoding="utf-8"))
    snapshot = build_source_snapshot(suite["knowledge_base_id"], claims)
    output = confined_path(root, suite["files"]["sources"])
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Frozen {len(snapshot['files'])} files and {len(snapshot['evidence'])} source sections: {output}")


if __name__ == "__main__":
    main()
