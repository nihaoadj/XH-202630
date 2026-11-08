"""Pure prompt assembly: resolved profile in, messages out."""
from langchain_core.messages import HumanMessage, SystemMessage
from app.models.courseware.content_review import canonical_json, json_hash


def build_messages(profile, enabled_rules, payload):
    fragments = [f for f in profile.fragments if f.id.startswith("content.") or f.id in enabled_rules]
    system = "\n".join(f"[{f.id}@{f.version}] {f.text}" for f in fragments)
    return (SystemMessage(content=system), HumanMessage(content=canonical_json(payload)))


def fingerprint(profile):
    return json_hash({"id": profile.id, "version": profile.version, "schema": profile.schema.model_json_schema(),
                      "role": profile.role, "fragments": [(f.id, f.version, f.text) for f in profile.fragments]})
