"""Single current representation and bounded issue context for semantic review.

Complete predecessor material stays server-side for identity, location and delta
validation. No prior artifact is included in the model request.
"""

import json

from ..types import PromptFragment

INPUT_CONTRACT = "single_representation_v1"
INPUT_CONTRACT_V2 = "single_representation_v2"
INPUT_CONTRACT_V3 = "single_representation_v3"
INPUT_CONTRACT_V4 = "single_representation_v4"
RANGE_CONTRACTS = {INPUT_CONTRACT_V3, INPUT_CONTRACT_V4}
NUMBERED_CONTRACTS = {INPUT_CONTRACT_V2, *RANGE_CONTRACTS}
MARKDOWN_RANGE_TYPES = {"讲义", "案例分析"}
ISSUE_EXCERPT_CHARS = 240
MAX_CHANGED_PATHS = 64


def input_rules(output_rules, input_contract=INPUT_CONTRACT):
    """Keep the historical prompt immutable for already frozen runs."""
    text = output_rules.text.replace(
        "previous_location 只定位 previous_content / previous_structured_payload 中的父版；current_location 只定位当前版本。",
        "previous_location 只能引用 parent_issue_context 中对应问题的 location；current_location 只定位新版。"
    )
    text = text.replace("结构化资源（实操指南、测评、复习清单）", "结构化资源（实操指南、测评、复习清单、JSON纠错包）")
    text += """
输入契约 single_representation_v1：只提供一个新版内容表示，不提供完整旧版。
structured_payload 是完整新版结构化内容（包含审核需要的答案/评分规则）；有它时不再提供text。
无structured_payload时text是完整新版正文。先全面检查新版，再逐项核销old_issues中status=open的问题，
不能因为修订过就默认通过；无法确认用unverifiable，不能关闭。已关闭问题仍须检查是否回归。
old_issues保留稳定ID、问题描述、要求、验收条件、证据和位置；parent_issue_context仅为旧问题的有限原文片段，
truncated=true表示片段不完整，空片段不代表父版没有问题；旧片段与旧意见不能作为技术事实证据。
false_positive只能在所附旧问题上下文足以证明误报时使用，否则unverifiable。
JSON引用location_index.unit_ids及unit_fields；不要推测未提供的段落ID。
change_summary是程序差异统计，不是审核通过依据；任何改动都必须满足新版整体质量要求。
"""
    if input_contract in NUMBERED_CONTRACTS:
        text = text.replace(INPUT_CONTRACT, INPUT_CONTRACT_V2)
        text = text.replace(
            "heading_path必须与原文该段所属标题一致；没有标题才是[]。",
            "heading_path留空；服务端根据paragraph_id补全并验证。",
        )
        text += """
Markdown 段落资源的 text 每行以 p000001 等服务端行号开头；行号仅用于定位，不是正文。
引用当前正文时只填写该行的 paragraph_id，heading_path 留空；服务端按行号补全标题路径。
不要推测行号、引用未列出的行或把行号当作技术事实。父版位置按 parent_issue_context 已提供的原位置填写。
"""
        if input_contract in RANGE_CONTRACTS:
            text = text.replace(INPUT_CONTRACT_V2, input_contract)
            text = text.replace("paragraph_id、heading_path 或 quote", "paragraph_id 或 quote")
            text = text.replace('{"kind":"paragraph","paragraph_id":"indexed-paragraph","heading_path":[]}',
                                '{"kind":"paragraph","paragraph_id":"indexed-paragraph"}')
            text = text.replace("heading_path留空；服务端根据paragraph_id补全并验证。",
                                "标题路径由服务端根据paragraph_id计算。")
            text = text.replace("heading_path 留空；服务端按行号补全标题路径。",
                                "标题路径由服务端根据行号计算。")
            text += """
仅讲义和案例分析的 Markdown 位置允许连续行范围：单行只填 paragraph_id；跨多行填起始
paragraph_id 与 end_paragraph_id（均为正文所列行号，含两端，且按正文顺序）。不要为同一行填结束行。
quote 若提供，必须逐字出现在该连续范围内；不能拼接互不相邻的引文。影响整份资源且无法定位
到具体连续行的问题用 kind=root。标题路径由服务端按起始行计算。
复审时 previous_location 复制 parent_issue_context 中该旧问题的位置（含结束行，如有）；
current_location 只引用当前新版的行号，不能沿用旧版行号推测新版位置。
"""
            if input_contract == INPUT_CONTRACT_V4:
                text = text.replace("只返回绑定 schema 的严格 JSON", "只返回符合 schema 的 JSON")
                text += """
只写本轮审核判断。没有发现问题时 issues 为 []；发现问题时写清位置、影响、阻断判断、最小修改要求和验收条件。
缺少练习所需材料属于 self_contained，不填写 affected_target_ids。
缺少某个冻结目标的讲解属于 coverage，只有该目标在 targets 中为 missing 才能填入 affected_target_ids。
覆盖问题若阻断，至少引用一个缺失目标。首审没有旧问题，不填复审记录；逐题 findings 仅用于分阶测试题。
"""
                return PromptFragment("resource_issue.single_input.output", "4.0", text)
            return PromptFragment("resource_issue.single_input.output", "3.0", text)
        return PromptFragment("resource_issue.single_input.output", "2.0", text)
    return PromptFragment("resource_issue.single_input.output", "1.0", text)


