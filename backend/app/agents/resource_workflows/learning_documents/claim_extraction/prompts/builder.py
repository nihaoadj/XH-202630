import json

from langchain_core.messages import HumanMessage, SystemMessage

from ..contracts import select_contract
from ..payloads import extraction_payload, extraction_payload_v2


def build_messages(text, resource, batch, policy, allowed_nodes):
    contract = select_contract(policy)
    prompt = contract.prompt
    payload = (extraction_payload_v2 if contract.is_v2 else extraction_payload)(
        text, resource, batch, policy, allowed_nodes)
    from ..resource_sources import build_source, GUIDANCE
    source = build_source(resource, policy)
    if source.snapshot and text != source.text:
        raise ValueError("structured extraction input source mismatch")
    from ..input_context import enabled as unified_enabled, add_plain_context
    if unified_enabled(policy):
        if source.snapshot and source.related_fields is not None:
            _unified_payload(payload, text, batch, source, policy, contract.is_v2)
            return [SystemMessage(content=prompt), HumanMessage(content=json.dumps(payload, ensure_ascii=False))]
        if source.snapshot is None:
            add_plain_context(payload, text, batch, policy, is_v2=contract.is_v2)
    if source.snapshot:
        from ..resource_sources import CHECKLIST_CONTEXT_PROMPT_VERSION, CHECKLIST_GUIDANCE
        if source.prompt_version == CHECKLIST_CONTEXT_PROMPT_VERSION:
            _checklist_payload(payload, text, batch, source, contract.is_v2)
            return [SystemMessage(content=prompt + "\n" + GUIDANCE + "\n" + CHECKLIST_GUIDANCE),
                    HumanMessage(content=json.dumps(payload, ensure_ascii=False))]
        from ..contextual_correction_sources import PROMPT_VERSION as contextual_marker, GUIDANCE as contextual_guidance
        if source.prompt_version == contextual_marker:
            _contextual_payload(payload, text, resource, batch, source, contract.is_v2)
            return [SystemMessage(content=prompt + "\n" + contextual_guidance),
                    HumanMessage(content=json.dumps(payload, ensure_ascii=False))]
        from ..correction_sources import PROMPT_VERSION, GUIDANCE as correction_guidance
        from ..filtered_correction_sources import PROMPT_VERSION as filtered_marker, GUIDANCE as filtered_guidance, related_context
        from ..compact_correction_sources import PROMPT_VERSION as compact_marker, GUIDANCE as compact_guidance
        prompt += "\n" + (compact_guidance if source.prompt_version == compact_marker else
                           filtered_guidance if source.prompt_version == filtered_marker else
                           correction_guidance if source.prompt_version == PROMPT_VERSION else GUIDANCE)
        fields = [f for f in source.fields if any(f["start"] < u.end and u.start < f["end"] for u in batch.units)]
        questions = {f.get("question") for f in fields if f.get("question")}
        # Field roles are data, not a second extraction target or evidence pool.
        payload["structured_context"] = {
            "version": source.snapshot["version"],
            "fields": [{"path": f["path"], "role": f["role"],
                        "text": text[max(f["start"], batch.units[0].start):min(f["end"], batch.units[-1].end)]}
                       for f in fields],
            "read_only_questions": [{"path": f["path"], "text": text[f["start"]:f["end"]]}
                                    for f in source.fields if f.get("question") in questions
                                    and f["role"] == "question_context"],
            "read_only_answer_keys": {q: source.snapshot["question_bindings"][q] for q in sorted(questions)},
        }
        if source.prompt_version in {filtered_marker, compact_marker}:
            payload["structured_context"]["read_only_related_fields"] = related_context(resource, source, fields)
    return [SystemMessage(content=prompt), HumanMessage(content=json.dumps(payload, ensure_ascii=False))]


def _unified_payload(payload, text, batch, source, policy, is_v2):
    fields = [f for f in source.fields if any(f['start'] < u.end and u.start < f['end'] for u in batch.units)]
    wanted = {p for f in fields for p in source.snapshot['context_bindings'].get(f['path'], [])}
    def fully_present(path):
        field = next((f for f in source.fields if f['path'] == path), None)
        if field is None:
            return False
        cursor = field['start']
        for u in sorted(batch.units, key=lambda u:u.start):
            if u.start > cursor:
                break
            cursor = max(cursor, u.end)
            if cursor >= field['end']:
                return True
        return False
    related = [f for f in source.related_fields if f['path'] in wanted and not fully_present(f['path'])]
    keys = {q:v for q,v in source.snapshot['question_bindings'].items()
            if any(f['path'].startswith(q+'.') for f in fields)}
    payload['structured_context'] = {
        'version':source.snapshot['version'],
        'unit_fields': [dict(unit_id=u.unit_id,path=f['path'],role=f['role'],
            field_start_in_unit=max(f['start'],u.start)-u.start,
            field_end_in_unit=min(f['end'],u.end)-u.start)
            for u in batch.units for f in fields if f['start'] < u.end and u.start < f['end']],
        'read_only_related_fields':related,'read_only_answer_keys':keys,
    }
    # Keep the same field's premise after an internal split. Unrelated previous
    # fields and synthetic path headings must not become anonymous background.
    from ..input_context import add_plain_context
    from app.core.llm.counting import CharacterEstimator
    counter = CharacterEstimator(policy.estimator_parameters)
    contexts = []
    limited = False
    remaining = policy.context_tokens
    for field in fields:
        if any(f['path'] == field['path'] for f in related):
            continue
        local = text[field['start']:field['end']]
        units = [u.model_copy(update={'start': max(u.start, field['start']) - field['start'],
                                     'end': min(u.end, field['end']) - field['start'],
                                     'required_context': [], 'context': []})
                 for u in batch.units if field['start'] < u.end and u.start < field['end']]
        # Local coordinates keep context inside this JSON field.
        context_batch = batch.model_copy(update={'units': units, 'context': []})
        local_payload = {}
        add_plain_context(local_payload, local, context_batch, policy,
                          is_v2=True, context_tokens=remaining)
        for value in local_payload['read_only_context']:
            contexts.append({'path': field['path'], 'role': field['role'], 'text': value})
            remaining -= counter.count_text(value)
        limited |= local_payload['context_status'] == 'budget_limited'
    payload['structured_context']['read_only_field_context'] = contexts
    payload['structured_context']['context_status'] = 'budget_limited' if limited else 'available'
    # Required table headers/code fences survive even when target text is split.
    required = sorted({(s.start,s.end) for u in batch.units for s in u.required_context
                       if not any(v.start <= s.start and s.end <= v.end for v in batch.units)})
    payload['read_only_context'] = [text[a:b] if is_v2 else
        {'context_start':a,'context_end':b,'text':text[a:b]} for a,b in required]


