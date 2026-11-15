"""Private correction dispatch envelope; inner historical hashes stay intact."""
from copy import deepcopy

from app.models.learning_documents.correction_package import parse_correction_generation_contract
from app.models.shared.persistence import canonical_hash

VERSION = "learning_documents.correction_json.v1"


def wrap_correction_dispatch(inner: dict, contract: dict) -> dict:
    if inner.get("workflow_version") == VERSION:
        raise ValueError("correction dispatch cannot be wrapped twice")
    value = {"workflow_version": VERSION, "inner_dispatch": deepcopy(inner),
             "correction_package_contract": parse_correction_generation_contract(contract).model_dump(mode="json")}
    return {**value, "correction_dispatch_hash": canonical_hash(value)}


def unwrap_correction_dispatch(snapshot: dict) -> tuple[dict, dict | None]:
    if snapshot.get("workflow_version") != VERSION:
        if {"inner_dispatch", "correction_package_contract", "correction_dispatch_hash"}.intersection(snapshot):
            raise ValueError("correction dispatch version missing")
        return deepcopy(snapshot), None
    expected = {"workflow_version", "inner_dispatch", "correction_package_contract", "correction_dispatch_hash"}
    if set(snapshot) != expected:
        raise ValueError("correction dispatch fields mismatch")
    body = {k: v for k, v in snapshot.items() if k != "correction_dispatch_hash"}
    if canonical_hash(body) != snapshot["correction_dispatch_hash"]:
        raise ValueError("correction dispatch hash mismatch")
    contract = parse_correction_generation_contract(snapshot["correction_package_contract"])
    inner = snapshot["inner_dispatch"]
    if not isinstance(inner, dict) or not inner.get("workflow_version") or inner.get("workflow_version") == VERSION:
        raise ValueError("invalid correction inner dispatch")
    return deepcopy(inner), contract.model_dump(mode="json")
