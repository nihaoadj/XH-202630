"""Pure report sections with explicit ordering and time dependencies."""

from __future__ import annotations

from app.models.learners.mastery import MASTERY_CONFIRMATION_THRESHOLD
from app.services.reports.difficulty_matching import STRATEGY_VERSION, match_difficulty
from datetime import datetime, timezone
from collections.abc import Callable
from types import SimpleNamespace


def ability_radar(ordered_nodes, catalog_nodes, *, order_nodes: Callable) -> dict:
    """Project all graph axes; subjective scores never replace the graph."""
    projected_by_id = {node.skill_node_id: node for node in ordered_nodes}
    radar_nodes = order_nodes([
        SimpleNamespace(
            skill_node_id=node.node_id, name=node.name, tier=node.tier,
            prerequisites=node.prerequisites,
        )
        for node in catalog_nodes
    ]) or ordered_nodes
    scores = []
    measurement_statuses = []
    for node in radar_nodes:
        projected = projected_by_id.get(node.skill_node_id)
        measured = bool(
            projected and projected.mastery.objective_evidence_count > 0
            and projected.mastery.mastery_score is not None
        )
        self_reported = bool(
            projected and projected.mastery.status.value == "self_reported"
            and projected.mastery.mastery_score is not None
        )
        scores.append(
            round(float(projected.mastery.mastery_score) * 100, 1)
            if (measured or self_reported) else 0.0
        )
        measurement_statuses.append(
            "measured" if measured else "self_reported" if self_reported else "unassessed"
        )
    return {
        "dimensions": [node.name for node in radar_nodes],
        "values": scores,
        "measurement_statuses": measurement_statuses,
    }


def _assessment_conclusions(events, ability_projection) -> dict[str, dict]:
    """Expose why each node is, or is not yet, a trusted conclusion."""
    states = {
        node.skill_node_id: node.mastery
        for node in (ability_projection.nodes if ability_projection else [])
    }
    grouped: dict[str, list] = {}
    for event in events or []:
        if not event.verified or event.source_type.value not in {"diagnosis", "learning_attempt"}:
            continue
        if not getattr(event, "evidence_eligible", True):
            continue
        grouped.setdefault(event.skill_node_id, []).append(event)
    conclusions: dict[str, dict] = {}
    for node_id, state in states.items():
        node_events = sorted(grouped.get(node_id, []), key=lambda item: (item.occurred_at, item.evidence_id))
        sessions = {
            getattr(item, "assessment_session_id", None) or item.source_id
            for item in node_events
        }
        forms = {
            getattr(item, "assessment_form_id", None) or item.source_id
            for item in node_events
        }
        dimensions = sorted({
            dimension
            for item in node_events
            for dimension in getattr(item, "covered_dimensions", [])
        })
        scores = [item.observed_score for item in node_events if item.observed_score is not None]
        high_sessions = sum(score >= MASTERY_CONFIRMATION_THRESHOLD for score in scores)
        required_dimensions = {"concept", "scenario", "misconception"}
        initial_calibrated = any(
            item.source_type.value == "diagnosis"
            and required_dimensions.issubset(set(getattr(item, "covered_dimensions", [])))
            for item in node_events
        )
        cumulative_dimension_ready = required_dimensions.issubset(set(dimensions))
        dimension_ready = initial_calibrated or cumulative_dimension_ready
        qualified_high_events = [
            item for item in node_events
            if item.observed_score is not None and item.observed_score >= MASTERY_CONFIRMATION_THRESHOLD
        ]
        qualified_high_sessions = {
            getattr(item, "assessment_session_id", None) or item.source_id
            for item in qualified_high_events
        }
        if not node_events:
            conclusion, trust = "unassessed", "none"
        elif (
            state.status.value == "mastered"
            and dimension_ready
            and (
                len(qualified_high_sessions) >= 2
                or (
                    len(qualified_high_sessions) >= 1
                    and state.self_report_prior is not None
                    and state.self_report_prior >= 1.0
                )
            )
        ):
            conclusion, trust = "confirmed_mastery", "high"
        elif len(sessions) < 2:
            conclusion, trust = "baseline_observation", "provisional"
        elif scores and scores[-1] < MASTERY_CONFIRMATION_THRESHOLD:
            conclusion, trust = "needs_reinforcement", "medium"
        else:
            conclusion, trust = "awaiting_confirmation", "medium"
        promotion_session_ids = list(dict.fromkeys(
            getattr(item, "assessment_session_id", None) or item.source_id
            for item in qualified_high_events
        ))[:2]
        promotion_index = max(
            (index for index, item in enumerate(node_events)
             if (getattr(item, "assessment_session_id", None) or item.source_id) in promotion_session_ids),
            default=-1,
        )
        opposing = [
            {"source_id": item.source_id, "score": item.observed_score, "occurred_at": item.occurred_at}
            for item in node_events[promotion_index + 1:]
            if item.observed_score is not None and item.observed_score < MASTERY_CONFIRMATION_THRESHOLD
        ]
        conclusions[node_id] = {
            "conclusion": conclusion,
            "trust_status": trust,
            "formal_session_count": len(sessions),
            "independent_form_count": len(forms),
            "eligible_evidence_count": len(node_events),
            "high_score_session_count": high_sessions,
            "covered_dimensions": dimensions,
            "required_dimensions": ["concept", "scenario", "misconception"],
            "dimension_ready": dimension_ready,
            "initial_calibrated": initial_calibrated,
            "last_contradictory_evidence": opposing[-1] if opposing else None,
            "scoring_audit_statuses": list(dict.fromkeys(
                getattr(item, "scoring_audit_status", "not_applicable") for item in node_events
            )),
        }
    return conclusions