def canonicalize_current_paragraph_locations(output, material):
    """Fill derived heading paths without weakening ID and quote validation."""
    if material.structured_payload is not None:
        return output
    data = output.model_dump(mode="json")
    locations = [item.get("location") for item in data.get("targets", [])]
    locations.extend(item.get("location") for item in data.get("issues", []))
    locations.extend(item.get("current_location") for item in data.get("resolutions", []))
    locations.extend(item.get("current_location") for item in data.get("reopen", []))
    for location in locations:
        if not isinstance(location, dict) or location.get("kind") != "paragraph":
            continue
        paragraph_id = location.get("paragraph_id")
        if paragraph_id in material.index.heading_paths:
            location["heading_path"] = list(material.index.heading_paths[paragraph_id])
    return type(output).model_validate(data)


def materialize_model_output(output, material, previous, *, markdown: bool, binding=None):
    """Construct the internal ledger output from the parsed model output."""
    from app.models.reviews.resource_review import ResourceReviewInitialV1, ResourceReviewRecheckV1

    data = output.model_dump(mode="json")
    if binding is not None:
        from app.models.reviews.resource_review_model_output import model_issue_record

        data["binding"] = binding.model_dump(mode="json")
        data["issues"] = [model_issue_record(issue) for issue in data["issues"]]
    if markdown:
        _restore_markdown_headings(data, material, previous)
    internal_schema = ResourceReviewRecheckV1 if previous else ResourceReviewInitialV1
    return internal_schema.model_validate(data)


def _restore_markdown_headings(data, material, previous):
    locations = [item.get("location") for item in data.get("targets", [])]
    locations.extend(item.get("location") for item in data.get("issues", []))
    locations.extend(item.get("current_location") for item in data.get("resolutions", []))
    locations.extend(item.get("current_location") for item in data.get("reopen", []))
    for location in locations:
        if isinstance(location, dict) and location.get("kind") == "paragraph":
            start_id = location.get("paragraph_id")
            if start_id in material.index.heading_paths:
                location["heading_path"] = list(material.index.heading_paths[start_id])
    old_issues = {entry.issue.issue_id: entry.issue for entry in previous.issues} if previous else {}
    for resolution in data.get("resolutions", []):
        location = resolution.get("previous_location")
        old = old_issues.get(resolution.get("issue_id"))
        if isinstance(location, dict) and location.get("kind") == "paragraph" and old is not None:
            location["heading_path"] = list(old.location.heading_path)


def _model_markdown_location(location):
    if isinstance(location, dict):
        allowed = {"kind", "paragraph_id", "end_paragraph_id", "quote"}
        for key in tuple(location):
            if key not in allowed:
                location.pop(key)
    return location


def validate_range_contract(output, *, input_contract, resource_type):
    """Historical runs and structured resources cannot introduce ranges."""
    from .validation import require

    locations = [item.location for item in output.targets]
    locations.extend(item.location for item in output.issues)
    locations.extend(item.current_location for item in output.resolutions)
    locations.extend(item.previous_location for item in output.resolutions)
    locations.extend(item.current_location for item in output.reopen)
    for location in locations:
        if location is None or location.end_paragraph_id is None:
            continue
        require(input_contract in RANGE_CONTRACTS and resource_type in MARKDOWN_RANGE_TYPES,
                "LOCATION_OUT_OF_BOUNDS", "location.end_paragraph_id",
                "line ranges require a new Markdown review contract")


def validate_issue_context_resolutions(output, previous, parent_material):
    """A model cannot close an issue by citing withheld predecessor content."""
    from .validation import require
    if previous is None:
        return
    issues = {entry.issue.issue_id: entry.issue for entry in previous.issues}
    for resolution in output.resolutions:
        issue = issues.get(resolution.issue_id)
        if issue is None:
            continue  # The complete resolution-set validator rejects this ID.
        if resolution.previous_location is not None:
            original = issue.location.model_dump(exclude={"quote"})
            returned = resolution.previous_location.model_dump(exclude={"quote"})
            require(original == returned, "LOCATION_OUT_OF_BOUNDS", "resolutions.previous_location",
                    "predecessor location was not included in this issue context")
            excerpt, _ = _excerpt(parent_material, issue.location)
            quote = resolution.previous_location.quote
            require(quote is None or quote in excerpt, "LOCATION_OUT_OF_BOUNDS", "resolutions.previous_location.quote",
                    "predecessor quote was not supplied to the reviewer")
        if resolution.result == "false_positive":
            excerpt, _ = _excerpt(parent_material, issue.location)
            require(bool(excerpt), "REOPEN_INVALID", "resolutions.false_positive",
                    "missing predecessor context cannot establish a false positive; use unverifiable")


