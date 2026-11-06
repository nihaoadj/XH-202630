"""Pinned corpus and maintenance safety contracts; no model or real data writes."""
from copy import deepcopy
import json
import os
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import psutil
import pytest

from app.core.retrieval import knowledge_base
from scripts import rebuild_multilingual_index as rebuild


@pytest.fixture(scope="module")
def corpus():
    docs = knowledge_base.load_documents(str(rebuild.KB))
    chunking = knowledge_base.load_metadata(str(rebuild.KB))['chunking']
    return docs, knowledge_base.chunk_documents(docs, chunk_size=chunking['chunk_size'],
                                               chunk_overlap=chunking['chunk_overlap'])


def test_active_evidence_snapshot_is_accepted_without_changing_source_files(corpus):
    docs, chunks = rebuild._chunks()
    assert (len(docs), len(chunks)) == (62, 1121)
    assert rebuild._snapshot_profile()['identity_revision'] == rebuild.EVIDENCE_IDENTITY_REVISION
    assert [item.metadata['chunk_id'] for item in chunks] == [item.metadata['chunk_id'] for item in corpus[1]]


def test_script_entrypoint_can_verify_snapshot_without_external_pythonpath():
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    result = subprocess.run([
        sys.executable, '-X', 'utf8', '-c',
        "import runpy; module=runpy.run_path('scripts/rebuild_multilingual_index.py', run_name='entrypoint_probe'); "
        "docs,chunks=module['_chunks'](); print(len(docs),len(chunks))",
    ], cwd=rebuild.ROOT, env=environment, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '62 1121'


@pytest.mark.parametrize('drift', ['count', 'text', 'metadata'])
def test_active_snapshot_rejects_count_text_and_metadata_drift(monkeypatch, corpus, drift):
    docs, chunks = corpus
    changed = deepcopy(chunks)
    if drift == 'count':
        changed.pop()
    elif drift == 'text':
        changed[0].page_content += '\nSYNTHETIC_DRIFT'
    else:
        changed[0].metadata['title'] = 'SYNTHETIC_DRIFT'
    monkeypatch.setattr(knowledge_base, 'load_documents', lambda _: docs)
    monkeypatch.setattr(knowledge_base, 'chunk_documents', lambda _, **kwargs: changed)
    with pytest.raises(ValueError, match='SNAPSHOT_COUNTS_UNEXPECTED|SNAPSHOT_HASH_UNEXPECTED'):
        rebuild._chunks()


def test_unknown_identity_is_rejected_and_legacy_profile_remains_supported(monkeypatch):
    monkeypatch.setattr(knowledge_base, 'load_metadata', lambda _: {'document_identity_revision': 'unknown-v99'})
    with pytest.raises(ValueError, match='MANIFEST_IDENTITY_REVISION_MISMATCH'):
        rebuild._chunks()
    monkeypatch.setattr(knowledge_base, 'load_metadata', lambda _: {'document_identity_revision': rebuild.IDENTITY_REVISION})
    profile = rebuild._snapshot_profile()
    assert (profile['document_count'], profile['chunk_count']) == (62, 3222)


def test_missing_fixture_hash_cannot_silently_disable_verification(monkeypatch, tmp_path):
    fixture = json.loads(rebuild.EVIDENCE_FIXTURE.read_text(encoding='utf-8'))
    fixture.pop('full_snapshot_sha256')
    path = tmp_path / 'fixture.json'
    path.write_text(json.dumps(fixture), encoding='utf-8')
    monkeypatch.setattr(rebuild, 'EVIDENCE_FIXTURE', path)
    with pytest.raises(ValueError, match='EVIDENCE_SNAPSHOT_FIXTURE_MISMATCH'):
        rebuild._chunks()


@pytest.fixture
def idle_source(monkeypatch, tmp_path):
    path = tmp_path / 'source.db'
    with sqlite3.connect(path) as connection:
        for table in ('generation_jobs', 'agent_runs', 'courseware_generation_jobs'):
            connection.execute(f'CREATE TABLE {table} (status TEXT)')
            connection.execute(f"INSERT INTO {table} VALUES ('completed')")
        connection.execute('CREATE TABLE courseware_outbox (status TEXT, delivered_at TEXT)')
    monkeypatch.setattr(psutil, 'process_iter', lambda _: [])

    monkeypatch.setattr(psutil, 'net_connections', lambda kind: [])
    return path


@pytest.mark.parametrize('role', ['uvicorn', 'generation_worker.py', 'courseware_worker.py'])
def test_relative_project_writer_processes_are_rejected(monkeypatch, idle_source, role):
    writer = SimpleNamespace(pid=99999999, info={
        'name': 'python.exe', 'cmdline': ['python', role], 'cwd': str(rebuild.ROOT / 'backend'),
    })
    monkeypatch.setattr(psutil, 'process_iter', lambda _: [writer])
    with pytest.raises(ValueError, match='STOP_PROJECT_WEB_AND_WORKERS_BEFORE_BUILD'):
        rebuild.ensure_project_idle(idle_source)


def test_inspection_shell_and_unrelated_python_service_are_not_project_writers(monkeypatch, idle_source, tmp_path):
    project = tmp_path / 'project'
    monkeypatch.setattr(rebuild, 'ROOT', project)
    processes = [
        SimpleNamespace(pid=99999998, info={'name': 'pwsh.exe', 'cmdline': ['pwsh', 'inspect generation_worker.py'], 'cwd': str(project)}),
        SimpleNamespace(pid=99999999, info={'name': 'python.exe', 'cmdline': ['python', '-m', 'uvicorn'], 'cwd': str(tmp_path / 'unrelated')}),
    ]
    monkeypatch.setattr(psutil, 'process_iter', lambda _: processes)
    rebuild.ensure_project_idle(idle_source)


def test_unconfirmed_service_ownership_is_not_treated_as_idle(monkeypatch, idle_source):
    process = SimpleNamespace(pid=99999999, info={'name': 'python.exe', 'cmdline': ['python', 'generation_worker.py'], 'cwd': None})
    monkeypatch.setattr(psutil, 'process_iter', lambda _: [process])
    with pytest.raises(ValueError, match='PROJECT_PROCESS_OWNERSHIP_UNCONFIRMED'):
        rebuild.ensure_project_idle(idle_source)


@pytest.mark.parametrize('table,status', [('generation_jobs', 'queued'), ('agent_runs', 'created'), ('agent_runs', 'finalizing'), ('courseware_generation_jobs', 'running')])
def test_inflight_database_work_is_rejected(idle_source, table, status):
    with sqlite3.connect(idle_source) as connection:
        connection.execute(f'INSERT INTO {table} VALUES (?)', (status,))
    with pytest.raises(ValueError, match='ACTIVE_GENERATION_EXISTS_BEFORE_BUILD'):
        rebuild.ensure_project_idle(idle_source)


def test_unreadable_python_command_line_blocks_maintenance(monkeypatch, idle_source):
    process = SimpleNamespace(pid=99999999, info={'name': 'python.exe', 'cmdline': None, 'cwd': str(rebuild.ROOT)})
    monkeypatch.setattr(psutil, 'process_iter', lambda _: [process])
    with pytest.raises(ValueError, match='PROJECT_PROCESS_OWNERSHIP_UNCONFIRMED'):
        rebuild.ensure_project_idle(idle_source)


@pytest.mark.parametrize('status', ['queued', 'retry', 'claimed'])
def test_undelivered_outbox_work_blocks_maintenance(idle_source, status):
    with sqlite3.connect(idle_source) as connection:
        connection.execute('INSERT INTO courseware_outbox VALUES (?, NULL)', (status,))
    with pytest.raises(ValueError, match='ACTIVE_GENERATION_EXISTS_BEFORE_BUILD'):
        rebuild.ensure_project_idle(idle_source)


@pytest.mark.parametrize('port', [8000, 8081, 8082])
def test_project_health_listeners_block_maintenance(monkeypatch, idle_source, port):
    listener = SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=port))
    monkeypatch.setattr(psutil, 'net_connections', lambda kind: [listener])
    with pytest.raises(ValueError, match='STOP_PROJECT_WEB_AND_WORKERS_BEFORE_BUILD'):
        rebuild.ensure_project_idle(idle_source)