def _build_learning_node_mastery_map(
    ability_projection,
    assessment_conclusions,
    mastery_events = (),
    *,
    ordered_ability_nodes: Callable,
    utc: Callable,
) -> dict:
    """Build the ongoing node-level mastery view.

    Initial diagnostic dimensions are intentionally not projected here.
    This map is the stable report view for every learning node and is
    driven by the canonical mastery projection plus eligible formal
    assessment conclusions.
    """
    nodes = ordered_ability_nodes(ability_projection.nodes if ability_projection else [])
    priorities = {
        item.skill_node_id: item
        for item in (ability_projection.weakness_priorities if ability_projection else [])
    }
    events_by_node: dict[str, list] = {}
    for event in mastery_events or []:
        source_type = getattr(getattr(event, "source_type", None), "value", getattr(event, "source_type", None))
        if (
            getattr(event, "verified", False)
            and getattr(event, "evidence_eligible", True)
            and source_type in {"diagnosis", "learning_attempt"}
        ):
            events_by_node.setdefault(event.skill_node_id, []).append(event)

    points = []
    status_counts = {key: 0 for key in ("unassessed", "self_reported", "weak", "learning", "mastered")}
    conclusion_counts = {key: 0 for key in (
        "unassessed", "baseline_observation", "awaiting_confirmation", "confirmed_mastery", "needs_reinforcement"
    )}
    for node in nodes:
        state = node.mastery
        conclusion = (assessment_conclusions or {}).get(node.skill_node_id, {})
        conclusion_name = conclusion.get("conclusion", "unassessed")
        trust_status = conclusion.get("trust_status", "none")
        node_events = sorted(
            events_by_node.get(node.skill_node_id, []),
            key=lambda item: (utc(item.occurred_at), item.evidence_id),
        )
        latest_event = node_events[-1] if node_events else None
        priority = priorities.get(node.skill_node_id)
        if conclusion_name in {"baseline_observation", "awaiting_confirmation"}:
            next_action = "verify"
        elif conclusion_name == "needs_reinforcement" or state.status.value == "weak":
            next_action = "remediate"
        elif conclusion_name == "confirmed_mastery" or state.status.value == "mastered":
            next_action = "maintain"
        elif state.status.value == "learning":
            next_action = "practice"
        else:
            next_action = "learn"
        reasons = list(priority.reason_codes) if priority else []
        if not reasons:
            reasons = {
                "unassessed": ["NO_OBJECTIVE_EVIDENCE"],
                "baseline_observation": ["INITIAL_BASELINE_PENDING_CONFIRMATION"],
                "awaiting_confirmation": ["AWAITING_SECOND_FORMAL_ASSESSMENT"],
                "confirmed_mastery": ["TWO_INDEPENDENT_FORMAL_ASSESSMENTS"],
                "needs_reinforcement": ["LATEST_FORMAL_RESULT_BELOW_0_80"],
            }.get(conclusion_name, ["MASTERY_PROJECTION"])
        point = {
            "skill_node_id": node.skill_node_id,
            "name": node.name,
            "tier": node.tier,
            "tier_label": node.tier_label,
            "mastery_score": state.mastery_score,
            "mastery_status": state.status.value,
            "conclusion": conclusion_name,
            "trust_status": trust_status,
            "confidence": state.confidence.value,
            "objective_evidence_count": state.objective_evidence_count,
            "independent_session_count": conclusion.get("formal_session_count", 0),
            "independent_form_count": conclusion.get("independent_form_count", 0),
            "high_score_session_count": conclusion.get("high_score_session_count", 0),
            "latest_observed_score": latest_event.observed_score if latest_event else None,
            "trend_delta": node.trend_delta,
            "last_evidence_at": latest_event.occurred_at if latest_event else state.last_updated,
            "next_action": next_action,
            "reason_codes": reasons,
        }
        points.append(point)
        status_counts[state.status.value] += 1
        conclusion_counts[conclusion_name] += 1
    return {
        "schema_version": "1.0",
        "nodes": points,
        "summary": {
            **{f"status_{key}_count": value for key, value in status_counts.items()},
            **{f"conclusion_{key}_count": value for key, value in conclusion_counts.items()},
            "total_node_count": len(points),
            "actionable_node_count": sum(item["next_action"] != "maintain" for item in points),
        },
    }