def _find_unit(value, unit_id):
    if isinstance(value, dict):
        if any(value.get(key) == unit_id for key in ("question_id", "step_id", "skill_node_id")):
            return value
        if unit_id in value:
            return value[unit_id]
        for child in value.values():
            found = _find_unit(child, unit_id)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_unit(child, unit_id)
            if found is not None:
                return found
    return None


def _excerpt(material, location):
    if location.kind == "paragraph":
        lines = material.index.paragraph_text
        start = int(location.paragraph_id[1:])
        end = int((location.end_paragraph_id or location.paragraph_id)[1:])
        value = "\n".join(lines.get(f"p{number:06d}", "") for number in range(start, end + 1))
    elif location.kind == "structured" and material.structured_payload is not None:
        value = _find_unit(material.structured_payload, location.unit_id)
        if location.field_path and isinstance(value, dict):
            # Correction fields are complete source paths; other adapters use
            # a question/step-relative field whitelist.
            if location.unit_id == "content":
                from app.core.learning_documents.correction_package import correction_audit_source
                from app.models.learning_documents.correction_package import parse_correction_package
                source = correction_audit_source(parse_correction_package(material.structured_payload))
                selected = set(location.field_path)
                value = "\n".join(source.text[f.start:f.end] for f in source.fields if f.path in selected)
            else:
                value = {key: value[key] for key in location.field_path if key in value}
        value = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False) if value is not None else ""
    else:
        value = ""
    return value[:ISSUE_EXCERPT_CHARS], len(value) > ISSUE_EXCERPT_CHARS


def _changed_paths(before, after, path=""):
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            yield from _changed_paths(before.get(key), after.get(key), f"{path}.{key}" if path else key)
    elif isinstance(before, list) and isinstance(after, list):
        for i in range(max(len(before), len(after))):
            yield from _changed_paths(before[i] if i < len(before) else None,
                                      after[i] if i < len(after) else None, f"{path}[{i}]")
    elif before != after:
        yield path


def single_input_payload(*, material, binding, targets, frozen_evidence, previous=None,
                         parent_material=None, input_contract=INPUT_CONTRACT):
    index = {"root_allowed": material.index.root_allowed}
    payload = {"input_contract": input_contract}
    if input_contract != INPUT_CONTRACT_V4:
        payload["binding"] = binding.model_dump(mode="json")
    payload.update({
        "resource_type": material.resource_type, "difficulty": material.difficulty,
        "targets": list(dict.fromkeys(targets)), "evidence": frozen_evidence,
        "teaching_rule_ids": list(material.rule_ids), "location_index": index,
    })
    if material.structured_payload is not None:
        value = material.structured_payload
        if material.resource_type == "个性化纠错训练包":
            from app.core.learning_documents.correction_package import correction_model_projection
            from app.models.learning_documents.correction_package import parse_correction_package
            value = correction_model_projection(parse_correction_package(value))
        payload["structured_payload"] = value
        index.update(unit_ids=sorted(material.index.unit_ids),
                     unit_fields={key: sorted(values) for key, values in material.index.unit_fields.items()})
    else:
        payload["text"] = (
            "\n".join(f"{paragraph_id} | {line}" for paragraph_id, line in material.index.paragraph_text.items())
            if input_contract in NUMBERED_CONTRACTS else material.text
        )
        index.update(paragraph_ids=sorted(material.index.paragraph_ids))
    if previous is not None:
        if parent_material is None:
            raise ValueError("single-input recheck requires verified parent material")
        entries = [entry for entry in previous.issues
                   if input_contract != INPUT_CONTRACT_V4 or entry.issue.origin == "model_review"]
        payload["old_issues"] = [
            {"issue": entry.issue.model_dump(mode="json"), "status": entry.status}
            for entry in entries
        ]
        if input_contract == INPUT_CONTRACT_V4:
            for item in payload["old_issues"]:
                issue = item["issue"]
                for field in ("origin", "criteria_version", "blocking_rule"):
                    issue.pop(field)
                if issue["dimension"] != "coverage":
                    issue.pop("affected_target_ids")
        context = []
        for entry in entries:
            excerpt, truncated = _excerpt(parent_material, entry.issue.location)
            context.append({"issue_id": entry.issue.issue_id,
                            "location": entry.issue.location.model_dump(mode="json"),
                            "excerpt": excerpt, "truncated": truncated})
        payload["parent_issue_context"] = context
        if input_contract in RANGE_CONTRACTS and material.resource_type in MARKDOWN_RANGE_TYPES:
            for item in payload["old_issues"]:
                _model_markdown_location(item["issue"]["location"])
            for item in context:
                _model_markdown_location(item["location"])
        payload["parent_version"] = previous.binding.version
        before = parent_material.comparison_projection
        after = material.comparison_projection
        if material.structured_payload is None:
            before, after = parent_material.index.paragraph_text, material.index.paragraph_text
        changed = list(_changed_paths(before, after))
        payload["change_summary"] = {
            "unchanged": parent_material.comparison_hash == material.comparison_hash,
            "changed_path_count": len(changed), "changed_paths": changed[:MAX_CHANGED_PATHS],
            "paths_truncated": len(changed) > MAX_CHANGED_PATHS,
        }
    return payload
