"""Run the bounded, zero-LLM courseware release evaluation set."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.courseware.evaluation import build_deterministic_fixture, evaluate_courseware_case, execute_workflow_case


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("tests/fixtures/courseware/evals/manifest.json"))
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true", help="mutate observed fields and verify each is rejected")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    previous = {}
    if args.baseline and args.baseline.exists():
        payload = json.loads(args.baseline.read_text(encoding="utf-8"))
        previous = {item.get("fixture"): item.get("artifact_hash") for item in payload.get("reports", [])}

    reports = []
    for case in manifest.get("cases") or []:
        document, snapshots = build_deterministic_fixture(case)
        report = evaluate_courseware_case(case, document, snapshots, previous.get(case.get("id")))
        try:
            report["workflow_actual"] = execute_workflow_case(case)
            actual = report["workflow_actual"]
            expected_status = str(case.get("expected_status"))
            required_artifact = str(case.get("artifact_policy") or "required") == "required"
            report["workflow_actual_match"] = (
                actual.get("status") == expected_status
                and bool(actual.get("artifact_present")) == required_artifact
            )
            if not report["workflow_actual_match"]:
                report["passed"] = False
        except Exception as exc:
            report["workflow_actual"] = {
                "status": "execution_error", "artifact_hash": None,
                "execution": "workflow", "error_type": type(exc).__name__,
            }
            report["workflow_actual_match"] = False
            report["passed"] = False
        reports.append(report)
    def _passes(item):
        actual = item.get("workflow_actual") or {}
        actual_status_match = actual.get("status") == item.get("expected_status")
        actual_artifact_match = bool(actual.get("artifact_present")) == (item.get("artifact_policy") == "required")
        return (
            item["outcome_matches_manifest"]
            and item["status"] == item["expected_status"]
            and item["failed_gates"] == item["expected_failed_gates"]
            and ((item["artifact_policy"] == "required") == bool(item.get("artifact_hash")))
            and bool(item.get("workflow_actual_match"))
            and actual_status_match and actual_artifact_match
            and not ((item.get("baseline_diff") or {}).get("changed", False))
        )
    report = {
        "schema_version": manifest.get("schema_version"),
        "case_count": len(reports),
        "passed": all(_passes(item) for item in reports),
        "reports": reports,
    }
    if args.self_test:
        mutations = ("expected_status", "expected_failed_gates", "artifact_policy", "workflow_actual")
        for field in mutations:
            mutated = deepcopy(reports[0])
            if field == "expected_failed_gates":
                mutated[field] = ["tampered"]
            elif field == "artifact_policy":
                mutated[field] = "forbidden"
            elif field == "workflow_actual":
                mutated[field] = {**mutated[field], "status": "tampered"}
            else:
                mutated[field] = "tampered"
            if _passes(mutated):
                report["passed"] = False
                report.setdefault("self_test_failures", []).append(field)
        report["self_test"] = not report.get("self_test_failures")
    serialized = json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
