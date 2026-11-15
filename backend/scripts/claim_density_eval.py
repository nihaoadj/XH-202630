"""Offline T37 density-packing diagnostics.

Calls the production planner and the production message/window builder on frozen
synthetic fixtures. It never reads .env, never touches a business database and
never instantiates a provider. A historical manifest is optional and only
re-checks a frozen fit sample.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.resource_workflows.learning_documents.claim_extraction.batching import plan_batches, risk_chars
from app.agents.resource_workflows.learning_documents.claim_extraction.budget import check_window
from app.agents.resource_workflows.learning_documents.claim_extraction.prompts.builder import build_messages
from app.core.llm.counting import CharacterEstimator
from app.models.reviews.claim_extraction import BatchOutput, EstimatePolicy, digest

SCHEMA_VERSION = "claim-density-eval-1.0"
SOURCE_FILES = (
    "backend/tests/fakes/claim_extraction.py",
    "backend/tests/fakes/llm.py",
    "backend/tests/fakes/evidence.py",
    "backend/app/agents/resource_workflows/learning_documents/claim_review_agent.py",
    "backend/app/agents/resource_workflows/learning_documents/claim_extraction/segmentation.py",
    "backend/app/agents/resource_workflows/learning_documents/claim_extraction/payloads.py",
    "backend/app/agents/resource_workflows/learning_documents/claim_extraction/prompts/extract.py",
    "backend/app/models/reviews/claims.py",
    "backend/app/core/llm/counting.py",
    "backend/app/models/reviews/claim_extraction.py",
    "backend/app/agents/resource_workflows/learning_documents/claim_extraction/executor.py",
    "backend/app/agents/resource_workflows/learning_documents/claim_extraction/merge.py",
    "backend/app/agents/resource_workflows/learning_documents/claim_extraction/batching.py",
    "backend/app/agents/resource_workflows/learning_documents/claim_extraction/budget.py",
    "backend/app/agents/resource_workflows/learning_documents/claim_extraction/prompts/builder.py",
    "backend/scripts/claim_density_eval.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sources() -> dict:
    return {name: _sha256(BACKEND_ROOT.parent / name) for name in SOURCE_FILES}


def _policy(manifest_dir: Path, density: bool) -> EstimatePolicy:
    raw = json.loads((manifest_dir / "policies" / "estimate_2_0_baseline.json").read_text(encoding="utf-8"))
    if not density:
        return EstimatePolicy.model_validate(raw)
    raw["density_batching"] = {"version": "claim-density-v1", "enabled": True,
                               "chars_per_claim": 35.0, "capacity_share": 0.9}
    return EstimatePolicy.model_validate(raw)


def _fits(policy, text, resource=None, allowed_nodes=None):
    counter = CharacterEstimator(policy.estimator_parameters)
    resource = resource or SimpleNamespace(resource_id="r", version=1, resource_type="讲义")

    def check(batch):
        messages = build_messages(text, resource, batch, policy, allowed_nodes or set())
        try:
            return check_window(policy, counter, messages, BatchOutput, policy.extractor_options) <= policy.target_tokens
        except ValueError:
            return False

    return check


def _covered(text: str, batches, start: int, end: int) -> bool:
    return any(unit.start <= start and end <= unit.end for batch in batches for unit in batch.units)


def _scripted_replay(text, policy, facts, *, omit_fact_ids=frozenset()):
    """Frozen gold is emitted by a fake transport, then real nodes validate it.

    This tests candidate preservation and judgement coverage, not model recall.
    Deliberate omission is exposed for negative tests of the scoring harness.
    """
    from unittest.mock import patch
    from app.core.execution import execution_session
    from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_extract_node, claim_judge_node
    from tests.fakes.claim_extraction import state_for_extraction, prepare_ledger, snapshot_for, neutral_settings, judge_all

    settings = neutral_settings()
    state, _, _, gateway, _ = state_for_extraction(text, settings=settings)
    _, repository = prepare_ledger(p=policy, run_id=state["run_id"])
    state.update(snapshot_for(policy))
    counter = CharacterEstimator(policy.estimator_parameters)

    def scripted(call):
        if call["context"].node_name == "claim_judge":
            return judge_all(call)
        payload = json.loads(call["messages"][-1].content)
        units = []
        for unit in payload["target_units"]:
            candidates = [dict(claim_text=f["text"], claim_type="factual", source_text=f["text"],
                               source_start=f["start"]-unit["unit_start"], source_end=f["end"]-unit["unit_start"],
                               knowledge_point_id=None)
                          for f in facts if f["fact_id"] not in omit_fact_ids
                          and unit["unit_start"] <= f["start"] < f["end"] <= unit["unit_end"]]
            units.append(dict(unit_id=unit["unit_id"], status="claims" if candidates else "non_factual",
                              reason="frozen synthetic oracle", claims=candidates))
        return {k: payload[k] for k in ("resource_id", "resource_version", "content_hash", "batch_id")} | {"units": units}

    gateway.outcomes = [scripted] * 64
    with patch("app.agents.resource_workflows.learning_documents.claim_review_agent.get_settings", lambda: settings):
        with execution_session(state["run_id"], "owner"):
            state.update(claim_extract_node(state, llm_gateway=gateway, claim_extraction_repository=repository,
                                            claim_extraction_counter=counter))
            if state.get("extracted_claims"):
                state.update(claim_judge_node(state, llm_gateway=gateway, claim_extraction_repository=repository,
                                              claim_extraction_counter=counter))
    actual = {(c["source_start"], c["source_end"], c["claim_text"]) for c in state.get("extracted_claims", [])}
    expected = {(f["start"], f["end"], f["text"]) for f in facts}
    saved = repository.get(state["run_id"]).state
    judged = {j["claim_id"] for j in state.get("claim_judgements", [])}
    ids = {c["claim_id"] for c in state.get("extracted_claims", [])}
    return dict(gold_total=len(expected), gold_covered=len(expected & actual), extra=len(actual-expected),
                judge_complete=judged == ids and (bool(ids) or not facts),
                calls=saved.calls, attempts=saved.attempts, tokens=saved.tokens,
                replaced_batches=sum(len(r.replaced_batches) for r in saved.results.values()),
                expected_empty_failure=not facts and not actual,
                status=state.get("claim_check_status"))


def _partition_ok(text: str, batches) -> bool:
    covered = [0] * len(text)
    for batch in batches:
        for unit in batch.units:
            for index in range(unit.start, unit.end):
                covered[index] += 1
    spans = [unit for batch in batches for unit in batch.units]
    ascending = all(a.end == b.start for a, b in zip(spans, spans[1:]))
    return all(count == 1 for count in covered) and ascending and spans[0].start == 0 and spans[-1].end == len(text)


def replay_historical(manifest_path):
    """Read frozen local artifacts, with the exact production window predicate."""
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 'claim-density-historical-1.0':
        raise ValueError('unsupported historical schema')
    material = {}
    for key in ['text','policy']:
        record = manifest[key]
        source = (path.parent/record['path']).resolve()
        if not source.is_relative_to(path.parent) or _sha256(source) != record['sha256']:
            raise ValueError('historical input path/hash mismatch')
        material[key] = source.read_bytes().decode('utf-8')
    policy = EstimatePolicy.model_validate(json.loads(material['policy']))
    resource = SimpleNamespace(**manifest['resource'])
    result = dict(quality_gate='NOT_RUN_OFFLINE',source_hash=manifest['text']['sha256'])
    for variant, p in [('baseline',policy.model_copy(update={'density_batching':None})),('candidate',policy)]:
        batches = plan_batches(material['text'],p,CharacterEstimator(p.estimator_parameters),
                               fits=_fits(p,material['text'],resource,set(manifest['target_skill_nodes'])))
        result[variant] = dict(batches=len(batches),batch_ids=[b.batch_id for b in batches],
                               risk_chars=[risk_chars(b.units) for b in batches])
        if len(batches) != manifest['expected'][variant+'_batches']:
            raise ValueError('historical batch expectation mismatch')
    return result


def evaluate(manifest_path: Path, output_path: Path | None = None) -> dict:
    manifest_path = Path(manifest_path).resolve()
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest missing: {manifest_path}")
    manifest_dir = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "density-fixtures-1.0":
        raise ValueError("unsupported density fixture schema")
    required_policies = {'baseline_estimate_2_0':'policies/estimate_2_0_baseline.json',
                         'legacy_extraction_1_0':'policies/extraction_1_0_baseline.json'}
    if any(manifest.get('policies',{}).get(key,{}).get('path') != value
           or not manifest['policies'][key].get('digest') for key,value in required_policies.items()):
        raise ValueError('required frozen policy hash/path metadata missing')
    if (not manifest.get('texts') or set(manifest['texts']) != set(manifest.get('labels',{}))
            or set(manifest['texts']) != set(manifest.get('expectations',{}).get('per_text',{}))):
        raise ValueError('fixture text/label/expectation identities disagree')
    if any(not isinstance(r.get('sha256'), str) or len(r['sha256']) != 64
           for r in [*manifest['texts'].values(), *manifest['labels'].values()]):
        raise ValueError('fixture hash metadata missing')
    policies = {"baseline": _policy(manifest_dir, density=False),
                "candidate": _policy(manifest_dir, density=True)}
    result = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest": {"path": str(manifest_path), "sha256": _sha256(manifest_path)},
        "sources": _sources(),
        "policies": {name: {"digest": digest(policy),
                            "density_batching": (policy.density_batching.model_dump(mode="json")
                                                 if policy.density_batching else None),
                            "batch_claims": policy.batch_claims}
                     for name, policy in policies.items()},
        "texts": {},
        "not_measured": [
            "real model recall/precision (scripted outputs only)",
            "Judge capacity above the fixture sizes",
            "production token savings",
        ],
    }
    problems = []
    for record in manifest["policies"].values():
        raw = json.loads((manifest_dir / record["path"]).read_text(encoding="utf-8"))
        if digest(raw) != record["digest"]:
            problems.append("policy hash mismatch: " + record["path"])
    if policies["candidate"].density_batching.model_dump(mode="json") != manifest["density_fixture"]:
        problems.append("density policy expectation mismatch")
    for name, meta in sorted(manifest["texts"].items()):
        text_path = manifest_dir / "texts" / (name + ".md")
        with open(text_path, encoding="utf-8", newline="") as handle:
            text = handle.read()
        actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if actual != meta["sha256"]:
            problems.append(f"text hash mismatch: {name}")
        label = json.loads((manifest_dir / "labels" / (name + ".json")).read_text(encoding="utf-8"))
        facts = label.get("facts", [])
        if (label.get("text_sha256") != actual or label.get("python_chars") != len(text)
                or len({f["fact_id"] for f in facts}) != len(facts)
                or any(not 0 <= f["start"] < f["end"] <= len(text)
                       or text[f["start"]:f["end"]] != f["text"] for f in facts)):
            problems.append(f"gold coverage label/source mismatch: {name}")
        label_meta = manifest.get("labels", {}).get(name, {})
        label_bytes = (manifest_dir / "labels" / (name + ".json")).read_bytes()
        if label_meta.get("sha256") and hashlib.sha256(label_bytes).hexdigest() != label_meta["sha256"]:
            problems.append(f"label hash mismatch: {name}")
        entry = {"chars": len(text), "sha256": actual}
        for label_name, policy in policies.items():
            counter = CharacterEstimator(policy.estimator_parameters)
            batches = plan_batches(text, policy, counter, fits=_fits(policy, text, None))
            entry[label_name] = {
                "batches": len(batches),
                "per_batch": [{"batch_id": batch.batch_id,
                               "units": len(batch.units),
                               "spans": [[unit.start, unit.end] for unit in batch.units],
                               "kinds": [unit.kind for unit in batch.units],
                               "risk_chars": risk_chars(batch.units),
                               "predicted_claims": round(risk_chars(batch.units) / 35.0, 2),
                               "contexts": [[span.start, span.end] for span in batch.context]}
                              for batch in batches],
                "total_risk_chars": sum(risk_chars(batch.units) for batch in batches),
                "partition_ok": _partition_ok(text, batches),
            }
            if not entry[label_name]["partition_ok"]:
                problems.append(f"partition failure: {name}/{label_name}")
            execution = _scripted_replay(text, policy, facts)
            entry[label_name]["execution"] = execution
            if (execution["gold_covered"] != len(facts) or execution["extra"] or not execution["judge_complete"]):
                problems.append(f"gold coverage execution failed: {name}/{label_name}")
            expected_batches = manifest["expectations"]["per_text"][name][
                "baseline" if label_name == "baseline" else "candidate_20"]
            if len(batches) != expected_batches:
                problems.append(f"batch expectation mismatch: {name}/{label_name}")
        matched = entry["candidate"]["execution"]["gold_covered"]
        entry["gold"] = {"total": len(facts), "covered": matched}
        if facts and matched != len(facts):
            problems.append(f"gold coverage failure: {name} {matched}/{len(facts)}")
        entry["baseline_batches"] = entry["baseline"]["batches"]
        entry["candidate_batches"] = entry["candidate"]["batches"]
        result["texts"][name] = entry
    totals = {
        "texts": len(result["texts"]),
        "baseline_batches": sum(item["baseline_batches"] for item in result["texts"].values()),
        "candidate_batches": sum(item["candidate_batches"] for item in result["texts"].values()),
        "gold_total": sum(item["gold"]["total"] for item in result["texts"].values()),
        "gold_covered": sum(item["gold"]["covered"] for item in result["texts"].values()),
    }
    result["totals"] = totals
    for field, expectation in (("baseline_batches", "baseline_batches"),
                               ("candidate_batches", "candidate_batches_20"), ("gold_total", "gold_total")):
        if totals[field] != manifest["expectations"][expectation]:
            problems.append(f"expectation mismatch: {field}")
    result["gates"] = {
        "fixture_hash_gate": "PASS" if not any("hash mismatch" in p for p in problems) else "FAIL",
        "partition_gate": "PASS" if not any("partition" in p for p in problems) else "FAIL",
        "gold_coverage_gate": "PASS" if not any("gold coverage" in p for p in problems) else "FAIL",
        "expectation_gate": "PASS" if not any("expectation" in p for p in problems) else "FAIL",
        "quality_gate": "NOT_RUN_OFFLINE",
        "live_gate": "NOT_RUN",
    }
    result["problems"] = problems
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
    parser.add_argument("--output", default="")
    parser.add_argument("--historical-manifest", default="")
    args = parser.parse_args(argv)
    try:
        if args.output and Path(args.output).exists():
            raise FileExistsError('output exists; refusing overwrite')
        result = evaluate(Path(args.manifest))
        if args.historical_manifest:
            result['historical'] = (replay_historical(args.historical_manifest)
                if Path(args.historical_manifest).exists() else {'status':'SKIP_SOURCE_UNAVAILABLE'})
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True,exist_ok=True)
            with output.open('x',encoding='utf-8') as handle:
                json.dump(result,handle,ensure_ascii=False,indent=2)
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    failed = [key for key, value in result["gates"].items() if value == "FAIL"]
    print(json.dumps({"totals": result["totals"], "gates": result["gates"],
                      "problems": result["problems"]}, ensure_ascii=False))
    return 1 if failed or result["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
