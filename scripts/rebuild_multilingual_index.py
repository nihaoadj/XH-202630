"""Provision one pinned dense model and build an isolated SQLite/Chroma snapshot.

Never activates configuration or deletes the source database/index. Run audit in
a new process before changing .env. Reports contain no credentials/user text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
sys.path.insert(0, str(BACKEND))
MODEL_ID = 'BAAI/bge-m3'
MODEL_REVISION = '5617a9f61b028005a4858fdac845db406aefb181'
IDENTITY_REVISION = 'layout-v1-teaching-v2-m3-20261027'
MODEL_DIR = BACKEND / 'data/models/bge-m3' / MODEL_REVISION
TARGET_DB = BACKEND / 'data/domain_knowledge_m3.db'
TARGET_VECTORS = BACKEND / 'data/chroma_bge_m3'
REPORTS = ROOT / 'output/test-runs/kb-m3'
KB = ROOT / 'knowledge_base/rag_engineering_training'
KB_ID = 'rag_engineering_training'
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


def sql_snapshot(path):
    """Hash complete old rows, never serialize learner data into a report."""
    with _readonly(path) as connection:
        tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts, business = {}, {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            counts[table] = connection.execute(f'SELECT COUNT(*) FROM {quoted}').fetchone()[0]
            # knowledge_states/mutations belong to learners, not the catalog.
            if table in CATALOG_TABLES or table == 'schema_migrations':
                continue
            rows = sorted(json.dumps(list(row), ensure_ascii=False, default=str) for row in connection.execute(f'SELECT * FROM {quoted}'))
            business[table] = hashlib.sha256('\n'.join(rows).encode()).hexdigest()
        history = {}
        for table, primary, mutable in [('knowledge_document_versions', 'document_version', 'is_current'),
                                        ('knowledge_chunk_versions', 'chunk_id', 'active')]:
            cols = [r[1] for r in connection.execute(f'PRAGMA table_info({table})') if r[1] not in {mutable, 'identity_revision'}]
            names = ','.join('"' + c + '"' for c in cols)
            history[table] = {'columns': cols, 'primary': primary, 'rows': {
                str(row[cols.index(primary)]): hashlib.sha256(json.dumps(list(row), ensure_ascii=False, default=str).encode()).hexdigest()
                for row in connection.execute(f'SELECT {names} FROM {table}')}}
        return {'counts': counts, 'business_hashes': business, 'history': history}


def _check_history(before, target):
    with _readonly(target) as connection:
        for table, expected in before['history'].items():
            names = ','.join('"' + c + '"' for c in expected['columns'])
            actual = {str(row[expected['columns'].index(expected['primary'])]):
                      hashlib.sha256(json.dumps(list(row), ensure_ascii=False, default=str).encode()).hexdigest()
                      for row in connection.execute(f'SELECT {names} FROM {table}')}
            if any(actual.get(key) != digest for key, digest in expected['rows'].items()):
                raise ValueError('IMMUTABLE_HISTORY_CHANGED:' + table)
    after = sql_snapshot(target)
    if any(after['business_hashes'].get(table) != digest for table, digest in before['business_hashes'].items()):
        raise ValueError('NON_KNOWLEDGE_BUSINESS_DATA_CHANGED')


def _chunks():
    from app.core.retrieval.knowledge_base import load_documents, chunk_documents, load_metadata
    if load_metadata(str(KB)).get('document_identity_revision') != IDENTITY_REVISION:
        raise ValueError('MANIFEST_IDENTITY_REVISION_MISMATCH')
    docs = load_documents(str(KB))
    chunks = chunk_documents(docs)
    if len(docs) != 62 or len(chunks) != 3222:
        raise ValueError('SNAPSHOT_COUNTS_UNEXPECTED')
    return docs, chunks


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
    # Avoid racing a local server/worker. No unrelated process is terminated.
    import psutil
    for process in psutil.process_iter(['pid', 'name', 'cmdline']):
        if process.pid == os.getpid():
            continue
        try:
            command = ' '.join(process.info['cmdline'] or [])
            if str(ROOT).lower() in command.lower() and any(x in command for x in ['uvicorn', 'resource_worker', 'courseware_worker']):
                raise ValueError('STOP_PROJECT_WEB_AND_WORKERS_BEFORE_BUILD')
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
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
    result = service.ingest(str(KB)).model_dump(mode='json')
    result.update(source_database=str(source), target_database=str(TARGET_DB),
                  target_vectors=str(TARGET_VECTORS), model_id=MODEL_ID, model_revision=MODEL_REVISION,
                  identity_revision=IDENTITY_REVISION, manifest_sha256=sha_file(KB / 'metadata.json'))
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
    if result['model_revision'] != MODEL_REVISION or result['identity_revision'] != IDENTITY_REVISION:
        raise ValueError('BUILD_MODEL_OR_IDENTITY_MISMATCH')
    configure_shadow()
    _, chunks = _chunks()
    _check_history(read_report('source-before.json'), TARGET_DB)
    if sql_snapshot(result['source_database'])['business_hashes'] != sql_snapshot(TARGET_DB)['business_hashes']:
        raise ValueError('SOURCE_AND_SHADOW_BUSINESS_DATA_MISMATCH')
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