def test_unreadable_system_listener_table_does_not_mean_idle(monkeypatch, idle_source):
    def denied(kind):
        raise psutil.AccessDenied()

    monkeypatch.setattr(psutil, 'net_connections', denied)
    with pytest.raises(ValueError, match='PROJECT_PORT_STATE_UNCONFIRMED'):
        rebuild.ensure_project_idle(idle_source)


def test_frontend_listener_does_not_block_database_maintenance(monkeypatch, idle_source):
    listener = SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=5173))
    monkeypatch.setattr(psutil, 'net_connections', lambda kind: [listener])
    rebuild.ensure_project_idle(idle_source)


@pytest.fixture
def audited_source(tmp_path):
    path = tmp_path / 'locked-source.db'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE users (id TEXT, value TEXT)')
        connection.execute("INSERT INTO users VALUES ('synthetic', 'unchanged')")
        connection.execute('CREATE TABLE knowledge_document_versions (document_version TEXT, is_current INTEGER)')
        connection.execute("INSERT INTO knowledge_document_versions VALUES ('v1', 1)")
        connection.execute('CREATE TABLE knowledge_chunk_versions (chunk_id TEXT, active INTEGER)')
        connection.execute("INSERT INTO knowledge_chunk_versions VALUES ('chunk1', 1)")
    return path


