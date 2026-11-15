"""Assessment construction and deterministic scoring for feedback."""

from __future__ import annotations

import json
import hashlib
import random
import re
from collections.abc import Callable
from decimal import Decimal, ROUND_HALF_UP
from app.models.learning_documents.schemas import (
    LearnerProfile,
    LearningResource,
    ResourceEvaluationQuestion,
)
from app.models.shared.assessment import (
    ASSESSMENT_QUESTION_QUOTAS,
    ASSESSMENT_SCORE_BY_TYPE,
    ASSESSMENT_SCORE_DECIMAL_PLACES,
    ASSESSMENT_TOTAL_SCORE,
)
from app.services.knowledge.knowledge import KnowledgeService


def _build_question_specs(
    profile: LearnerProfile,
    resource: LearningResource,
    knowledge_service: KnowledgeService,
    limit: int = 10,
    *,
    resource_target_skill_nodes: Callable,
    usable_resource_exercises: Callable,
    structured_assessment_questions: Callable,
    order_questions_for_coverage: Callable,
) -> tuple[list[ResourceEvaluationQuestion], dict[str, object]]:
    questions: list[ResourceEvaluationQuestion] = []
    answer_key: dict[str, object] = {}

    structured = structured_assessment_questions(resource)
    if structured is not None:
        for item in structured[:limit]:
            question_id = str(item["question_id"])
            options = [f"{choice['option_id']}. {choice['text']}" for choice in item.get("options", [])]
            questions.append(ResourceEvaluationQuestion(
                question_id=question_id, question_type=item["question_type"], question=item["stem"],
                options=options, skill_node_id=item.get("skill_node_id"), path_node_id=resource.learning_path_node,
                knowledge_point=(item.get("knowledge_point_tags") or [None])[0], difficulty=resource.difficulty,
                source="resource",
            ))
            answer_key[question_id] = item
        return questions, answer_key

    generated_items = usable_resource_exercises(resource)
    if generated_items:
        for item in generated_items[:limit]:
            question_id = f"{resource.resource_id}:{item.question_id}"
            questions.append(
                ResourceEvaluationQuestion(
                    question_id=question_id,
                    question_type=item.question_type,
                    question=item.question,
                    options=item.options,
                    skill_node_id=item.skill_node_id or resource.learning_path_node,
                    path_node_id=resource.learning_path_node,
                    knowledge_point=item.knowledge_point,
                    difficulty=item.difficulty,
                    diagnostic_dimension=item.diagnostic_dimension,
                    source="resource",
                )
            )
            answer_key[question_id] = item.answer
        return questions, answer_key

    if not profile.knowledge_base_id:
        return questions, answer_key

    target_skill_nodes = [item for item in resource_target_skill_nodes(resource) if item]
    load_assessment = getattr(knowledge_service, "load_assessment_questions", None)
    candidates = load_assessment(profile.knowledge_base_id) if load_assessment else []
    question_source = "assessment_bank"
    if not candidates:
        # 兼容尚未配置独立测评题库的其他知识库。
        candidates = knowledge_service.load_diagnostic_questions(profile.knowledge_base_id)
        question_source = "knowledge_base"
    related = [
        item
        for item in candidates
        if target_skill_nodes and item.skill_node_id in target_skill_nodes
    ]
    seen_related_ids = {item.question_id for item in related}

    tokens = [resource.topic or "", *(resource.knowledge_points or [])]
    for item in candidates:
        if item.question_id in seen_related_ids:
            continue
        searchable = " ".join(
            [
                item.question or "",
                item.knowledge_point or "",
                " ".join(item.options or []),
            ]
        )
        if any(token and token in searchable for token in tokens):
            related.append(item)
            seen_related_ids.add(item.question_id)

    if len(related) < limit:
        select_assessment = getattr(knowledge_service, "select_assessment_questions", None)
        if question_source == "assessment_bank" and select_assessment:
            selected = select_assessment(
                profile.knowledge_base_id,
                # 只有确实命中题库节点时才把路径节点作为硬过滤，兼容历史资源中
                # 使用展示名称或旧节点 ID 的 learning_path_node。
                skill_node_ids=target_skill_nodes if related else None,
                limit=limit,
            )
        else:
            selected = knowledge_service.select_diagnostic_questions(
                profile.knowledge_base_id,
                limit=limit,
            )
        for item in selected:
            if item.question_id in seen_related_ids:
                continue
            related.append(item)
            seen_related_ids.add(item.question_id)
            if len(related) >= limit:
                break

    for item in order_questions_for_coverage(related)[:limit]:
        questions.append(
            ResourceEvaluationQuestion(
                question_id=item.question_id,
                question_type=item.question_type,
                question=item.question,
                options=item.options or [],
                skill_node_id=item.skill_node_id,
                path_node_id=resource.learning_path_node,
                knowledge_point=item.knowledge_point,
                difficulty=item.difficulty,
                diagnostic_dimension=item.metadata.get("diagnostic_dimension"),
                source=question_source,
            )
        )
        answer_key[item.question_id] = item.answer

    return questions, answer_key


