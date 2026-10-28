"""Quality-qualified source diversity after SQL validation and deduplication."""
from dataclasses import dataclass
from collections import Counter
import hashlib
import json

VERSION = "source-balanced-global-v2"
TEACHING_LIMIT = 2
ORIGINAL_TARGET = 2
DOCUMENT_LIMIT = 2
RELEVANCE_GAP = 0.15


def config_payload():
    return {"version": VERSION, "teaching_limit": TEACHING_LIMIT, "original_target": ORIGINAL_TARGET,
            "document_limit": DOCUMENT_LIMIT, "relevance_gap": RELEVANCE_GAP,
            "budget": "min-global-max-and-top-k-times-query-count", "classification": "sql-path-manifest-v1"}


def source_catalog(knowledge_base_id):
    from app.core.retrieval.knowledge_base import load_knowledge_base_manifest, resolve_knowledge_base_dir_by_id
    try:
        manifest = load_knowledge_base_manifest(str(resolve_knowledge_base_dir_by_id(knowledge_base_id)))
        if manifest["knowledge_base_id"] != knowledge_base_id:
            raise ValueError("catalog scope mismatch")
        specs = {v["id"]: (v["file"], v.get("document_type")) for v in manifest["document_specs"].values()}
    except Exception:
        specs = {}
    return specs


def catalog_hash(specs):
    return hashlib.sha256(json.dumps(specs, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def source_role(document_id, path, specs):
    entry = specs.get(document_id)
    if not entry or entry[0] != path or not isinstance(path, str):
        return "unknown"
    parts = path.split("/")
    if any(p in {"", ".", ".."} for p in parts) or ":" in path or "\\" in path:
        return "unknown"
    if path.startswith("teaching/zh/") and document_id.startswith("module_"):
        return "teaching"
    if path.startswith(("references/en/", "references/zh/")) and entry[1] == "authoritative_original":
        return "original"
    return "unknown"


@dataclass(frozen=True)
class SourceCandidate:
    chunk_id: str
    document_id: str
    role: str
    relevance: float
    nodes: frozenset[str] = frozenset()


def select_sources(ranked, *, budget, nodes, minimum_score):
    """Input order is the existing selection order; never change any score."""
    if not ranked or budget <= 0:
        return [], {"version": VERSION, "selected_counts": {}, "relaxations": []}
    budget = min(budget, len(ranked))
    baseline = ranked[budget - 1].relevance  # Freeze BEFORE source reservations.
    original_floor = max(minimum_score, baseline - RELEVANCE_GAP)
    selected, doc_counts, role_counts = [], Counter(), Counter()
    pins = []

    def take(item):
        if item.chunk_id in selected or len(selected) >= budget:
            return False
        selected.append(item.chunk_id)
        doc_counts[item.document_id] += 1
        role_counts[item.role] += 1
        return True

    for node in nodes:
        if any(item.chunk_id in selected and node in item.nodes for item in ranked):
            continue
        item = next((v for v in ranked if node in v.nodes), None)
        if item and take(item):
            pins.append(item.chunk_id)
    for item in ranked:
        if role_counts["original"] >= min(ORIGINAL_TARGET, budget):
            break
        if item.role == "original" and item.relevance >= original_floor and doc_counts[item.document_id] < DOCUMENT_LIMIT:
            take(item)
    for relax in range(3):
        for item in ranked:
            if relax < 2 and item.relevance < original_floor:
                continue
            if relax == 0 and doc_counts[item.document_id] >= DOCUMENT_LIMIT:
                continue
            if relax == 0 and item.role == "teaching" and role_counts["teaching"] >= TEACHING_LIMIT:
                continue
            take(item)
        if len(selected) >= budget:
            break
    selected_set = set(selected)
    uncovered = [node for node in nodes if not any(v.chunk_id in selected_set and node in v.nodes for v in ranked)]
    return [v.chunk_id for v in ranked if v.chunk_id in selected_set], {
        "version": VERSION, "budget": budget, "baseline_relevance": baseline,
        "original_floor": original_floor, "selected_counts": dict(role_counts), "node_pins": pins,
        "uncovered_nodes": uncovered, "relaxations": [
            reason for condition, reason in ((role_counts["teaching"] > TEACHING_LIMIT, "teaching_limit"),
                (any(v > DOCUMENT_LIMIT for v in doc_counts.values()), "document_limit"),
                (any(v.chunk_id in selected_set and v.relevance < original_floor for v in ranked), "relative_floor_fill"),
                (role_counts["original"] < min(ORIGINAL_TARGET, budget), "original_shortfall")) if condition],
    }