def test_final_snapshot_uses_the_locked_connection_without_releasing_its_transaction(monkeypatch, audited_source):
    path = audited_source
    before = rebuild.sql_snapshot(path)

    def independent_read_forbidden(_):
        raise AssertionError('The final snapshot must use the held SQLite connection')

    with sqlite3.connect(path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        monkeypatch.setattr(rebuild, '_readonly', independent_read_forbidden)
        assert rebuild.sql_snapshot(path, connection=connection) == before
        assert connection.in_transaction
        connection.rollback()


def test_additive_migration_preserves_every_original_business_column(audited_source, tmp_path):
    before = rebuild.sql_snapshot(audited_source)
    target = tmp_path / 'shadow.db'
    with sqlite3.connect(audited_source) as source, sqlite3.connect(target) as shadow:
        source.backup(shadow)
        shadow.execute("ALTER TABLE users ADD COLUMN dispatch_mode TEXT DEFAULT 'legacy'")
        shadow.execute('CREATE TABLE report_watermarks (epoch INTEGER)')
        shadow.execute('INSERT INTO report_watermarks VALUES (0)')
    rebuild._check_history(before, target)
    assert rebuild.sql_snapshot(target, business_columns=before['business_columns'])['business_hashes']['users'] == before['business_hashes']['users']


@pytest.mark.parametrize('mutation', [
    "UPDATE users SET value='changed'",
    "DELETE FROM users",
    "INSERT INTO users VALUES ('another', 'new')",
    'ALTER TABLE users DROP COLUMN value',
    'DROP TABLE users',
])
def test_business_projection_rejects_changes_or_loss_of_original_data(audited_source, tmp_path, mutation):
    before = rebuild.sql_snapshot(audited_source)
    target = tmp_path / 'shadow.db'
    with sqlite3.connect(audited_source) as source, sqlite3.connect(target) as shadow:
        source.backup(shadow)
        shadow.execute(mutation)
    with pytest.raises(ValueError, match='NON_KNOWLEDGE_BUSINESS_DATA_CHANGED|BUSINESS_COLUMN_MISSING|BUSINESS_TABLE_MISSING'):
        rebuild._check_history(before, target)


def test_legacy_receipt_without_an_independent_schema_baseline_is_rejected(audited_source):
    before = rebuild.sql_snapshot(audited_source)
    legacy = {key: value for key, value in before.items() if key != 'business_columns'}
    with pytest.raises(ValueError, match='SOURCE_SCHEMA_BASELINE_MISSING'):
        rebuild.verify_source_snapshot(legacy, audited_source)
    assert 'business_columns' not in legacy
    with sqlite3.connect(audited_source) as source:
        source.execute("UPDATE users SET value='concurrent-change'")
    with pytest.raises(ValueError, match='SOURCE_DATABASE_CHANGED_SINCE_BUILD'):
        rebuild.verify_source_snapshot(before, audited_source)


@pytest.mark.parametrize('mutation', [
    'ALTER TABLE unused_business ADD COLUMN extra TEXT',
    'ALTER TABLE users RENAME COLUMN value TO renamed_value',
])
def test_empty_table_or_equal_value_schema_drift_is_rejected(audited_source, mutation):
    with sqlite3.connect(audited_source) as source:
        source.execute('CREATE TABLE unused_business (original_column TEXT)')
    before = rebuild.sql_snapshot(audited_source)
    with sqlite3.connect(audited_source) as source:
        source.execute(mutation)
    with pytest.raises(ValueError, match='SOURCE_BUSINESS_COLUMNS_CHANGED|SOURCE_SCHEMA_CHANGED'):
        rebuild.verify_source_snapshot(before, audited_source)


@pytest.fixture
def source_with_report_watermark(audited_source):
    with sqlite3.connect(audited_source) as source:
        source.execute('CREATE TABLE report_read_watermarks (source TEXT, installation_id TEXT, protocol TEXT, epoch INTEGER)')
        source.execute("INSERT INTO report_read_watermarks VALUES ('global','installation-1','report-read/1',102)")
    return audited_source


@pytest.mark.parametrize('epoch,installation,accepted', [
    (103, 'installation-1', True), (0, 'installation-2', True), (101, 'installation-1', False),
])
def test_target_report_invalidation_may_advance_or_reset_only_with_new_identity(source_with_report_watermark, tmp_path, epoch, installation, accepted):
    before = rebuild.sql_snapshot(source_with_report_watermark)
    target = tmp_path / 'shadow.db'
    with sqlite3.connect(source_with_report_watermark) as source, sqlite3.connect(target) as shadow:
        source.backup(shadow)
        shadow.execute('UPDATE report_read_watermarks SET epoch=?, installation_id=?', (epoch, installation))
    if accepted:
        rebuild._check_history(before, target)
    else:
        with pytest.raises(ValueError, match='REPORT_WATERMARK_REGRESSED'):
            rebuild._check_history(before, target)


def test_source_report_invalidation_still_blocks_switch(source_with_report_watermark):
    before = rebuild.sql_snapshot(source_with_report_watermark)
    with sqlite3.connect(source_with_report_watermark) as source:
        source.execute('UPDATE report_read_watermarks SET epoch=epoch+1')
    with pytest.raises(ValueError, match='SOURCE_DATABASE_CHANGED_SINCE_BUILD'):
        rebuild.verify_source_snapshot(before, source_with_report_watermark)
