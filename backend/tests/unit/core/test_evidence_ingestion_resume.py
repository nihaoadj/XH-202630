"""Small data-only checks for accepting persisted interrupted vectors."""
import pytest

from scripts.refresh_cleaned_knowledge import validate_partial_vectors


def sample():
    old = {"old": ("old body", {"id": "old"})}
    new = {"new": ("new body", {"id": "new"})}
    data = {"ids": ["old", "new"], "documents": ["old body", "new body"],
            "metadatas": [{"id": "old"}, {"id": "new"}], "embeddings": [[0.1, 0.2], [0.3, 0.4]]}
    return data, old, new


def test_partial_vectors_preserve_old_and_reuse_only_exact_candidates():
    data, old, new = sample()
    assert validate_partial_vectors(data, old, new, dimensions=2) == {
        "validated_vectors": 2, "stable_candidates": 1, "expected_candidates": 1,
    }


@pytest.mark.parametrize("damage", ["unknown_id", "text", "metadata", "nan", "shape", "duplicate", "missing_column"])
def test_partial_vectors_reject_unsafe_or_unbound_content(damage):
    data, old, new = sample()
    if damage == "unknown_id":
        data["ids"][1] = "unknown"
    elif damage == "text":
        data["documents"][1] = "changed"
    elif damage == "metadata":
        data["metadatas"][1]["id"] = "wrong-node"
    elif damage == "nan":
        data["embeddings"][1][0] = float("nan")
    elif damage == "shape":
        data["embeddings"][1] = [0.1]
    elif damage == "duplicate":
        data["ids"][1] = "old"
    else:
        data["metadatas"].pop()
    with pytest.raises(ValueError):
        validate_partial_vectors(data, old, new, dimensions=2)


def test_same_identity_with_new_metadata_is_never_reused():
    data, old, _ = sample()
    with pytest.raises(ValueError, match="identity metadata conflict"):
        validate_partial_vectors(data, old, {"old": ("old body", {"id": "new"})}, dimensions=2)
