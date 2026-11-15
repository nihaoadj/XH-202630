"""T37 offline density diagnostics must be real, non-overwriting and provider-free."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/claim_density_eval.py"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "claim_extraction" / "density_v1"
MANIFEST = FIXTURES / "manifest.json"


def load():
    spec = importlib.util.spec_from_file_location("claim_density_eval_t37", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_evaluation_uses_production_planner_without_provider(monkeypatch):
    import socket
    import app.config

    def forbidden(*args, **kwargs):
        raise AssertionError("offline density evaluation touched network/environment")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(app.config, "get_settings", forbidden)
    result = load().evaluate(MANIFEST)
    assert result["totals"]["baseline_batches"] == 8
    assert result["totals"]["candidate_batches"] == 12
    assert result["totals"]["gold_total"] == 7
    assert result["totals"]["gold_covered"] == 7
    assert result["gates"]["fixture_hash_gate"] == "PASS"
    assert result["gates"]["partition_gate"] == "PASS"
    assert result["gates"]["gold_coverage_gate"] == "PASS"
    assert result["gates"]["quality_gate"] == "NOT_RUN_OFFLINE"
    assert result["problems"] == []
    assert "batching.py" in " ".join(result["sources"])


def test_evaluation_refuses_to_overwrite_existing_evidence(tmp_path):
    output = tmp_path / "density.json"
    output.write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError):
        load().evaluate(MANIFEST, output)


def test_missing_manifest_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        load().evaluate(tmp_path / "absent.json")


def test_text_hash_mismatch_fails_the_fixture_gate(tmp_path):
    module = load()
    source = FIXTURES
    target = tmp_path / "density"
    for name in ("texts", "labels", "policies"):
        (target / name).mkdir(parents=True)
        for item in (source / name).iterdir():
            (target / name / item.name).write_bytes(item.read_bytes())
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    manifest["texts"]["t01_paragraphs"]["sha256"] = "0" * 64
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = module.evaluate(target / "manifest.json")
    assert result["gates"]["fixture_hash_gate"] == "FAIL"
    assert any("hash mismatch" in problem for problem in result["problems"])


def test_each_text_reports_per_batch_risk_and_prediction():
    result = load().evaluate(MANIFEST)
    mixed = result["texts"]["t08_mixed"]
    assert mixed["candidate"]["batches"] == 2
    assert [batch["risk_chars"] for batch in mixed["candidate"]["per_batch"]] == [494, 244]
    assert [batch["predicted_claims"] for batch in mixed["candidate"]["per_batch"]] == [14.11, 6.97]
    code = result["texts"]["t04_code"]
    assert code["candidate"]["batches"] == 1
    assert code["candidate"]["per_batch"][0]["risk_chars"] > 630


def test_manifest_expectations_are_actually_enforced(tmp_path):
    import shutil
    target = tmp_path / 'fixtures'
    shutil.copytree(FIXTURES, target)
    path = target / 'manifest.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    data['expectations']['candidate_batches_20'] = 999
    data['expectations']['gold_total'] = 999
    path.write_text(json.dumps(data), encoding='utf-8')
    result = load().evaluate(path)
    assert result['gates']['expectation_gate'] == 'FAIL'


def test_scripted_candidate_omission_fails_gold_gate(monkeypatch):
    module = load()
    original = module._scripted_replay
    monkeypatch.setattr(module, '_scripted_replay', lambda text, policy, facts:
        original(text, policy, facts, omit_fact_ids={f['fact_id'] for f in facts}))
    result = module.evaluate(MANIFEST)
    assert result['gates']['gold_coverage_gate'] == 'FAIL'
    assert result['totals']['gold_covered'] == 0


def test_persisted_policy_digest_is_checked(tmp_path):
    import shutil
    target = tmp_path / 'fixtures'
    shutil.copytree(FIXTURES, target)
    path = target / 'policies/estimate_2_0_baseline.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    data['batch_claims'] = 19
    path.write_text(json.dumps(data), encoding='utf-8')
    assert load().evaluate(target / 'manifest.json')['gates']['fixture_hash_gate'] == 'FAIL'


def test_missing_label_hash_is_rejected(tmp_path):
    import shutil
    target = tmp_path / 'fixtures'
    shutil.copytree(FIXTURES,target)
    path = target/'manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    del manifest['labels']['t01_paragraphs']['sha256']
    path.write_text(json.dumps(manifest),encoding='utf-8')
    with pytest.raises(ValueError,match='hash metadata missing'):
        load().evaluate(path)


def test_missing_used_policy_metadata_is_rejected(tmp_path):
    import shutil
    target = tmp_path/'fixtures'
    shutil.copytree(FIXTURES,target)
    path = target/'manifest.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    del data['policies']['baseline_estimate_2_0']
    path.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError,match='policy hash/path metadata missing'):
        load().evaluate(path)


def test_historical_replay_checks_artifacts_and_full_production_fits(tmp_path):
    import hashlib
    module = load()
    text_path = tmp_path/'text.md'
    text_path.write_bytes((FIXTURES/'texts/t08_mixed.md').read_bytes())
    policy_path = tmp_path/'policy.json'
    policy_path.write_text(module._policy(FIXTURES, True).model_dump_json(),encoding='utf-8')
    manifest = dict(schema_version='claim-density-historical-1.0',
        text=dict(path=text_path.name,sha256=hashlib.sha256(text_path.read_bytes()).hexdigest()),
        policy=dict(path=policy_path.name,sha256=hashlib.sha256(policy_path.read_bytes()).hexdigest()),
        resource=dict(resource_id='r',version=1,resource_type='讲义'),target_skill_nodes=['k'],
        expected=dict(baseline_batches=1,candidate_batches=2))
    path = tmp_path/'manifest.json'
    path.write_text(json.dumps(manifest),encoding='utf-8')
    report = module.replay_historical(path)
    assert report['baseline']['batches'] == 1 and report['candidate']['batches'] == 2
    text_path.write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError,match='hash mismatch'):
        module.replay_historical(path)
