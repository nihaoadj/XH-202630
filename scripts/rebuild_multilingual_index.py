"""Provision one pinned dense model and build an isolated SQLite/Chroma snapshot.

Never activates configuration or deletes the source database/index. Run audit in
a new process before changing .env. Reports contain no credentials/user text.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND))
MODEL_ID = 'BAAI/bge-m3'
MODEL_REVISION = '5617a9f61b028005a4858fdac845db406aefb181'
IDENTITY_REVISION = 'layout-v1-teaching-v2-m3-20261027'
EVIDENCE_IDENTITY_REVISION = IDENTITY_REVISION + '-evidence-v2'
MODEL_DIR = BACKEND / 'data/models/bge-m3' / MODEL_REVISION
TARGET_DB = BACKEND / 'data/domain_knowledge_m3.db'
TARGET_VECTORS = BACKEND / 'data/chroma_bge_m3'
REPORTS = ROOT / 'output/test-runs/kb-m3'
KB = ROOT / 'knowledge_base/rag_engineering_training'
KB_ID = 'rag_engineering_training'
EVIDENCE_FIXTURE = BACKEND / 'tests/fixtures/knowledge_pilot/evidence_units_v2.json'
MODEL_FILES = [
    'pytorch_model.bin', 'config.json', 'modules.json',
    'sentence_bert_config.json', 'config_sentence_transformers.json',
    'sentencepiece.bpe.model', 'tokenizer.json', 'tokenizer_config.json',
    'special_tokens_map.json', '1_Pooling/config.json', 'README.md',
]
CATALOG_TABLES = {
    'knowledge_bases', 'knowledge_documents', 'knowledge_document_versions',
    'knowledge_chunks', 'knowledge_chunk_versions', 'knowledge_index_status',
    'knowledge_chunk_skill_node_mappings', 'rag_skill_nodes', 'skill_node_relations',
}
REPORT_WATERMARK_TABLE = 'report_read_watermarks'


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def save_report(name, payload):
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def read_report(name):
    return json.loads((REPORTS / name).read_text(encoding='utf-8'))


def verify_model_receipt():
    receipt = read_report('model.json')
    if receipt['model_id'] != MODEL_ID or receipt['revision'] != MODEL_REVISION:
        raise ValueError('MODEL_RECEIPT_MISMATCH')
    if Path(receipt['directory']).resolve() != MODEL_DIR.resolve():
        raise ValueError('MODEL_DIRECTORY_MISMATCH')
    if set(receipt['files']) != set(MODEL_FILES):
        raise ValueError('MODEL_INVENTORY_MISMATCH')
    for name, expected in receipt['files'].items():
        if sha_file(MODEL_DIR / name) != expected:
            raise ValueError('MODEL_FILE_HASH_MISMATCH')
    return receipt


def prepare_model():
    os.environ['HF_HUB_DISABLE_XET'] = '1'
    from huggingface_hub import snapshot_download, get_hf_file_metadata, hf_hub_url
    print('Provisioning pinned dense model:', MODEL_ID, MODEL_REVISION, flush=True)
    snapshot_download(MODEL_ID, revision=MODEL_REVISION, local_dir=MODEL_DIR,
                      allow_patterns=MODEL_FILES, max_workers=4, etag_timeout=30)
    hashes = {name: sha_file(MODEL_DIR / name) for name in MODEL_FILES}
    # LFS ETag is the upstream SHA256, not a locally invented checksum.
    upstream = get_hf_file_metadata(hf_hub_url(MODEL_ID, 'pytorch_model.bin', revision=MODEL_REVISION), timeout=30).etag
    if hashes['pytorch_model.bin'] != upstream:
        raise ValueError('UPSTREAM_WEIGHT_HASH_MISMATCH')
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(min(8, os.cpu_count() or 1))
    model = SentenceTransformer(str(MODEL_DIR), device='cpu', local_files_only=True, trust_remote_code=False)
    vectors = model.encode(['检索增强生成需要证据。', 'Retrieval augmented generation needs evidence.'],
                           batch_size=2, normalize_embeddings=True)
    if vectors.shape != (2, 1024) or not np.isfinite(vectors).all():
        raise ValueError('MODEL_SHAPE_OR_VALUES_INVALID')
    if not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5):
        raise ValueError('MODEL_NORMALIZATION_INVALID')
    save_report('model.json', {'model_id': MODEL_ID, 'revision': MODEL_REVISION,
                'directory': str(MODEL_DIR), 'files': hashes, 'dimension': 1024,
                'max_seq_length': model.max_seq_length, 'mode': 'dense_only',
                'license': 'MIT per pinned official model card', 'smoke': 'passed'})
    print('Pinned local model verified; configuration has NOT been activated.', flush=True)


def reject_existing_targets(source, target_db=TARGET_DB, target_vectors=TARGET_VECTORS):
    source, target_db, target_vectors = map(lambda p: Path(p).resolve(), (source, target_db, target_vectors))
    if source == target_db or target_db.exists() or target_vectors.exists():
        raise ValueError('SHADOW_TARGET_MUST_BE_NEW')
    if not source.is_file():
        raise ValueError('SOURCE_DATABASE_MISSING')
    if not target_db.is_relative_to(BACKEND / 'data') or not target_vectors.is_relative_to(BACKEND / 'data'):
        raise ValueError('SHADOW_TARGET_OUTSIDE_DATA')


def configure_shadow():
    # These are process-local; do not touch .env or enable real LLM/reranker.
    os.environ.update(EMBEDDING_MODEL=str(MODEL_DIR), EMBEDDING_LOCAL_FILES_ONLY='true',
                      EMBEDDING_BATCH_SIZE='4', VECTOR_STORE_DIR=str(TARGET_VECTORS),
                      DATABASE_URL='sqlite:///' + TARGET_DB.as_posix(), RERANK_ENABLED='false',
                      RUN_LIVE_LLM='0', COURSEWARE_LIVE_EVAL='0', RUN_LIVE_RERANK='0')
    from app.config import get_settings
    get_settings.cache_clear()
    import torch
    torch.set_num_threads(min(8, os.cpu_count() or 1))


def _readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def sql_snapshot(path, *, connection=None, business_columns=None):
    """Hash complete old rows, never serialize learner data into a report."""
    with (_readonly(path) if connection is None else nullcontext(connection)) as connection:
        tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        schema_columns = {table: [row[1] for row in connection.execute(
            'PRAGMA table_info("' + table.replace('"', '""') + '")')] for table in tables}
        schema_records = connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        schema_hash = hashlib.sha256(json.dumps(schema_records, ensure_ascii=False).encode()).hexdigest()
        if business_columns is not None and set(business_columns) - set(tables):
            raise ValueError('BUSINESS_TABLE_MISSING')
        counts, business, columns_by_table = {}, {}, {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            counts[table] = connection.execute(f'SELECT COUNT(*) FROM {quoted}').fetchone()[0]
            # knowledge_states/mutations belong to learners, not the catalog.
            if table in CATALOG_TABLES or table == 'schema_migrations':
                continue
            available = schema_columns[table]
            selected = (business_columns or {}).get(table, available)
            if not selected or not set(selected) <= set(available):
                raise ValueError('BUSINESS_COLUMN_MISSING:' + table)
            columns_by_table[table] = selected
            projection = ','.join('"' + name.replace('"', '""') + '"' for name in selected)
            rows = sorted(json.dumps(list(row), ensure_ascii=False, default=str) for row in connection.execute(f'SELECT {projection} FROM {quoted}'))
            business[table] = hashlib.sha256('\n'.join(rows).encode()).hexdigest()
        history = {}
        for table, primary, mutable in [('knowledge_document_versions', 'document_version', 'is_current'),
                                        ('knowledge_chunk_versions', 'chunk_id', 'active')]:
            cols = [r[1] for r in connection.execute(f'PRAGMA table_info({table})') if r[1] not in {mutable, 'identity_revision'}]
            names = ','.join('"' + c + '"' for c in cols)
            history[table] = {'columns': cols, 'primary': primary, 'rows': {
                str(row[cols.index(primary)]): hashlib.sha256(json.dumps(list(row), ensure_ascii=False, default=str).encode()).hexdigest()
                for row in connection.execute(f'SELECT {names} FROM {table}')}}
        report_watermark = None
        if REPORT_WATERMARK_TABLE in tables:
            report_watermark = [list(row) for row in connection.execute(
                'SELECT source,installation_id,protocol,epoch FROM report_read_watermarks ORDER BY source')]
        return {'counts': counts, 'business_hashes': business, 'business_columns': columns_by_table,
                'schema_columns': schema_columns, 'schema_hash': schema_hash, 'history': history,
                'report_watermark': report_watermark}


def verify_source_snapshot(before, source, *, connection=None):
    """Reject source data/schema drift; legacy receipts need a proven schema baseline."""
    if any(key not in before for key in ('business_columns', 'schema_columns', 'schema_hash', 'report_watermark')):
        raise ValueError('SOURCE_SCHEMA_BASELINE_MISSING')
    current = sql_snapshot(source, connection=connection)
    if any(current[key] != before[key] for key in ('counts', 'business_hashes', 'history')):
        raise ValueError('SOURCE_DATABASE_CHANGED_SINCE_BUILD')
    if before['business_columns'] != current['business_columns']:
        raise ValueError('SOURCE_BUSINESS_COLUMNS_CHANGED')
    if before['schema_columns'] != current['schema_columns'] or before['schema_hash'] != current['schema_hash']:
        raise ValueError('SOURCE_SCHEMA_CHANGED')
    if before['report_watermark'] != current['report_watermark']:
        raise ValueError('SOURCE_DERIVED_STATE_CHANGED')
    return before


def _check_report_watermark(before, target):
    from app.db.reports.watermarks import PROTOCOL
    with _readonly(target) as connection:
        present = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (REPORT_WATERMARK_TABLE,)).fetchone()
        if not present:
            if REPORT_WATERMARK_TABLE in before['counts']:
                raise ValueError('REPORT_WATERMARK_MISSING')
            return
        rows = connection.execute('SELECT source,installation_id,protocol,epoch FROM report_read_watermarks').fetchall()
    if (len(rows) != 1 or rows[0][0] != 'global' or not rows[0][1]
            or rows[0][2] != PROTOCOL or not isinstance(rows[0][3], int) or rows[0][3] < 0):
        raise ValueError('REPORT_WATERMARK_INVALID')
    previous = before.get('report_watermark')
    if REPORT_WATERMARK_TABLE in before['counts'] and not previous:
        raise ValueError('SOURCE_DERIVED_BASELINE_MISSING')
    if previous and rows[0][1] == previous[0][1] and rows[0][3] < previous[0][3]:
        raise ValueError('REPORT_WATERMARK_REGRESSED')


def _check_history(before, target):
    with _readonly(target) as connection:
        for table, expected in before['history'].items():
            names = ','.join('"' + c + '"' for c in expected['columns'])
            actual = {str(row[expected['columns'].index(expected['primary'])]):
                      hashlib.sha256(json.dumps(list(row), ensure_ascii=False, default=str).encode()).hexdigest()
                      for row in connection.execute(f'SELECT {names} FROM {table}')}
            if any(actual.get(key) != digest for key, digest in expected['rows'].items()):
                raise ValueError('IMMUTABLE_HISTORY_CHANGED:' + table)
    after = sql_snapshot(target, business_columns=before.get('business_columns'))
    if any(after['business_hashes'].get(table) != digest for table, digest in before['business_hashes'].items()
           if table != REPORT_WATERMARK_TABLE):
        raise ValueError('NON_KNOWLEDGE_BUSINESS_DATA_CHANGED')
    _check_report_watermark(before, target)


def _snapshot_profile():
    from app.core.retrieval.knowledge_base import load_metadata
    revision = load_metadata(str(KB)).get('document_identity_revision')
    if revision == IDENTITY_REVISION:
        return {'identity_revision': revision, 'document_count': 62, 'chunk_count': 3222}
    if revision == EVIDENCE_IDENTITY_REVISION:
        fixture = json.loads(EVIDENCE_FIXTURE.read_text(encoding='utf-8'))
        digest = fixture.get('full_snapshot_sha256')
        if (fixture.get('identity_revision') != revision or fixture.get('document_count') != 62
                or fixture.get('chunk_count') != 1121 or not isinstance(digest, str)
                or len(digest) != 64 or any(value not in '0123456789abcdef' for value in digest)):
            raise ValueError('EVIDENCE_SNAPSHOT_FIXTURE_MISMATCH')
        return fixture
    raise ValueError('MANIFEST_IDENTITY_REVISION_MISMATCH')


def _chunks():
    from app.core.retrieval.knowledge_base import load_documents, chunk_documents, load_metadata
    profile = _snapshot_profile()
    chunking = load_metadata(str(KB)).get('chunking') or {}
    docs = load_documents(str(KB))
    chunks = chunk_documents(docs, chunk_size=int(chunking.get('chunk_size', 500)),
                             chunk_overlap=int(chunking.get('chunk_overlap', 100)))
    if len(docs) != profile['document_count'] or len(chunks) != profile['chunk_count']:
        raise ValueError('SNAPSHOT_COUNTS_UNEXPECTED')
    if 'full_snapshot_sha256' in profile:
        from scripts.prepare_evidence_chunks import digest_chunks
        if digest_chunks(chunks) != profile['full_snapshot_sha256']:
            raise ValueError('SNAPSHOT_HASH_UNEXPECTED')
    return docs, chunks


def ensure_project_idle(source):
    """Reject local writers, including relative-path text workers, before copying."""
    import psutil
    own_process = psutil.Process()
    excluded = {own_process.pid, *(parent.pid for parent in own_process.parents())}
    for process in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd']):
        if process.pid in excluded:
            continue
        try:
            info = process.info
            name = (info['name'] or '').lower()
            if name not in {'python', 'python.exe', 'pythonw.exe', 'uvicorn', 'uvicorn.exe'}:
                continue
            if not info['cmdline']:
                raise ValueError('PROJECT_PROCESS_OWNERSHIP_UNCONFIRMED')
            command = ' '.join(info['cmdline']).lower()
            if not any(role in command for role in ('uvicorn', 'generation_worker', 'resource_worker', 'courseware_worker')):
                continue
            cwd = info.get('cwd')
            if not cwd and str(ROOT).lower() not in command:
                raise ValueError('PROJECT_PROCESS_OWNERSHIP_UNCONFIRMED')
            if str(ROOT).lower() in command or (cwd and Path(cwd).resolve().is_relative_to(ROOT)):
                raise ValueError('STOP_PROJECT_WEB_AND_WORKERS_BEFORE_BUILD')
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as exc:
            raise ValueError('PROJECT_PROCESS_OWNERSHIP_UNCONFIRMED') from exc
    try:
        listeners = psutil.net_connections(kind='tcp')
    except (psutil.AccessDenied, OSError) as exc:
        raise ValueError('PROJECT_PORT_STATE_UNCONFIRMED') from exc
    if any(connection.status == psutil.CONN_LISTEN and connection.laddr.port in {8000, 8081, 8082}
           for connection in listeners):
        raise ValueError('STOP_PROJECT_WEB_AND_WORKERS_BEFORE_BUILD')
    with _readonly(source) as connection:
        queries = (
            "SELECT COUNT(*) FROM generation_jobs WHERE status IN ('queued','running')",
            "SELECT COUNT(*) FROM agent_runs WHERE status IN ('created','running','finalizing')",
            "SELECT COUNT(*) FROM courseware_generation_jobs WHERE status IN ('queued','running')",
            "SELECT COUNT(*) FROM courseware_outbox WHERE delivered_at IS NULL AND status IN ('queued','retry','claimed')",
        )
        if any(connection.execute(query).fetchone()[0] for query in queries):
            raise ValueError('ACTIVE_GENERATION_EXISTS_BEFORE_BUILD')


def build():
    verify_model_receipt()
    from app.config import get_settings, resolve_backend_path
    source_settings = get_settings()
    url = source_settings.database_url
    if not url.startswith('sqlite:///'):
        raise ValueError('REBUILD_REQUIRES_LOCAL_SQLITE')
    source = resolve_backend_path(url.removeprefix('sqlite:///'))
    reject_existing_targets(source)
    if source_settings.embedding_model != MODEL_ID and source.resolve() == TARGET_DB.resolve():
        raise ValueError('SOURCE_MUST_BE_OLD_DATABASE')
    ensure_project_idle(source)
    configure_shadow()
    docs, chunks = _chunks()
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR), local_files_only=True, trust_remote_code=False)
    lengths = [len(tokenizer.encode(c.page_content, truncation=False)) for c in chunks]
    length_report = {'max_tokens': max(lengths), 'over_8192': sum(n > 8192 for n in lengths),
                     'chunk_count': len(lengths)}
    save_report('lengths.json', length_report)
    if length_report['over_8192']:
        raise ValueError('CHUNKS_EXCEED_MODEL_LIMIT_REVIEW_BEFORE_BUILD')
    before = sql_snapshot(source)
    required = {'knowledge_bases', 'knowledge_document_versions', 'knowledge_chunk_versions',
                'knowledge_chunk_skill_node_mappings', 'rag_skill_nodes', 'schema_migrations'}
    if not required <= set(before['counts']):
        raise ValueError('SOURCE_SCHEMA_PREREQUISITES_MISSING')
    save_report('source-before.json', before)
    # Retain the complete pre-switch configuration without logging it.
    config_backup = REPORTS / 'backend.env.before'
    if config_backup.exists():
        raise ValueError('CONFIG_BACKUP_ALREADY_EXISTS')
    config_backup.write_bytes((BACKEND / '.env').read_bytes())
    TARGET_DB.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(TARGET_DB, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    with _readonly(source) as original, sqlite3.connect(TARGET_DB) as shadow:
        original.backup(shadow)
    print('Shadow SQLite cloned; old database and vectors remain untouched.', flush=True)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.shared.database import configure_sqlite_foreign_keys
    from app.db.migrations.p0_34_knowledge_identity_revision import apply_p0_34_knowledge_identity_revision_migration
    from app.db.knowledge.catalog import KnowledgeCatalogRepository
    from app.services.knowledge.ingestion import IngestionService, ChromaKnowledgeVectorIndex
    engine = configure_sqlite_foreign_keys(create_engine('sqlite:///' + TARGET_DB.as_posix()))
    apply_p0_34_knowledge_identity_revision_migration(engine)
    catalog = KnowledgeCatalogRepository(sessionmaker(bind=engine))
    service = IngestionService(catalog=catalog, vector_index=ChromaKnowledgeVectorIndex())
    print('Encoding', len(chunks), 'chunks with pinned multilingual dense model; batch=4.', flush=True)
    from app.core.retrieval.embeddings import get_embeddings
    get_embeddings().show_progress = True
    result = service.ingest(str(KB)).model_dump(mode='json')
    result.update(source_database=str(source), target_database=str(TARGET_DB),
                  target_vectors=str(TARGET_VECTORS), model_id=MODEL_ID, model_revision=MODEL_REVISION,
                  identity_revision=_snapshot_profile()['identity_revision'], manifest_sha256=sha_file(KB / 'metadata.json'))
    save_report('build.json', result)
    engine.dispose()
    if result['status'] != 'ready':
        raise ValueError('SHADOW_BUILD_NOT_READY_SEE_BUILD_REPORT')
    _check_history(before, TARGET_DB)
    if sql_snapshot(source) != before:
        raise ValueError('SOURCE_DATABASE_CHANGED_DURING_BUILD')
    print('Shadow build ready. Run audit in a NEW process; .env is unchanged.', flush=True)


def audit():
    verify_model_receipt()
    result = read_report('build.json')
    if result['status'] != 'ready' or result['manifest_sha256'] != sha_file(KB / 'metadata.json'):
        raise ValueError('BUILD_REPORT_OR_MANIFEST_MISMATCH')
    if (result['model_revision'] != MODEL_REVISION
            or result['identity_revision'] != _snapshot_profile()['identity_revision']):
        raise ValueError('BUILD_MODEL_OR_IDENTITY_MISMATCH')
    ensure_project_idle(result['source_database'])
    configure_shadow()
    _, chunks = _chunks()
    before = verify_source_snapshot(read_report('source-before.json'), result['source_database'])
    _check_history(before, TARGET_DB)
    from app.core.retrieval.vector_store import get_vector_store, _to_chroma_document
    store = get_vector_store(KB_ID)
    data = store.get(include=['documents', 'metadatas', 'embeddings'])
    import numpy as np
    embeddings = np.asarray(data['embeddings'])
    if embeddings.shape != (len(chunks), 1024) or not np.isfinite(embeddings).all():
        raise ValueError('STORED_VECTOR_SHAPE_OR_VALUES_INVALID')
    if not np.allclose(np.linalg.norm(embeddings, axis=1), 1, atol=1e-4):
        raise ValueError('STORED_VECTOR_NORMALIZATION_INVALID')
    vectors = {ident: (text, meta) for ident, text, meta in zip(data['ids'], data['documents'], data['metadatas'])}
    expected = {c.metadata['chunk_id']: c for c in chunks}
    if set(vectors) != set(expected):
        raise ValueError('VECTOR_ID_SET_MISMATCH')
    for ident, chunk in expected.items():
        projected = _to_chroma_document(chunk)
        if vectors[ident] != (projected.page_content, projected.metadata):
            raise ValueError('VECTOR_TEXT_OR_FULL_METADATA_MISMATCH')
    with _readonly(TARGET_DB) as connection:
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or connection.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('SQL_INTEGRITY_FAILED')
        sql_rows = {r[0]: (r[1], json.loads(r[2])) for r in connection.execute(
            'SELECT chunk_id, content, metadata FROM knowledge_chunk_versions WHERE knowledge_base_id=? AND active=1', (KB_ID,))}
        if set(sql_rows) != set(expected) or any(sql_rows[k] != (c.page_content, c.metadata) for k, c in expected.items()):
            raise ValueError('SQL_ID_TEXT_OR_FULL_METADATA_MISMATCH')
        node_count = connection.execute('SELECT COUNT(DISTINCT m.skill_node_id) FROM knowledge_chunk_skill_node_mappings m JOIN knowledge_chunk_versions c ON c.chunk_id=m.chunk_id WHERE c.active=1 AND c.knowledge_base_id=?', (KB_ID,)).fetchone()[0]
        if node_count != 13:
            raise ValueError('SKILL_NODE_COVERAGE_MISMATCH')
        from app.db.reports.watermarks import INDEXES, expected_triggers
        triggers = dict(connection.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_report_%'"))
        if any(triggers.get(name) != definition for name, definition in expected_triggers().items()):
            raise ValueError('REPORT_INVALIDATION_TRIGGER_MISMATCH')
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        if set(INDEXES) - indexes:
            raise ValueError('REPORT_READ_INDEX_MISSING')
    # Deliberately dense-only: no CrossEncoder or generation model is loaded.
    queries = [
        ('中文问题和英文资料的非对称语义检索，encode_query与encode_document有什么区别？', ['source_sbert_semantic_search']),
        ('Cross-Encoder为什么只能重排已经召回的候选？', ['source_sbert_retrieve_rerank', 'module_hybrid_rerank']),
        ('RAG中的假设文档HyDE为什么不能当作最终事实证据？', ['source_paper_hyde', 'module_hybrid_rerank']),
        ('MinerU中间JSON的page_idx从0还是1开始？', ['source_zh_mineru_output', 'module_ingestion_chunking']),
        ('rag-lab-v2的Q4中HitRate与Recall有什么区别？', ['module_evaluation_tuning']),
        ('rag-lab-v2中500字符100重叠是不是所有资料的最佳参数？', ['module_ingestion_chunking', 'module_rag_foundations']),
    ]
    smoke = []
    english_ids = sorted({c.metadata['document_id'] for c in chunks
                          if c.metadata['document_id'].startswith('source_')
                          and not c.metadata['document_id'].startswith('source_zh_')})
    for index, (query, targets) in enumerate(queries):
        # Restrict cross-language probes to the English corpus explicitly;
        # otherwise a good Chinese translation can mask the tested direction.
        where = {'document_id': {'$in': english_ids}} if index < 3 else None
        hits = store.similarity_search_with_score(query, k=10, filter=where)
        identifiers = [d.metadata['document_id'] for d, _ in hits]
        smoke.append({'query': query, 'scope': 'english_official_only' if where else 'full_corpus',
                      'expected_document_ids': targets,
                      'hit_document_ids': identifiers, 'passed': bool(set(targets) & set(identifiers))})
    report = {'status': 'passed' if all(q['passed'] for q in smoke) else 'failed',
              'chunk_count': len(chunks), 'covered_skill_nodes': node_count,
              'exact_sql_vector_text_metadata': 'passed', 'history_business_data': 'passed',
              'integrity': 'passed', 'new_process_dense_queries': smoke,
              'model_id': MODEL_ID, 'model_revision': MODEL_REVISION,
              'manifest_sha256': sha_file(KB / 'metadata.json'),
              'scope': 'small smoke, not benchmark or threshold calibration; no LLM/reranker'}
    save_report('audit.json', report)
    if report['status'] != 'passed':
        raise ValueError('DENSE_SMOKE_FAILED_SEE_AUDIT_REPORT')
    print('New-process exact SQL/vector audit and six dense queries passed; .env remains unchanged.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare-model', 'build', 'audit'])
    args = parser.parse_args()
    if args.command == 'prepare-model':
        prepare_model()
    elif args.command == 'build':
        build()
    else:
        audit()


if __name__ == '__main__':
    main()
