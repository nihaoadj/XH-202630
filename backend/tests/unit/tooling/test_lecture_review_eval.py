import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[3] / 'scripts/lecture_review_eval.py'
spec = importlib.util.spec_from_file_location('lecture_review_eval', PATH)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def test_manifest_runs_production_engine_without_network(monkeypatch, tmp_path):
    monkeypatch.setattr('socket.create_connection', lambda *a, **k: pytest.fail('offline attempted network'))
    output=tmp_path/'report.json'
    assert evaluation.main(['--mode','offline','--output',str(output)])==0
    result=json.loads(output.read_text(encoding='utf-8'))
    assert result['status']=='PASS' and len(result['results'])>=32
    assert result['real_model_quality']=='NOT_RUN_LIVE' and result['end_to_end']=='NOT_RUN'
    assert all(row['passed'] for row in result['results'])
    with pytest.raises(SystemExit) as error:
        evaluation.main(['--output',str(output)])
    assert error.value.code==2


def test_fixture_tamper_and_duplicate_case_fail_closed(tmp_path):
    data=json.loads(evaluation.DEFAULT_MANIFEST.read_text(encoding='utf-8'))
    data['cases'][0]['resource']['content_text']='modified'
    path=tmp_path/'bad.json';path.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError,match='hash'):
        evaluation.evaluate(path)
    data['cases'][0]=data['cases'][1]
    path.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError,match='duplicate'):
        evaluation.evaluate(path)
