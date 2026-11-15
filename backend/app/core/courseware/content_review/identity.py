"""Stable content identity; accounting and timestamps never define approval."""
from app.models.courseware.content_review import json_hash


def design_projection(spec):
    return {k: spec.get(k) for k in ("learning_design", "design", "storyboard", "resource_bundle_snapshot")}


def content_identity(run_id, snapshot, design, inventory, evidence, policy, prompt_fingerprint):
    return json_hash({"run_id": run_id, "source": snapshot, "design": design,
                      "inventory": inventory.model_dump(mode="json"),
                      "evidence": evidence.model_dump(mode="json"),
                      "policy": policy.model_dump(mode="json"), "prompt": prompt_fingerprint})


def stage_content_hash(identity, stage, scenes=None):
    return json_hash({"identity": identity, "stage": stage,
                      "scenes": scenes if stage not in {"snapshot", "design"} else None})


def approval_identity(content_id, results, status):
    return json_hash({"content": content_id, "results": [r.model_dump(mode="json") for r in sorted(results, key=lambda r: r.item_id)],
                      "status": status, "template_version": "courseware-templates-v1"})
