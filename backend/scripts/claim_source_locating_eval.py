"""Offline T42 source-locating policy gate (component level).

Runs the production ``locate`` entry on the frozen synthetic calibration or
acceptance split. It never reads .env, never touches a database and never
instantiates a provider. Calibration and acceptance modes share the same code;
only the data split differs, and acceptance mode never writes back any
parameter or gold label.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.resource_workflows.learning_documents.claim_extraction.prompts.extract_v2 import PROMPT as PROMPT_V2
from app.agents.resource_workflows.learning_documents.claim_extraction.source_locating import (
    locate, load_rules, rules_digest, WorkCounter,
)
from app.models.reviews.claim_extraction import BatchOutputV2, SourceLocatingPolicy, digest

SCHEMA_VERSION = "claim-source-locating-eval-1.0"
SOURCE_FILES = (
    "backend/app/agents/resource_workflows/learning_documents/claim_extraction/source_locating/api.py",
    "backend/app/agents/resource_workflows/learning_documents/claim_extraction/source_locating/normalization.py",
    "backend/app/agents/resource_workflows/learning_documents/claim_extraction/source_locating/approximate.py",
    "backend/app/agents/resource_workflows/learning_documents/claim_extraction/source_locating/rules.py",
    "backend/app/agents/resource_workflows/learning_documents/claim_extraction/source_locating/types.py",
    "backend/app/agents/resource_workflows/learning_documents/claim_extraction/source_locating/rules_v1.json",
    "backend/app/agents/resource_workflows/learning_documents/claim_extraction/prompts/extract_v2.py",
    "backend/app/models/reviews/claim_extraction.py",
    "backend/scripts/claim_source_locating_eval.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sources() -> dict:
    return {name: _sha256(BACKEND_ROOT.parent / name) for name in SOURCE_FILES}


def _policy(rules, algorithm_version="locator-v2") -> SimpleNamespace:
    locating = SourceLocatingPolicy(
        locator_algorithm_version=algorithm_version,
        mode="tolerant_v1",
        extractor_prompt_hash=digest(PROMPT_V2),
        output_schema_hash=digest(BatchOutputV2.model_json_schema()),
        rules_hash=rules.hash,
        max_edits=rules.thresholds.max_edits,
        max_edit_ratio=rules.thresholds.max_edit_ratio,
        min_effective_chars=rules.thresholds.min_effective_chars,
        min_score_margin=rules.thresholds.min_score_margin,
        max_unit_chars=rules.thresholds.max_unit_chars,
        max_candidate_chars=rules.thresholds.max_candidate_chars,
        max_dp_cells_per_ref=rules.thresholds.max_dp_cells_per_ref,
        max_distinct_intervals=rules.thresholds.max_distinct_intervals,
        max_work_cells_per_batch=rules.thresholds.max_work_cells_per_batch,
    )
    return SimpleNamespace(source_locating=locating)


def _load_manifest(manifest_path: Path) -> tuple[dict, Path]:
    manifest_path = Path(manifest_path).resolve()
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") not in {
            "source-locating-fixtures-1.0", "source-locating-fixtures-2.0"}:
        raise ValueError("unsupported source-locating fixture schema")
    if manifest.get("synthetic") is not True:
        raise ValueError("non-synthetic fixture manifest rejected")
    return manifest, manifest_path.parent


def _load_split(manifest_dir: Path, manifest: dict, split: str) -> list[dict]:
    if split not in {"calibration", "acceptance"}:
        raise ValueError("split must be calibration or acceptance")
    record = manifest.get("splits", {}).get(split)
    if not record:
        raise ValueError(f"split metadata missing: {split}")
    path = (manifest_dir / record["path"]).resolve()
    # Path escape and missing-file guards.
    if not path.is_relative_to(manifest_dir):
        raise ValueError(f"split path escapes fixture directory: {record['path']}")
    if not path.exists():
        raise ValueError(f"split file missing: {record['path']}")
    if _sha256(path) != record["sha256"]:
        raise ValueError(f"split hash mismatch: {split}")
    samples = json.loads(path.read_text(encoding="utf-8"))
    if len(samples) != record["count"]:
        raise ValueError(f"split count mismatch: {split}")
    _validate_samples(samples, manifest)
    return samples


def _validate_samples(samples: list[dict], manifest: dict) -> None:
    ids = [s["id"] for s in samples]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate sample id")
    groups = set(manifest.get("source_groups", []))
    if not groups:
        raise ValueError("source groups missing")
    for s in samples:
        if manifest["schema_version"] == "source-locating-fixtures-2.0":
            if not s.get("source_template") or "source_text_gold" not in s:
                raise ValueError("v2 sample requires source_template and source_text_gold")
        if s["source_group"] not in groups:
            raise ValueError(f"unknown source group: {s['source_group']}")
        if s["category"] not in {"exact", "format", "edit", "reject"}:
            raise ValueError(f"unknown category: {s['category']}")
        if not (0 <= s["unit_start"] < s["unit_end"] <= len(s["text"])):
            raise ValueError(f"invalid unit span: {s['id']}")
        exp = s["expect"]
        if exp.get("accept"):
            # Gold span must slice the frozen text exactly (write-back fidelity).
            if not (0 <= exp["start"] < exp["end"] <= len(s["text"])
                    and s["unit_start"] <= exp["start"] < exp["end"] <= s["unit_end"]
                    and s["text"][exp["start"]:exp["end"]]
                        == s.get("source_text_gold", s["claim_text"])):
                raise ValueError(f"gold accept span does not slice the frozen text: {s['id']}")
        else:
            if not exp.get("code"):
                raise ValueError(f"reject sample missing code: {s['id']}")


def validate_independence(manifest_dir: Path, manifest: dict) -> None:
    """Reject cross-split source and numeric-template leakage before evaluation."""
    cal = _load_split(manifest_dir, manifest, "calibration")
    acc = _load_split(manifest_dir, manifest, "acceptance")
    for field in ("source_group", "source_template"):
        left = {s[field] for s in cal if field in s}
        right = {s[field] for s in acc if field in s}
        if left & right:
            raise ValueError(f"cross-split {field} leakage")
    def templates(samples):
        return {re.sub(r"\d+", "#", re.sub(r"\s+", "", s["text"])) for s in samples}
    if templates(cal) & templates(acc):
        raise ValueError("cross-split text/template leakage")


def evaluate(manifest_path: Path, split: str, output_path: Path | None = None) -> dict:
    manifest, manifest_dir = _load_manifest(manifest_path)
    independent = manifest["schema_version"] == "source-locating-fixtures-2.0"
    if independent:
        validate_independence(manifest_dir, manifest)
    rules = load_rules()
    # Frozen rules parameters must match the live asset and the manifest gates.
    rp = json.loads((manifest_dir / manifest["rules_parameters"]["path"]).read_text(encoding="utf-8"))
    if rp.get("rules_hash") != rules.hash:
        raise ValueError("rules parameters hash does not match the frozen rules asset")
    if rp.get("frozen_gates") != manifest.get("frozen_gates"):
        raise ValueError("manifest and rules-parameter gates disagree")
    policy = _policy(rules, "locator-v2" if independent else "locator-v1")
    samples = _load_split(manifest_dir, manifest, split)

    results = []
    stats = {"exact": {"total": 0, "ok": 0}, "format": {"total": 0, "ok": 0},
             "edit": {"total": 0, "ok": 0}, "reject": {"total": 0, "ok": 0,
             "wrong_accept": 0}}
    reject_by_code = {}
    wrong_span = 0
    for s in samples:
        unit = SimpleNamespace(unit_id="u", kind=s["unit_kind"], start=s["unit_start"], end=s["unit_end"])
        work = WorkCounter(policy.source_locating.max_work_cells_per_batch)
        outcome = locate(s["text"], unit, s["ref"], policy, rules, work)
        exp = s["expect"]
        cat = s["category"]
        stats[cat]["total"] += 1
        if exp["accept"]:
            correct = outcome.accepted and outcome.start == exp["start"] and outcome.end == exp["end"]
            stats[cat]["ok"] += int(correct)
            if outcome.accepted and not correct:
                wrong_span += 1
        else:
            if outcome.accepted:
                stats[cat]["wrong_accept"] += 1
            else:
                stats[cat]["ok"] += 1
            reject_by_code[outcome.code] = reject_by_code.get(outcome.code, 0) + 1
        results.append({"id": s["id"], "source_group": s["source_group"], "category": s["category"],
                        "error_class": s["error_class"], "level": outcome.level, "code": outcome.code,
                        "edits": outcome.edits, "score": outcome.score})

    exact_acc = stats["exact"]["ok"] / stats["exact"]["total"]
    fmt_rate = stats["format"]["ok"] / stats["format"]["total"]
    edit_rate = stats["edit"]["ok"] / stats["edit"]["total"]
    gates = {
        "unique_exact_span_accuracy": exact_acc,
        "format_recovery": fmt_rate,
        "edit_recovery": edit_rate,
        "must_reject_wrong_accept": stats["reject"]["wrong_accept"],
        "accepted_wrong_span": wrong_span,
    }
    frozen = manifest["frozen_gates"]
    gate_results = {
        "unique_exact_span_accuracy": "PASS" if exact_acc >= frozen["unique_exact_span_accuracy"] else "FAIL",
        "format_recovery": "PASS" if fmt_rate >= frozen["format_recovery_min"] else "FAIL",
        "edit_recovery": "PASS" if edit_rate >= frozen["edit_recovery_min"] else "FAIL",
        "must_reject_wrong_accept": "PASS" if stats["reject"]["wrong_accept"] == 0 else "FAIL",
        "accepted_wrong_span": "PASS" if wrong_span == 0 else "FAIL",
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": split,
        "manifest": {"path": str(manifest_path.resolve()), "sha256": _sha256(manifest_path.resolve())},
        "sources": _sources(),
        "rules": {"hash": rules.hash, "thresholds": {
            "max_edits": rules.thresholds.max_edits,
            "max_edit_ratio": rules.thresholds.max_edit_ratio,
            "min_effective_chars": rules.thresholds.min_effective_chars,
            "min_score_margin": rules.thresholds.min_score_margin}},
        "policy": {"source_locating": policy.source_locating.model_dump(mode="json")},
        "runtime": {"python": platform.python_version()},
        "totals": {"sample_total": len(samples),
                   "unique_exact": stats["exact"]["total"],
                   "format": stats["format"]["total"],
                   "edit": stats["edit"]["total"],
                   "reject": stats["reject"]["total"]},
        "metrics": {
            "unique_exact_accuracy": round(exact_acc, 6),
            "format_recovery": round(fmt_rate, 6),
            "edit_recovery": round(edit_rate, 6),
            "must_reject_wrong_accept": stats["reject"]["wrong_accept"],
            "accepted_wrong_span": wrong_span,
            "reject_by_code": reject_by_code,
            "wrong_binding": wrong_span,
        },
        "gates": gate_results,
        "independence": "SOURCE_GROUPS_DISJOINT" if independent else "NOT_PROVEN_HISTORICAL",
        "locator_algorithm_version": policy.source_locating.locator_algorithm_version,
        "source_group_count": len({s["source_group"] for s in samples}),
        "distinct_text_count": len({s["text"] for s in samples}),
        "not_measured_component": [
            "resource completion rate",
            "logical calls / physical attempts",
            "tokens and elapsed time",
            "real model recall / precision",
        ],
        "results": results,
    }
    if output_path is not None:
        output_path = Path(output_path)
        if output_path.exists():
            raise FileExistsError(f"refusing to overwrite existing evidence: {output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--split", required=True, choices=["calibration", "acceptance"])
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)
    try:
        if args.output and Path(args.output).exists():
            raise FileExistsError("output exists; refusing overwrite")
        result = evaluate(Path(args.manifest), args.split, Path(args.output) if args.output else None)
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    failed = [key for key, value in result["gates"].items() if value == "FAIL"]
    print(json.dumps({"mode": result["mode"], "totals": result["totals"],
                      "metrics": result["metrics"], "gates": result["gates"]}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