def _structured_assessment_questions(resource: LearningResource) -> list[dict] | None:
    payload = resource.assessment_payload
    if payload is None:
        return None
    expected_hash = resource.assessment_payload_hash or payload.get("payload_hash")
    actual_payload = {key: value for key, value in payload.items() if key != "payload_hash"}
    actual_hash = hashlib.sha256(json.dumps(actual_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if not expected_hash or expected_hash != actual_hash:
        raise ValueError("结构化测试题资源校验失败")
    blocks = payload.get("node_blocks", [])
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("结构化测试题资源内容不完整")
    rows = []
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError("结构化测试题资源题型配额无效")
        for field_name, quota in (
            ("single_choice_questions", ASSESSMENT_QUESTION_QUOTAS["single_choice"]),
            ("multiple_choice_questions", ASSESSMENT_QUESTION_QUOTAS["multiple_choice"]),
            ("short_answer_questions", ASSESSMENT_QUESTION_QUOTAS["short_answer"]),
        ):
            values = block.get(field_name)
            if not isinstance(values, list) or len(values) != quota:
                raise ValueError("结构化测试题资源题型配额无效")
        for field_name in ("single_choice_questions", "multiple_choice_questions", "short_answer_questions"):
            for question in block.get(field_name, []):
                rows.append({**question, "skill_node_id": block.get("skill_node_id"), "skill_node_name": block.get("skill_node_name")})
    type_totals = {
        question_type: round(
            sum(float(item.get("max_score", 0)) for item in rows if item.get("question_type") == question_type),
            ASSESSMENT_SCORE_DECIMAL_PLACES,
        )
        for question_type in ASSESSMENT_QUESTION_QUOTAS
    }
    expected_type_totals = {
        question_type: ASSESSMENT_SCORE_BY_TYPE[question_type] * quota
        for question_type, quota in ASSESSMENT_QUESTION_QUOTAS.items()
    }
    if (
        not rows
        or round(sum(float(item.get("max_score", 0)) for item in rows), ASSESSMENT_SCORE_DECIMAL_PLACES) != ASSESSMENT_TOTAL_SCORE
        or type_totals != expected_type_totals
    ):
        raise ValueError("结构化测试题资源内容不完整")
    return rows


def _order_questions_for_coverage(questions: list) -> list:
    dimensions = ("concept", "scenario", "misconception")
    ordered = []
    seen = set()
    for dimension in dimensions:
        for question in questions:
            if question.question_id in seen:
                continue
            diagnostic_dimension = getattr(question, "diagnostic_dimension", None)
            if diagnostic_dimension is None:
                diagnostic_dimension = getattr(question, "metadata", {}).get("diagnostic_dimension")
            if diagnostic_dimension == dimension:
                ordered.append(question)
                seen.add(question.question_id)
    for question in questions:
        if question.question_id not in seen:
            ordered.append(question)
    return ordered


def _shuffle_question_options(
    questions: list[ResourceEvaluationQuestion],
    learner_id: str,
    session_id: str,
) -> list[ResourceEvaluationQuestion]:
    """Shuffle fallback-bank choices while preserving generated-resource choices.

    Generated and structured assessment resources already have an authored
    option order.  Only fallback questions selected from the shared bank
    need deterministic shuffling to avoid presenting the same bank order
    to every learner while keeping a session resumable.
    """
    shuffled_questions = []
    for question in questions:
        options = list(question.options or [])
        if question.source in {"assessment_bank", "knowledge_base"} and len(options) > 1:
            seed_material = f"{learner_id}\x1f{session_id}\x1f{question.question_id}"
            seed = int.from_bytes(hashlib.sha256(seed_material.encode("utf-8")).digest()[:8], "big")
            random.Random(seed).shuffle(options)
        shuffled_questions.append(question.model_copy(update={"options": options}))
    return shuffled_questions


def _question_max_score(expected: object) -> float:
    if isinstance(expected, dict):
        value = float(expected.get("max_score") or 0.0)
        if value > 0:
            return value
    return 1.0


def _normalize_answer_set(value: object) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        raw_values = [value]
    values = set()
    for item in raw_values:
        text = str(item).strip()
        match = re.match(r"^([A-D])(?:[.、\s]|$)", text, re.I)
        values.add((match.group(1) if match else text).casefold()) if text else None
    return values


def _build_run_question_specs(
    profile: LearnerProfile,
    resources: list[LearningResource],
    knowledge_service: KnowledgeService,
    questions_per_skill_node: int = 1,
    max_questions: int = 13,
    *,
    build_question_specs: Callable,
    latest_structured_resources: Callable,
    usable_resource_exercises: Callable,
    order_questions_for_coverage: Callable,
) -> tuple[list[ResourceEvaluationQuestion], dict[str, object]]:
    """Build one question per covered skill node, capped for a focused feedback session."""
    candidates: list[ResourceEvaluationQuestion] = []
    answer_key: dict[str, object] = {}
    seen_question_ids: set[str] = set()
    structured_resources = latest_structured_resources(resources)
    # A published v2 assessment is authoritative for its batch.  Do not
    # silently mix it with bank items or truncate its fixed 6-question
    # node blocks; a corrupt payload is rejected by _build_question_specs.
    if structured_resources:
        for resource in structured_resources:
            questions, keys = build_question_specs(profile, resource, knowledge_service, limit=1000)
            for question in questions:
                if question.question_id in seen_question_ids:
                    raise ValueError("结构化测试题中存在重复题号")
                candidates.append(question)
                answer_key[question.question_id] = keys[question.question_id]
                seen_question_ids.add(question.question_id)
        return candidates, answer_key
    skill_nodes = list(dict.fromkeys(
        resource.learning_path_node for resource in resources if resource.learning_path_node
    ))

    resources_with_generated_questions = [
        resource
        for resource in resources
        if usable_resource_exercises(resource)
    ]
    # 任务中只要有资源携带 AI 生成题，就只聚合这些题；只有整个任务均未生成
    # 可判分题目时，才由每个资源对应的能力节点触发题库回退。
    question_resources = resources_with_generated_questions or resources

    for resource in question_resources:
        questions, resource_answer_key = build_question_specs(
            profile,
            resource,
            knowledge_service,
            limit=50,
        )
        for question in questions:
            if question.question_id in seen_question_ids:
                continue
            candidates.append(question)
            answer_key[question.question_id] = resource_answer_key.get(question.question_id)
            seen_question_ids.add(question.question_id)
            if question.skill_node_id and question.skill_node_id not in skill_nodes:
                skill_nodes.append(question.skill_node_id)

    if not skill_nodes:
        selected = candidates[:max_questions]
        return selected, {item.question_id: answer_key[item.question_id] for item in selected}

    # AI-generated resource exercises can be sparse. Supplement each covered
    # node from the assessment bank so every node has a comparable check.
    load_assessment = getattr(knowledge_service, "load_assessment_questions", None)
    assessment_candidates = load_assessment(profile.knowledge_base_id) if load_assessment else []
    assessment_source = "assessment_bank"
    if not assessment_candidates:
        assessment_candidates = knowledge_service.load_diagnostic_questions(profile.knowledge_base_id)
        assessment_source = "knowledge_base"

    for skill_node_id in skill_nodes:
        current_count = sum(question.skill_node_id == skill_node_id for question in candidates)
        if current_count >= questions_per_skill_node:
            continue
        for item in assessment_candidates:
            if item.question_id in seen_question_ids or item.skill_node_id != skill_node_id:
                continue
            candidates.append(
                ResourceEvaluationQuestion(
                    question_id=item.question_id,
                    question_type=item.question_type,
                    question=item.question,
                    options=item.options or [],
                    skill_node_id=item.skill_node_id,
                    path_node_id=skill_node_id,
                    knowledge_point=item.knowledge_point,
                    difficulty=item.difficulty,
                    diagnostic_dimension=item.metadata.get("diagnostic_dimension"),
                    source=assessment_source,
                )
            )
            answer_key[item.question_id] = item.answer
            seen_question_ids.add(item.question_id)
            current_count += 1
            if current_count >= questions_per_skill_node:
                break

    selected_questions: list[ResourceEvaluationQuestion] = []
    selected_answer_key: dict[str, object] = {}
    for skill_node_id in skill_nodes:
        if len(selected_questions) >= max_questions:
            break
        node_questions = order_questions_for_coverage(
            [question for question in candidates if question.skill_node_id == skill_node_id]
        )[:questions_per_skill_node]
        for question in node_questions:
            if len(selected_questions) >= max_questions:
                break
            selected_questions.append(question)
            selected_answer_key[question.question_id] = answer_key[question.question_id]

    return selected_questions, selected_answer_key


def _round_assessment_score(value: float) -> float:
    """Round learner-facing assessment scores with decimal half-up semantics."""

    quantum = Decimal("1").scaleb(-ASSESSMENT_SCORE_DECIMAL_PLACES)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def _weighted_point_scores(question_results: list[dict[str, object]]) -> dict[str, float]:
    """Aggregate question scores by point using each question's maximum score.

    ``correct_count`` is reserved for fully correct questions. It must not be
    used as the point score because partial answers still earn score.
    """

    totals: dict[str, float] = {}
    maximums: dict[str, float] = {}
    for item in question_results:
        point_id = item.get("skill_node_id") or item.get("knowledge_point") or "综合能力"
        try:
            score = float(item.get("score") or 0.0)
            maximum = float(item.get("max_score") or 0.0)
        except (TypeError, ValueError):
            continue
        if maximum <= 0:
            continue
        point_id = str(point_id)
        totals[point_id] = totals.get(point_id, 0.0) + score
        maximums[point_id] = maximums.get(point_id, 0.0) + maximum
    return {
        point_id: total / maximums[point_id]
        for point_id, total in totals.items()
        if maximums.get(point_id, 0.0) > 0
    }