def _build_blind_spot_map(
    ability_projection,
    attempts,
    diagnostic_runs = (),
    *,
    ordered_ability_nodes: Callable,
    score_status: Callable,
    utc: Callable,
) -> dict:
    """Project only dimension evidence that can be reconstructed exactly.

    A point-level attempt result can cover several questions.  If its stored
    trace spans more than one dimension, the aggregate score cannot be
    honestly split across those dimensions, so the relevant cells stay in
    an evidence-needed state instead of copying the node score.
    """
    dimensions = ["concept", "scenario", "misconception", "practice"]
    nodes = ordered_ability_nodes(ability_projection.nodes if ability_projection else [])
    node_ids = {item.skill_node_id for item in nodes}
    exact_scores: dict[tuple[str, str], tuple[datetime, str, float]] = {}
    pending_diagnostic_cells: set[tuple[str, str]] = set()
    # Initial direction diagnosis is a formal server-scored source too.
    # Its trace is deliberately de-identified: no learner answer, answer
    # key, or explanation is needed to render a blind-spot cell.
    for run in diagnostic_runs:
        raw = run.raw_result if isinstance(run.raw_result, dict) else {}
        submitted_at = utc(run.created_at) if run.created_at else datetime.min.replace(tzinfo=timezone.utc)
        for item in raw.get("blind_spot_trace", []):
            if not isinstance(item, dict):
                continue
            node_id = item.get("skill_node_id")
            dimension = item.get("diagnostic_dimension")
            if node_id not in node_ids or dimension not in dimensions or not isinstance(item.get("correct"), bool):
                continue
            key = (node_id, dimension)
            if item.get("measurement_status") != "measured":
                pending_diagnostic_cells.add(key)
                continue
            candidate = (submitted_at, f"diagnosis:{run.diagnostic_result_id}", 1.0 if item["correct"] else 0.0)
            if key not in exact_scores or candidate[:2] > exact_scores[key][:2]:
                exact_scores[key] = candidate
    for attempt in attempts:
        trace = attempt.metadata.get("question_trace", []) if isinstance(attempt.metadata, dict) else []
        trace_by_question = {
            str(item.get("question_id")): item for item in trace
            if isinstance(item, dict) and item.get("question_id")
        }
        for result in attempt.knowledge_point_results:
            entries = [trace_by_question.get(question_id) for question_id in result.question_ids]
            if not entries or any(entry is None for entry in entries):
                continue
            pairs = {
                (str(entry.get("skill_node_id")), str(entry.get("diagnostic_dimension")))
                for entry in entries
                if entry.get("skill_node_id") in node_ids and entry.get("diagnostic_dimension") in dimensions
            }
            if len(pairs) != 1:
                continue
            node_id, dimension = pairs.pop()
            observed = result.correct_count / result.total_count
            key = (node_id, dimension)
            candidate = (utc(attempt.submitted_at), attempt.attempt_id, observed)
            if key not in exact_scores or candidate[:2] > exact_scores[key][:2]:
                exact_scores[key] = candidate

    cells = []
    node_states = {}
    for node in nodes:
        state = node.mastery
        statuses = []
        has_dimension_score = any(
            (node.skill_node_id, dimension) in exact_scores for dimension in dimensions
        )
        for dimension in dimensions:
            evidence = exact_scores.get((node.skill_node_id, dimension))
            if evidence is not None:
                score = round(evidence[2], 6)
                status = score_status(score)
                reasons = ["FORMAL_DIMENSION_EVIDENCE"]
            elif (node.skill_node_id, dimension) in pending_diagnostic_cells:
                score = None
                status = "needs_evidence"
                reasons = ["DIAGNOSTIC_COVERAGE_INCOMPLETE"]
            elif (
                dimension == "concept"
                and not has_dimension_score
                and state.objective_evidence_count > 0
                and state.mastery_score is not None
            ):
                # Older generated-resource assessments recorded a verified
                # node score but did not label each question with a
                # diagnostic dimension.  Surface that real aggregate in
                # one clearly bounded cell rather than reporting the whole
                # node as unmeasured; do not copy it into other dimensions.
                score = round(float(state.mastery_score), 6)
                status = score_status(score)
                reasons = ["FORMAL_NODE_EVIDENCE_NO_DIMENSION"]
            elif state.objective_evidence_count > 0:
                score = None
                status = "needs_evidence"
                reasons = ["DIMENSION_EVIDENCE_UNAVAILABLE"]
            elif state.status.value == "self_reported":
                score = None
                status = "needs_evidence"
                reasons = ["LOW_CONFIDENCE_SELF_REPORT"]
            else:
                score = None
                status = "unassessed"
                reasons = ["NO_OBJECTIVE_EVIDENCE"]
            statuses.append(status)
            cells.append({
                "skill_node_id": node.skill_node_id,
                "dimension": dimension,
                "score": score,
                "status": status,
                "confidence": state.confidence.value,
                "objective_evidence_count": state.objective_evidence_count,
                "reason_codes": reasons,
            })
        node_states[node.skill_node_id] = statuses

    def node_status(statuses):
        if "verified_weak" in statuses:
            return "verified_weak"
        if "learning" in statuses:
            return "learning"
        if "mastered" in statuses:
            return "mastered"
        if "needs_evidence" in statuses:
            return "needs_evidence"
        return "unassessed"

    counts = {key: 0 for key in ("verified_weak", "learning", "mastered", "needs_evidence", "unassessed")}
    for statuses in node_states.values():
        counts[node_status(statuses)] += 1
    measured = sum(1 for statuses in node_states.values() if any(status in {"verified_weak", "learning", "mastered"} for status in statuses))
    return {
        "schema_version": "1.0",
        "dimensions": dimensions,
        "nodes": [
            {"skill_node_id": node.skill_node_id, "name": node.name, "stable_order": index,
             "prerequisite_ids": list(node.prerequisites)}
            for index, node in enumerate(nodes, start=1)
        ],
        "cells": cells,
        "summary": {
            **{f"{key}_count": value for key, value in counts.items()},
            "measurement_coverage": measured / len(nodes) if nodes else None,
            "measured_node_count": measured,
            "total_node_count": len(nodes),
        },
    }


