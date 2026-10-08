"""Add the versioned learner mastery projection and append-only ability events."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.shared.models import AbilityStateEventORM


MIGRATION_ID = "20260823_p0_19_learner_mastery"


def _hash(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(str(part) for part in parts).encode("utf-8")).hexdigest()


def _json(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def _status(value: object, score: float | None) -> str:
    if value in {"unassessed", "self_reported", "weak", "learning", "mastered"}:
        return str(value)
    if score is None:
        return "unassessed"
    return "weak" if score < 0.60 else "learning" if score <= 0.85 else "mastered"


def _ability_snapshot(
    value: dict,
    *,
    learner_id: str,
    knowledge_base_id: str,
    skill_node_id: str,
    evidence_id: str | None,
    occurred_at,
) -> dict[str, object]:
    score = value.get("mastery", value.get("mastery_score"))
    score = float(score) if isinstance(score, (int, float)) and 0 <= float(score) <= 1 else None
    objective_count = int(value.get("objective_evidence_count") or (1 if evidence_id else 0))
    distinct_count = int(value.get("distinct_objective_source_count") or (1 if evidence_id else 0))
    prior = value.get("self_report_prior")
    return {
        "schema_version": "2.0",
        "learner_id": learner_id,
        "knowledge_base_id": knowledge_base_id,
        "skill_node_id": skill_node_id,
        "mastery_score": score,
        "self_report_prior": prior if isinstance(prior, (int, float)) else None,
        "status": _status(value.get("status"), score),
        "confidence": value.get("confidence") or ("medium" if objective_count else "low" if prior is not None else "none"),
        "objective_evidence_count": objective_count,
        "distinct_objective_source_count": distinct_count,
        "attempt_count": int(value.get("attempt_count") or 0),
        "last_evidence_type": "learning_attempt" if evidence_id else value.get("last_evidence_type"),
        "last_evidence_id": evidence_id or value.get("last_evidence_id"),
        "row_version": max(1, int(value.get("row_version") or 1)),
        "last_updated": occurred_at.isoformat() if hasattr(occurred_at, "isoformat") else str(occurred_at),
    }


def apply_p0_19_learner_mastery_migration(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())
    if not {"knowledge_states", "learner_profiles", "rag_skill_nodes"}.issubset(tables):
        return

    expected = {
        "state_schema_version": "VARCHAR(16) NOT NULL DEFAULT '2.0'",
        "self_report_prior": "FLOAT",
        "confidence": "VARCHAR(16) NOT NULL DEFAULT 'none'",
        "objective_evidence_count": "INTEGER NOT NULL DEFAULT 0",
        "distinct_objective_source_count": "INTEGER NOT NULL DEFAULT 0",
        "last_evidence_type": "VARCHAR(32)",
        "last_evidence_id": "VARCHAR(128)",
    }
    columns = {item["name"] for item in inspect(engine).get_columns("knowledge_states")}
    with engine.begin() as connection:
        for column, ddl in expected.items():
            if column not in columns:
                connection.execute(text(f"ALTER TABLE knowledge_states ADD COLUMN {column} {ddl}"))

    AbilityStateEventORM.__table__.create(engine, checkfirst=True)

    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS learner_mastery_migration_reports ("
            "migration_id VARCHAR(128) PRIMARY KEY, mapped_count INTEGER NOT NULL, "
            "canonical_preserved_count INTEGER NOT NULL, unmapped_count INTEGER NOT NULL, "
            "unmapped_entries JSON NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ))
        has_schema_migrations = "schema_migrations" in set(inspect(engine).get_table_names())
        if has_schema_migrations:
            applied = connection.execute(
                text("SELECT 1 FROM schema_migrations WHERE migration_id=:migration_id"),
                {"migration_id": MIGRATION_ID},
            ).first()
            if applied is not None:
                return

        node_rows = connection.execute(text(
            "SELECT knowledge_base_id, node_id, name FROM rag_skill_nodes ORDER BY node_id"
        )).fetchall()
        nodes_by_base: dict[str, dict[str, str]] = {}
        ids_by_name: dict[str, dict[str, list[str]]] = {}
        for knowledge_base_id, node_id, name in node_rows:
            nodes_by_base.setdefault(knowledge_base_id, {})[node_id] = name
            ids_by_name.setdefault(knowledge_base_id, {}).setdefault(name, []).append(node_id)

        profiles = connection.execute(text(
            "SELECT learner_id, knowledge_base_id, knowledge_states FROM learner_profiles"
        )).fetchall()
        mapped_count = 0
        canonical_preserved_count = 0
        unmapped_entries: list[dict[str, str]] = []
        for learner_id, knowledge_base_id, legacy_states_raw in profiles:
            if not knowledge_base_id:
                continue
            node_names = nodes_by_base.get(knowledge_base_id, {})
            legacy_states = _json(legacy_states_raw, {})
            for legacy_key, raw_state in legacy_states.items():
                candidates = (
                    [legacy_key]
                    if legacy_key in node_names
                    else ids_by_name.get(knowledge_base_id, {}).get(legacy_key, [])
                )
                if len(candidates) != 1 or not isinstance(raw_state, dict):
                    unmapped_entries.append({
                        "learner_id": learner_id,
                        "knowledge_base_id": knowledge_base_id,
                        "legacy_key": str(legacy_key),
                        "reason": "ambiguous_name" if len(candidates) > 1 else "unknown_or_invalid",
                    })
                    continue
                node_id = candidates[0]
                exists = connection.execute(text(
                    "SELECT 1 FROM knowledge_states WHERE learner_id=:learner_id "
                    "AND knowledge_base_id=:knowledge_base_id AND skill_node_id=:skill_node_id"
                ), {"learner_id": learner_id, "knowledge_base_id": knowledge_base_id, "skill_node_id": node_id}).first()
                if exists is not None:
                    canonical_preserved_count += 1
                    continue
                raw_score = raw_state.get("score")
                score = float(raw_score) if isinstance(raw_score, (int, float)) and 0 <= float(raw_score) <= 1 else None
                state_id = f"kst_{_hash(learner_id, knowledge_base_id, node_id)[:32]}"
                event_id = f"abe_{_hash('legacy', learner_id, knowledge_base_id, node_id)[:32]}"
                state = {
                    "schema_version": "2.0", "learner_id": learner_id,
                    "knowledge_base_id": knowledge_base_id, "skill_node_id": node_id,
                    "mastery_score": score, "self_report_prior": score,
                    "status": "self_reported" if score is not None else "unassessed",
                    "confidence": "low" if score is not None else "none",
                    "objective_evidence_count": 0, "distinct_objective_source_count": 0,
                    "attempt_count": 0, "last_evidence_type": "legacy_import",
                    "last_evidence_id": event_id, "row_version": 1,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                }
                connection.execute(text(
                    "INSERT INTO knowledge_states (state_id, learner_id, knowledge_base_id, skill_node_id, "
                    "mastery_score, status, evidence, attempt_count, row_version, state_schema_version, "
                    "self_report_prior, confidence, objective_evidence_count, distinct_objective_source_count, "
                    "last_evidence_type, last_evidence_id) VALUES (:state_id,:learner_id,:knowledge_base_id,"
                    ":skill_node_id,:score,:status,:evidence,0,1,'2.0',:prior,:confidence,0,0,'legacy_import',:event_id)"
                ), {
                    "state_id": state_id, "learner_id": learner_id, "knowledge_base_id": knowledge_base_id,
                    "skill_node_id": node_id, "score": score, "prior": score,
                    "status": state["status"], "confidence": state["confidence"],
                    "evidence": json.dumps([event_id]), "event_id": event_id,
                })
                connection.execute(text(
                    "INSERT INTO ability_state_events (event_id,schema_version,learner_id,knowledge_base_id,"
                    "skill_node_id,source_type,source_id,source_hash,observed_score,verified,before_state,"
                    "after_state,occurred_at) VALUES (:event_id,'1.0',:learner_id,:knowledge_base_id,"
                    ":skill_node_id,'legacy_import',:source_id,:source_hash,:score,0,NULL,:after_state,:occurred_at)"
                ), {
                    "event_id": event_id, "learner_id": learner_id, "knowledge_base_id": knowledge_base_id,
                    "skill_node_id": node_id, "source_id": f"legacy:{learner_id}",
                    "source_hash": _hash(legacy_key, raw_state), "score": score,
                    "after_state": json.dumps(state, ensure_ascii=False),
                    "occurred_at": datetime.now(timezone.utc),
                })
                mapped_count += 1

        # Existing formal attempts are independently persisted objective evidence.
        if {"knowledge_state_mutations", "learning_attempts"}.issubset(tables):
            mutation_rows = connection.execute(text(
                "SELECT m.learner_id,p.knowledge_base_id,m.knowledge_point_id,m.attempt_id,"
                "m.before_state,m.after_state,a.submitted_at FROM knowledge_state_mutations m "
                "JOIN learner_profiles p ON p.learner_id=m.learner_id "
                "JOIN learning_attempts a ON a.attempt_id=m.attempt_id ORDER BY a.submitted_at,m.mutation_id"
            )).fetchall()
            for learner_id, knowledge_base_id, node_id, attempt_id, before_state, after_state, occurred_at in mutation_rows:
                if node_id not in nodes_by_base.get(knowledge_base_id, {}):
                    continue
                event_id = f"abe_{_hash('attempt', learner_id, attempt_id, node_id)[:32]}"
                exists = connection.execute(text(
                    "SELECT 1 FROM ability_state_events WHERE event_id=:event_id"
                ), {"event_id": event_id}).first()
                if exists is None:
                    after = _json(after_state, {})
                    before = _json(before_state, {})
                    after_ability = _ability_snapshot(
                        after,
                        learner_id=learner_id,
                        knowledge_base_id=knowledge_base_id,
                        skill_node_id=node_id,
                        evidence_id=event_id,
                        occurred_at=occurred_at,
                    )
                    before_ability = _ability_snapshot(
                        before,
                        learner_id=learner_id,
                        knowledge_base_id=knowledge_base_id,
                        skill_node_id=node_id,
                        evidence_id=None,
                        occurred_at=occurred_at,
                    ) if before else None
                    connection.execute(text(
                        "INSERT INTO ability_state_events (event_id,schema_version,learner_id,knowledge_base_id,"
                        "skill_node_id,source_type,source_id,source_hash,observed_score,verified,before_state,"
                        "after_state,occurred_at) VALUES (:event_id,'1.0',:learner_id,:knowledge_base_id,"
                        ":skill_node_id,'learning_attempt',:source_id,:source_hash,:score,1,:before_state,"
                        ":after_state,:occurred_at)"
                    ), {
                        "event_id": event_id, "learner_id": learner_id, "knowledge_base_id": knowledge_base_id,
                        "skill_node_id": node_id, "source_id": attempt_id, "source_hash": _hash(attempt_id),
                        "score": after.get("mastery"),
                        "before_state": json.dumps(before_ability, ensure_ascii=False) if before_ability else None,
                        "after_state": json.dumps(after_ability, ensure_ascii=False), "occurred_at": occurred_at,
                    })

            connection.execute(text(
                "UPDATE knowledge_states SET objective_evidence_count=(SELECT COUNT(*) FROM ability_state_events e "
                "WHERE e.learner_id=knowledge_states.learner_id AND e.knowledge_base_id=knowledge_states.knowledge_base_id "
                "AND e.skill_node_id=knowledge_states.skill_node_id AND e.verified=1), "
                "distinct_objective_source_count=(SELECT COUNT(DISTINCT e.source_id) FROM ability_state_events e "
                "WHERE e.learner_id=knowledge_states.learner_id AND e.knowledge_base_id=knowledge_states.knowledge_base_id "
                "AND e.skill_node_id=knowledge_states.skill_node_id AND e.verified=1), "
                "confidence=CASE WHEN (SELECT COUNT(*) FROM ability_state_events e WHERE e.learner_id=knowledge_states.learner_id "
                "AND e.skill_node_id=knowledge_states.skill_node_id AND e.verified=1)>=3 AND "
                "(SELECT COUNT(DISTINCT e.source_id) FROM ability_state_events e WHERE e.learner_id=knowledge_states.learner_id "
                "AND e.skill_node_id=knowledge_states.skill_node_id AND e.verified=1)>=2 THEN 'high' "
                "WHEN (SELECT COUNT(*) FROM ability_state_events e WHERE e.learner_id=knowledge_states.learner_id "
                "AND e.skill_node_id=knowledge_states.skill_node_id AND e.verified=1)>=1 THEN 'medium' "
                "WHEN self_report_prior IS NOT NULL THEN 'low' ELSE 'none' END"
            ))

        # Compatibility fields are a one-way projection of the canonical table.
        # Existing canonical rows always win over legacy profile JSON values.
        for learner_id, knowledge_base_id, _legacy_states_raw in profiles:
            if not knowledge_base_id:
                continue
            node_names = nodes_by_base.get(knowledge_base_id, {})
            name_counts: dict[str, int] = {}
            for name in node_names.values():
                name_counts[name] = name_counts.get(name, 0) + 1
            rows = connection.execute(text(
                "SELECT skill_node_id,mastery_score,status,self_report_prior,confidence,"
                "objective_evidence_count,distinct_objective_source_count,attempt_count,"
                "last_evidence_type,last_evidence_id,row_version,last_updated "
                "FROM knowledge_states WHERE learner_id=:learner_id AND knowledge_base_id=:knowledge_base_id "
                "ORDER BY skill_node_id"
            ), {"learner_id": learner_id, "knowledge_base_id": knowledge_base_id}).fetchall()
            projected: dict[str, dict[str, object]] = {}
            theory_scores: dict[str, float] = {}
            weak_points: list[str] = []
            strong_points: list[str] = []
            for row in rows:
                (
                    node_id, score, status, prior, confidence, objective_count,
                    source_count, attempt_count, last_type, last_id, row_version, last_updated,
                ) = row
                projected[node_id] = {
                    "score": score,
                    "status": status or _status(None, score),
                    "evidence": [last_id] if last_id else [],
                    "last_updated": last_updated.isoformat() if hasattr(last_updated, "isoformat") else last_updated,
                    "self_report_prior": prior,
                    "confidence": confidence or "none",
                    "objective_evidence_count": objective_count or 0,
                    "distinct_objective_source_count": source_count or 0,
                    "attempt_count": attempt_count or 0,
                    "last_evidence_type": last_type,
                    "last_evidence_id": last_id,
                    "row_version": row_version or 1,
                }
                if (objective_count or 0) > 0 and score is not None:
                    theory_scores[node_id] = round(float(score) * 100, 1)
                    name = node_names.get(node_id, node_id)
                    label = f"{name} [{node_id}]" if name_counts.get(name, 0) > 1 else name
                    if status == "weak":
                        weak_points.append(label)
                    elif status == "mastered":
                        strong_points.append(label)
            connection.execute(text(
                "UPDATE learner_profiles SET knowledge_states=:knowledge_states,theory_scores=:theory_scores,"
                "weak_points=:weak_points,strong_points=:strong_points WHERE learner_id=:learner_id"
            ), {
                "knowledge_states": json.dumps(projected, ensure_ascii=False),
                "theory_scores": json.dumps(theory_scores, ensure_ascii=False),
                "weak_points": json.dumps(weak_points, ensure_ascii=False),
                "strong_points": json.dumps(strong_points, ensure_ascii=False),
                "learner_id": learner_id,
            })

        report_exists = connection.execute(text(
            "SELECT 1 FROM learner_mastery_migration_reports WHERE migration_id=:migration_id"
        ), {"migration_id": MIGRATION_ID}).first()
        if report_exists is None:
            connection.execute(text(
                "INSERT INTO learner_mastery_migration_reports "
                "(migration_id,mapped_count,canonical_preserved_count,unmapped_count,unmapped_entries) "
                "VALUES (:migration_id,:mapped_count,:canonical_preserved_count,:unmapped_count,:unmapped_entries)"
            ), {
                "migration_id": MIGRATION_ID,
                "mapped_count": mapped_count,
                "canonical_preserved_count": canonical_preserved_count,
                "unmapped_count": len(unmapped_entries),
                "unmapped_entries": json.dumps(unmapped_entries, ensure_ascii=False),
            })

        if has_schema_migrations:
            connection.execute(
                text("INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"),
                {"migration_id": MIGRATION_ID},
            )
