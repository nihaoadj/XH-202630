"""Pure composition; profile selection belongs to profiles.py."""

import hashlib
import json

from ..types import ReviewProfile, ReviewPromptBundle


def build_review_prompt(*, profile: ReviewProfile, enabled_specialties: tuple[str, ...] = ()) -> ReviewPromptBundle:
    allowed = {fragment.id: fragment for fragment in profile.allowed_specialties}
    if set(enabled_specialties) - set(allowed):
        raise ValueError("unknown review specialty")
    fragments = list(profile.fragments) + [allowed[key] for key in dict.fromkeys(enabled_specialties)]
    unique = {}
    for fragment in fragments:
        if fragment.id in unique and unique[fragment.id] != fragment:
            raise ValueError("conflicting review fragment definition")
        unique.setdefault(fragment.id, fragment)
    ordered = tuple(unique.values())
    system_text = "\n\n".join(fragment.text for fragment in ordered)
    material = {"resource_type": profile.resource_type, "phase": profile.phase, "version": profile.version,
                "schema": profile.output_schema.__name__, "role": profile.gateway_role,
                "fragments": [(f.id, f.version, f.text) for f in ordered], "system_text": system_text}
    fingerprint = hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")).encode("utf-8")).hexdigest()
    return ReviewPromptBundle(profile.resource_type, profile.phase, profile.version, system_text, ordered, fingerprint)