def _build_resource_difficulty_curve(
    ability_projection,
    resources,
    *,
    credibility_items = None,
    credibility_summary = None,
    attempts = None,
    ordered_ability_nodes: Callable,
    utc: Callable,
) -> dict:
    ordered_nodes = ordered_ability_nodes(ability_projection.nodes if ability_projection else [])
    node_order = {item.skill_node_id: index for index, item in enumerate(ordered_nodes)}
    nodes = {item.skill_node_id: item for item in ordered_nodes}
    credibility_by_resource = {
        (item["resource_id"], item.get("resource_version")): item
        for item in (credibility_items or [])
    }
    feedback_by_resource = {}
    for attempt in attempts or []:
        resource_id = getattr(attempt, "source_resource_id", None)
        score = getattr(attempt, "overall_score", None)
        if resource_id and isinstance(score, (int, float)) and 0 <= score <= 1:
            key = (resource_id, getattr(attempt, "source_resource_version", 1))
            feedback_by_resource.setdefault(key, []).append(float(score))

    def calibrated_match(match, feedback_scores):
        """Raise difficulty only when formal feedback is below 60%."""
        if match.score is None or match.gap is None or not feedback_scores:
            return match, None, 0.0
        feedback_score = sum(feedback_scores) / len(feedback_scores)
        if feedback_score >= 0.60:
            return match, feedback_score, 0.0
        # Readiness provides context so an unprepared learner's low score
        # does not overstate the resource's actual difficulty.
        low_score_signal = (0.60 - feedback_score) * 0.20
        readiness_signal = max(0.0, match.gap) * 0.25
        adjustment = round(min(0.20, max(low_score_signal, readiness_signal)), 6)
        score = min(1.0, round(match.score + adjustment, 6))
        gap = round(score - (match.score - match.gap), 6)
        if gap < -0.15:
            status = "too_easy"
        elif gap <= 0.10:
            status = "matched"
        elif gap <= 0.25:
            status = "challenging"
        else:
            status = "too_hard"
        return match.__class__(
            score, "calibrated_history", gap, status,
            ("DIFFICULTY_CALIBRATED_FROM_LOW_FEEDBACK",),
        ), feedback_score, adjustment

    resource_points = []
    for resource in resources:
        if resource.publication_status != "published":
            continue
        target_ids = []
        if resource.learning_path_node in nodes:
            target_ids.append(resource.learning_path_node)
        target_ids.extend(point for point in resource.knowledge_points if point in nodes and point not in target_ids)
        if not target_ids:
            continue
        credibility = credibility_by_resource.get((resource.resource_id, resource.version))
        # A resource is rendered once.  Prefer its explicit learning-path
        # target; the first linked node is a deterministic legacy fallback.
        node_id = target_ids[0] if target_ids else None
        node = nodes.get(node_id) if node_id else None
        readiness = (
            node.mastery.mastery_score
            if node and node.mastery.objective_evidence_count > 0 else None
        )
        match = match_difficulty(learner_readiness=readiness, declared_difficulty=resource.difficulty)
        feedback_scores = feedback_by_resource.get((resource.resource_id, resource.version), [])
        adjusted_match, feedback_score, difficulty_adjustment = calibrated_match(match, feedback_scores)
        resource_points.append({
            "resource_id": resource.resource_id,
            "skill_node_id": node_id or "unassigned",
            "skill_name": node.name if node else "未关联能力节点",
            "point_type": "resource",
            "batch_id": resource.batch_id or resource.run_id,
            "_batch_key": resource.batch_id or resource.run_id or "__legacy__",
            "resource_name": resource.topic or resource.resource_type,
            "resource_count": 1,
            "default_resource_difficulty_score": match.score,
            "learner_readiness_score": readiness,
            "resource_difficulty_score": adjusted_match.score,
            "difficulty_gap": adjusted_match.gap,
            "match_status": adjusted_match.status,
            "confidence": node.mastery.confidence.value if node else "none",
            "difficulty_source": adjusted_match.source,
            "resource_type": resource.resource_type,
            "resource_ids": [resource.resource_id],
            "reason_codes": list(adjusted_match.reason_codes),
            "feedback_score": feedback_score,
            "feedback_count": len(feedback_scores),
            "difficulty_adjustment": difficulty_adjustment,
            "credibility_score": credibility.get("credibility_score") if credibility else None,
            "credibility_level": credibility.get("credibility_level") if credibility else None,
            "credibility_grade": credibility.get("grade") if credibility else None,
            "credibility_score_breakdown": credibility.get("score_breakdown") if credibility else None,
            "_published_at": resource.published_at or resource.created_at,
        })

    batches = {}
    for point in resource_points:
        batches.setdefault(point["_batch_key"], []).append(point)

    def batch_time(items):
        dates = [item["_published_at"] for item in items if item["_published_at"] is not None]
        return max((utc(value) for value in dates), default=datetime.min.replace(tzinfo=timezone.utc))

    ordered_batches = sorted(batches.items(), key=lambda item: (batch_time(item[1]), str(item[0])))
    latest_batch_id = ordered_batches[-1][0] if ordered_batches else None

    def average(items, key):
        values = [item[key] for item in items if isinstance(item.get(key), (int, float))]
        return round(sum(values) / len(values), 6) if values else None

    def aggregate_batch(batch_id, items):
        readiness = average(items, "learner_readiness_score")
        difficulty = average(items, "resource_difficulty_score")
        gap = average(items, "difficulty_gap")
        calibrated = any(item["difficulty_source"] == "calibrated_history" for item in items)
        if readiness is None or difficulty is None or gap is None:
            status = "not_measured"
            source = "unavailable" if difficulty is None else "calibrated_history" if calibrated else "declared_band"
        elif gap < -0.15:
            status = "too_easy"
            source = "calibrated_history" if calibrated else "declared_band"
        elif gap <= 0.10:
            status = "matched"
            source = "calibrated_history" if calibrated else "declared_band"
        elif gap <= 0.25:
            status = "challenging"
            source = "calibrated_history" if calibrated else "declared_band"
        else:
            status = "too_hard"
            source = "calibrated_history" if calibrated else "declared_band"
        reason_codes = ["BATCH_AVERAGE"]
        if calibrated:
            reason_codes.append("BATCH_INCLUDES_FEEDBACK_CALIBRATION")
        scores = [item["credibility_score"] for item in items if isinstance(item.get("credibility_score"), (int, float))]
        return {
            "resource_id": f"batch:{batch_id}",
            "skill_node_id": f"batch:{batch_id}",
            "skill_name": "历史批次平均",
            "point_type": "batch_average",
            "batch_id": None if batch_id == "__legacy__" else batch_id,
            "resource_name": "历史资源批次",
            "resource_count": len({resource_id for item in items for resource_id in item["resource_ids"]}),
            "default_resource_difficulty_score": average(items, "default_resource_difficulty_score"),
            "learner_readiness_score": readiness,
            "resource_difficulty_score": difficulty,
            "difficulty_gap": gap,
            "match_status": status,
            "confidence": "batch_average",
            "difficulty_source": source,
            "resource_type": "批次平均",
            "resource_ids": list(dict.fromkeys(resource_id for item in items for resource_id in item["resource_ids"])),
            "reason_codes": reason_codes,
            "feedback_score": average(items, "feedback_score"),
            "feedback_count": sum(item.get("feedback_count", 0) for item in items),
            "difficulty_adjustment": average(items, "difficulty_adjustment"),
            "credibility_score": average(items, "credibility_score"),
            "credibility_level": "batch_average" if scores else None,
            "credibility_grade": None,
            "credibility_score_breakdown": None,
        }

    points = []
    for batch_key, items in ordered_batches:
        if batch_key == latest_batch_id:
            points.extend(sorted(
                items,
                key=lambda item: (node_order.get(item["skill_node_id"], len(node_order)), item["resource_id"]),
            ))
        else:
            points.append(aggregate_batch(batch_key, items))
    for point in points:
        point.pop("_published_at", None)
        point.pop("_batch_key", None)
    counts = {key: 0 for key in ("too_easy", "matched", "challenging", "too_hard", "not_measured")}
    for point in points:
        counts[point["match_status"]] += 1
    measured = len(points) - counts["not_measured"]
    resource_count = len(resource_points)
    return {
        "schema_version": "1.0",
        "strategy_version": STRATEGY_VERSION,
        "points": points,
        "summary": {
            "total_point_count": len(points),
            "total_resource_count": resource_count,
            "batch_count": len(ordered_batches),
            "expanded_resource_count": sum(len(items) for batch_id, items in ordered_batches if batch_id == latest_batch_id),
            "aggregated_batch_count": max(0, len(ordered_batches) - 1),
            "measured_point_count": measured,
            "measurement_coverage": measured / len(points) if points else None,
            "credibility_strategy_version": (credibility_summary or {}).get("scoring_strategy_version"),
            "credibility_scored_count": (credibility_summary or {}).get("scored_count", 0),
            "average_credibility_score": (credibility_summary or {}).get("average_credibility_score"),
            "claim_review_passed_count": (credibility_summary or {}).get("claim_review_passed_count", 0),
            "claim_ceiling_applied_count": (credibility_summary or {}).get("claim_ceiling_applied_count", 0),
            **{f"{key}_count": value for key, value in counts.items()},
        },
    }