def _checklist_payload(payload, text, batch, source, is_v2):
    """Carry complete question dependencies across splits, once per field.

    These values clarify author intent; only target_units remain extractable.
    build_messages is also used by the executor's window/budget checks.
    """
    fields = [f for f in source.fields
              if any(f["start"] < u.end and u.start < f["end"] for u in batch.units)]
    questions = {f["question"] for f in fields if f.get("question")}
    background_roles = {"question_context", "exercise_proposition", "answer_proposition", "exercise_option"}

    def fully_targeted(field):
        cursor = field["start"]
        for unit in sorted(batch.units, key=lambda u: u.start):
            if unit.start > cursor:
                break
            if unit.end > cursor:
                cursor = unit.end
            if cursor >= field["end"]:
                return True
        return False

    related = [f for f in source.fields if f.get("question") in questions
               and f["role"] in background_roles
               and not fully_targeted(f)]
    payload["structured_context"] = {
        "version": source.prompt_version,
        "fields": [
            {**{k: f[k] for k in ("path", "role", "question") if k in f},
             "unit_id": u.unit_id, "field_start_in_unit": max(f["start"], u.start) - u.start,
             "field_end_in_unit": min(f["end"], u.end) - u.start}
            for u in batch.units for f in fields if f["start"] < u.end and u.start < f["end"]],
        "read_only_related_fields": [
            {"path": f["path"], "role": f["role"], "text": text[f["start"]:f["end"]]} for f in related],
        "read_only_answer_keys": {q: source.snapshot["question_bindings"][q] for q in sorted(questions)},
    }
    covered = [(u.start, u.end) for u in batch.units] + [(f["start"], f["end"]) for f in related]
    contexts = []
    for span in batch.context:
        remaining = [(span.start, span.end)]
        for low, high in covered:
            remaining = [(a, b) for start, end in remaining
                         for a, b in ((start, min(end, low)), (max(start, high), end)) if a < b]
        for start, end in remaining:
            if text[start:end].strip():
                contexts.append(text[start:end] if is_v2 else
                                {"context_start": start, "context_end": end, "text": text[start:end]})
                covered.append((start, end))
    payload["read_only_context"] = contexts


def _contextual_payload(payload, text, resource, batch, source, is_v2):
    """Attach role spans without repeating target text; share same-path context.

    The frozen source coordinates stay server-owned. These offsets describe
    field roles inside a unit, not Claim output locations.
    """
    from ..contextual_correction_sources import related_context
    fields = [f for f in source.fields
              if any(f["start"] < u.end and u.start < f["end"] for u in batch.units)]
    related = related_context(resource, source, fields)
    payload["structured_context"] = {
        "version": source.snapshot["version"],
        "input_version": source.snapshot["input_version"],
        "unit_fields": [
            {"unit_id": u.unit_id, "path": f["path"], "role": f["role"],
             "field_start_in_unit": max(f["start"], u.start) - u.start,
             "field_end_in_unit": min(f["end"], u.end) - u.start,
             "context_paths": source.snapshot["context_bindings"].get(f["path"], [])}
            for u in batch.units for f in fields if f["start"] < u.end and u.start < f["end"]],
        "read_only_related_fields": related,
    }
    # Preserve neighboring context, excluding text already sent as a target or
    # as a related field. Do not deduplicate identical values at different paths.
    related_paths = {f["path"] for f in related}
    covered = [(u.start, u.end) for u in batch.units]
    covered.extend((f["start"], f["end"]) for f in source.fields if f["path"] in related_paths)
    contexts = []
    for span in batch.context:
        remaining = [(span.start, span.end)]
        for low, high in covered:
            remaining = [(a, b) for start, end in remaining
                         for a, b in ((start, min(end, low)), (max(start, high), end)) if a < b]
        for start, end in remaining:
            if text[start:end].strip():
                contexts.append(text[start:end] if is_v2 else
                    {"context_start": start, "context_end": end, "text": text[start:end]})
                covered.append((start, end))
    payload["read_only_context"] = contexts
