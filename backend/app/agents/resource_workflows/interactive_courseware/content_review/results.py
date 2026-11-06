from app.models.courseware.content_review import BatchResultV1, ContentReviewBlocked


def validate_results(raw, batch):
    output = BatchResultV1.model_validate_json(raw.model_dump_json() if hasattr(raw, "model_dump_json") else __import__("json").dumps(raw))
    if (output.batch_id, output.identity, output.value_hash) != (batch.batch_id, batch.identity, batch.value_hash):
        raise ContentReviewBlocked("mixed batch/identity/hash")
    actual = [r.item_id for r in output.results]
    if len(actual) != len(set(actual)) or set(actual) != {i.item_id for i in batch.items}:
        raise ContentReviewBlocked("missing/duplicate/extra field result")
    by_id = {i.item_id: i for i in batch.items}
    for result in output.results:
        item = by_id[result.item_id]
        rules = [r.rule_id for r in result.rules]
        if result.value_hash != item.value_hash or len(rules) != len(set(rules)) or set(rules) != set(item.rule_ids):
            raise ContentReviewBlocked("incomplete rule/value binding")
        for rule in result.rules:
            if len(rule.evidence_ids) != len(set(rule.evidence_ids)) or not set(rule.evidence_ids) <= set(item.evidence_ids):
                raise ContentReviewBlocked("unknown evidence")
            if rule.verdict == "pass" and (not rule.evidence_ids or rule.problems):
                raise ContentReviewBlocked("unsupported pass")
            if rule.verdict != "pass" and not rule.problems:
                raise ContentReviewBlocked("missing bounded finding")
            if rule.rule_id == "factual_support":
                if rule.factual_support is None or (rule.factual_support == "not_applicable" and not rule.reason):
                    raise ContentReviewBlocked("missing factual verdict/reason")
                if rule.verdict == "pass" and rule.factual_support not in {"supported", "not_applicable"}:
                    raise ContentReviewBlocked("conflicting factual verdict")
                if rule.factual_support == "not_applicable" and (rule.verdict != "pass" or rule.problems):
                    raise ContentReviewBlocked("not_applicable cannot carry a failure")
            elif rule.factual_support is not None:
                raise ContentReviewBlocked("factual verdict outside rule")
            if rule.reason and not (rule.rule_id == "factual_support" and rule.factual_support == "not_applicable"):
                raise ContentReviewBlocked("reason is reserved for non-factual guidance; failures use bounded problems")
    return output


def passed(results):
    return all(rule.verdict == "pass" for item in results for rule in item.rules)
