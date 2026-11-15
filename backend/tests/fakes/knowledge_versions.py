"""Project current source bodies into their explicitly historical identity epoch.

Only for comparing retained pre-rebuild fixtures. Current identities must also
be checked separately; this must never be used by ingestion/runtime code.
"""
from copy import deepcopy
from contextlib import contextmanager

from app.core.retrieval.knowledge_ids import document_version_id


def without_identity_revision(documents):
    projected = deepcopy(documents)
    for document in projected:
        metadata = document.metadata
        metadata.pop('document_identity_revision', None)
        metadata['document_version'] = document_version_id(
            metadata['knowledge_base_id'], metadata['document_id'], metadata['document_content_hash'],
        )
    return projected


@contextmanager
def source_baseline():
    """Reconstruct T24 input when comparing retained pre-cleaning fixtures."""
    from scripts.knowledge_layout import KB
    from scripts.knowledge_corpus_promotion import DESCRIPTOR, reconstructed_base
    if (KB / "provenance/evidence-base/manifest.json").is_file():
        from scripts.evidence_corpus_promotion import reconstructed_previous
        with reconstructed_previous(KB) as old, reconstructed_base(old) as base:
            yield base
        return
    if (KB / DESCRIPTOR).is_file():
        with reconstructed_base(KB) as base:
            yield base
    else:
        yield KB


@contextmanager
def pre_evidence_corpus():
    """T26 sources for retained 3177/126 historical chunk fixtures."""
    from scripts.knowledge_layout import KB
    if (KB / "provenance/evidence-base/manifest.json").is_file():
        from scripts.evidence_corpus_promotion import reconstructed_previous
        with reconstructed_previous(KB) as base:
            yield base
    else:
        yield KB