def _build_learning_path_graph(
    ability_projection,
    path,
    generation_options,
    *,
    current_batch_node_ids: set[str] | None = None,
    ordered_ability_nodes: Callable,
) -> dict:
    nodes = ordered_ability_nodes(ability_projection.nodes if ability_projection else [])
    known_ids = {item.skill_node_id for item in nodes}
    curriculum = {
        item.skill_node_id: item for item in (ability_projection.curriculum_nodes if ability_projection else [])
    }
    path_nodes = {}
    for item in (path.nodes if path else []):
        if item.knowledge_point_id in known_ids:
            path_nodes[item.knowledge_point_id] = item
    recommended_ids = set(generation_options.recommended_node_ids if generation_options else [])
    remedial_ids = {
        item.skill_node_id for item in (generation_options.reinforce_weakness if generation_options else [])
    }
    new_ids = {
        item.skill_node_id for item in (generation_options.learn_new_knowledge if generation_options else [])
    }
    # Only the newest effective generation batch defines "current
    # learning".  If that batch projection is unavailable, do not infer
    # currentness from mastery or curriculum status: those facts describe
    # learner progress, not membership in the latest round.
    current_ids = set(current_batch_node_ids or ())
    tier_progress = getattr(generation_options, "tier_progress", None) if generation_options else None
    highest_unlocked_tier = getattr(tier_progress, "highest_unlocked_tier", None)

    graph_nodes = []
    for index, node in enumerate(nodes, start=1):
        path_node = path_nodes.get(node.skill_node_id)
        progress = curriculum.get(node.skill_node_id)
        missing = [
            prerequisite for prerequisite in node.prerequisites
            if prerequisite in known_ids and (curriculum.get(prerequisite) is None or curriculum[prerequisite].published_resource_count <= 0)
        ]
        tier_locked = bool(
            highest_unlocked_tier is not None
            and node.tier is not None
            and node.tier > highest_unlocked_tier
        )
        placement_exempt = bool(progress and progress.placement_exempt and not progress.placement_verification_required)
        learning_history = bool(progress and (
            progress.published_resource_count > 0
            or progress.verified_attempt_count > 0
            or progress.progress_status.value in {"exposed", "verification_pending", "reinforcement_due", "completed"}
        ))
        # Placement has already covered lower tiers.  These nodes are not
        # formally completed, but they must not be presented as blocked
        # just because no learning batch was generated for them.
        # Likewise, a node that has already been published or assessed
        # retains its learning outcome when the learner temporarily
        # returns to a prerequisite tier. It is historical progress, not
        # a newly blocked future node.
        blocked = (
            not placement_exempt
            and not learning_history
            and (bool(missing) or tier_locked or bool(path_node and path_node.status.value == "locked"))
        )
        if node.skill_node_id in current_ids:
            role = "current"
        elif node.skill_node_id in remedial_ids:
            # Only the server's eligible "learned but not mastered" set is
            # actionable remediation. A weak diagnosis alone does not mean
            # the learner has first received this node's learning resource.
            role = "remedial"
        elif path_node and path_node.node_type.value == "challenge":
            role = "challenge"
        elif path_node and path_node.node_type.value == "remedial":
            role = "remedial"
        elif node.skill_node_id in recommended_ids or node.skill_node_id in new_ids:
            role = "next"
        elif node.mastery.status.value == "weak" and generation_options is None:
            # Retain the legacy read-only projection for report callers
            # that do not have the generation-option service wired.
            role = "remedial"
        elif node.mastery.status.value in {"unassessed", "self_reported"}:
            role = "verification"
        else:
            role = "prerequisite"
        reason_codes = []
        if node.mastery.status.value == "weak":
            reason_codes.append("OBJECTIVE_SCORE_BELOW_0_60")
        if node.mastery.status.value == "self_reported":
            reason_codes.append("LOW_CONFIDENCE_SELF_REPORT")
        if missing:
            reason_codes.append("PREREQUISITES_NOT_YET_EXPOSED")
        if tier_locked:
            reason_codes.append("TIER_NOT_UNLOCKED")
        if placement_exempt:
            reason_codes.append("PLACEMENT_EXEMPT")
        if path_node:
            reason_codes.append(f"PATH_NODE_{path_node.node_type.value.upper()}")
        resource_types = (
            ["讲义", "实操指南", "分阶测试题"] if role == "remedial"
            else ["复习清单", "实操指南", "分阶测试题"] if role == "current"
            else ["案例分析", "分阶测试题"] if role == "challenge"
            else ["分阶测试题"] if role == "verification"
            else ["讲义", "复习清单"]
        )
        graph_nodes.append({
            "skill_node_id": node.skill_node_id,
            "name": node.name,
            "progress_status": progress.progress_status.value if progress else (path_node.status.value if path_node else "unplanned"),
            "placement_verification_status": (
                "verification_required" if progress and progress.placement_verification_required
                else "placement_exempt" if progress and progress.placement_exempt
                else "formally_reverified" if progress and progress.placement_evidence_id
                else "not_applicable"
            ),
            "placement_exempt": placement_exempt,
            "mastery_status": node.mastery.status.value,
            "mastery_score": node.mastery.mastery_score,
            "confidence": node.mastery.confidence.value,
            "role": role,
            "is_current_batch": node.skill_node_id in current_ids,
            "blocked": blocked,
            "blocked_by_node_ids": missing,
            "recommended_resource_types": resource_types,
            "reason_codes": reason_codes or ["KNOWLEDGE_GRAPH_POSITION"],
            "stable_order": index,
            "tier": node.tier,
            "prerequisite_ids": [item for item in node.prerequisites if item in known_ids],
        })
    edges = [
        {"source_skill_node_id": edge["from"], "target_skill_node_id": edge["to"], "relation": "prerequisite"}
        for edge in (ability_projection.edges if ability_projection else [])
        if edge.get("from") in known_ids and edge.get("to") in known_ids and edge.get("from") != edge.get("to")
    ]
    order_by_id = {item["skill_node_id"]: item["stable_order"] for item in graph_nodes}
    edges.sort(key=lambda item: (
        order_by_id[item["source_skill_node_id"]],
        order_by_id[item["target_skill_node_id"]],
    ))
    # "Focus" is the learner-facing projection of the newest generation
    # batch.  Do not include merely recommended next nodes here: they are
    # available choices for a future batch, not part of this round.
    focus_ids = [
        item["skill_node_id"]
        for item in graph_nodes
        if item["skill_node_id"] in current_ids
    ]
    return {
        "schema_version": "1.0",
        "path_id": path.path_id if path else None,
        "path_version": path.version if path else None,
        "nodes": graph_nodes,
        "edges": edges,
        "current_node_ids": sorted(current_ids),
        "recommended_next_node_ids": sorted(recommended_ids),
        "focus_node_ids": focus_ids,
        "summary": {
            "total_node_count": len(graph_nodes),
            "blocked_node_count": sum(item["blocked"] for item in graph_nodes),
            "remedial_node_count": sum(item["role"] == "remedial" for item in graph_nodes),
            "eligible_remedial_node_count": len(remedial_ids),
            "verification_node_count": sum(item["role"] == "verification" for item in graph_nodes),
            "next_node_count": sum(item["role"] == "next" for item in graph_nodes),
        },
    }
