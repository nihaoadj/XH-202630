from datetime import datetime, timezone
from types import SimpleNamespace

from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.audit.memory import MemoryAuditRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.feedback.feedback_loop import KnowledgePointAttemptResult
from app.models.learners.history import DiagnosticRunRecord
from app.models.learners.mastery import (
    AbilityMasteryStateV2,
    AbilityNodeProjectionV1,
    AbilityNodeSummaryV1,
    AbilityStatus,
    AbilityNodesResponseV1,
    CurriculumNodeProgressV1,
    CurriculumProgressStatus,
)
from app.models.learning_documents.schemas import LearningResource
from app.services.reports import reports as reports_module
from app.services.reports.reports import ReportService


def _state(node_id, *, score, status, objective_count, confidence="medium"):
    return AbilityMasteryStateV2(
        learner_id="learner", knowledge_base_id="kb", skill_node_id=node_id,
        mastery_score=score, status=status, confidence=confidence,
        objective_evidence_count=objective_count,
    )


def _projection():
    foundation = AbilityNodeProjectionV1(
        skill_node_id="foundation", name="基础", prerequisites=[], children=["advanced"],
        mastery=_state("foundation", score=0.4, status="weak", objective_count=1),
    )
    advanced = AbilityNodeProjectionV1(
        skill_node_id="advanced", name="进阶", prerequisites=["foundation"], children=[],
        mastery=_state("advanced", score=None, status="unassessed", objective_count=0, confidence="none"),
    )
    return AbilityNodesResponseV1(
        learner_id="learner", knowledge_base_id="kb", as_of_profile_version=1,
        summary=AbilityNodeSummaryV1(
            total_count=2, mastered_count=0, learning_count=0, weak_count=1,
            self_reported_count=0, unassessed_count=1, medium_or_high_confidence_count=1,
        ),
        nodes=[foundation, advanced], edges=[{"from": "foundation", "to": "advanced"}],
    )


def test_assessment_conclusions_distinguish_baseline_from_confirmed_mastery():
    service = ReportService(MemoryResourceRepository(), MemoryFeedbackRepository())
    node = SimpleNamespace(skill_node_id="skill-a", mastery=_state(
        "skill-a", score=0.9, status="learning", objective_count=1, confidence="low",
    ))
    projection = SimpleNamespace(nodes=[node])
    event = SimpleNamespace(
        verified=True, evidence_eligible=True, source_type=SimpleNamespace(value="diagnosis"),
        skill_node_id="skill-a", source_id="diagnosis-1", evidence_id="event-1",
        assessment_session_id="session-1", assessment_form_id="form-1",
        question_ids=["q1", "q2", "q3"], covered_dimensions=["concept", "scenario", "misconception"],
        scoring_audit_status="single_pass", observed_score=0.9,
        occurred_at=datetime.now(timezone.utc),
    )
    baseline = service._assessment_conclusions([event], projection)["skill-a"]
    assert baseline["conclusion"] == "baseline_observation"
    assert baseline["formal_session_count"] == 1

    confirmed_node = SimpleNamespace(skill_node_id="skill-a", mastery=_state(
        "skill-a", score=0.9, status="mastered", objective_count=2, confidence="high",
    ))
    second = SimpleNamespace(**{**event.__dict__, "source_id": "attempt-1", "evidence_id": "event-2",
                                "assessment_session_id": "session-2", "assessment_form_id": "form-2",
                                "question_ids": ["q4", "q5", "q6"]})
    confirmed = service._assessment_conclusions([event, second], SimpleNamespace(nodes=[confirmed_node]))["skill-a"]
    assert confirmed["conclusion"] == "confirmed_mastery"
    assert confirmed["independent_form_count"] == 2


def test_full_self_report_can_be_confirmed_after_one_passing_assessment():
    service = ReportService(MemoryResourceRepository(), MemoryFeedbackRepository())
    node = SimpleNamespace(skill_node_id="skill-a", mastery=_state(
        "skill-a", score=0.84, status="mastered", objective_count=1, confidence="low",
    ))
    node.mastery = node.mastery.model_copy(update={"self_report_prior": 1.0})
    projection = SimpleNamespace(nodes=[node])
    event = SimpleNamespace(
        verified=True, evidence_eligible=True, source_type=SimpleNamespace(value="diagnosis"),
        skill_node_id="skill-a", source_id="diagnosis-1", evidence_id="event-1",
        assessment_session_id="session-1", assessment_form_id="form-1",
        question_ids=["q1", "q2", "q3"], covered_dimensions=["concept", "scenario", "misconception"],
        scoring_audit_status="single_pass", observed_score=0.8,
        occurred_at=datetime.now(timezone.utc),
    )

    conclusion = service._assessment_conclusions([event], projection)["skill-a"]
    assert conclusion["conclusion"] == "confirmed_mastery"
    assert conclusion["trust_status"] == "high"


def _service():
    return ReportService(MemoryResourceRepository(), MemoryFeedbackRepository())


def _credibility_resource(*, source_refs, review_id="review", review_status="approved"):
    return SimpleNamespace(
        resource_id="resource", resource_type="讲义", topic="主题", run_id="run", batch_id="batch",
        version=1, published_at=datetime(2026, 8, 25, tzinfo=timezone.utc), publication_status="published",
        representation="text", review_id=review_id, review_status=review_status, source_refs=source_refs,
        difficulty_match=None, claim_metric_status="legacy_unavailable",
    )


def _verified_ref(*, knowledge_base_id="kb"):
    return SimpleNamespace(
        provenance_status="verified", evidence_id="evidence", knowledge_base_id=knowledge_base_id,
        doc_id="doc", document_version="v1", chunk_id="chunk",
    )


def test_resource_credibility_scores_reuse_review_claim_and_source_evidence(monkeypatch):
    service = _service()
    service.audit_repo = SimpleNamespace(get_review_by_resource=lambda _resource_id: SimpleNamespace(
        review_id="review", status="approved", issues=[],
    ))
    service._claims_for_resource = lambda _resource: ([object()], [object()])
    monkeypatch.setattr(reports_module, "compute_claim_metric", lambda _claims, _judgements: SimpleNamespace(
        metric_status=SimpleNamespace(value="complete"), claim_hallucination_rate=0.0,
        factual_claim_total=1, supported_claim_total=1, contradicted_claim_total=0,
        not_in_evidence_claim_total=0, incomplete_claim_total=0,
    ))

    result = service._resource_credibility([_credibility_resource(source_refs=[_verified_ref()])], knowledge_base_id="kb")
    item = result["items"][0]
    assert item["credibility_score"] == 99.0
    assert item["credibility_level"] == "high"
    assert item["grade"] == "trusted"
    assert item["score_breakdown"] == {
        "publication_review_score": 40.0,
        "source_traceability_score": 50.0,
        "claim_review_score": 10.0,
        "claim_review_passed": True,
        "score_ceiling": 99.0,
        "ceiling_applied": False,
        "reason_codes": [],
    }
    assert result["summary"]["average_credibility_score"] == 99.0


def test_resource_credibility_normalizes_workflow_approve_status(monkeypatch):
    audit = MemoryAuditRepository()
    review_id = audit.save_review(
        "resource",
        {"review_id": "review", "status": "approve", "passed": True, "issues": []},
        "run",
    )
    assert audit.get_review_by_resource("resource").status == "approved"
    assert audit.list_reviews_by_run("run")[0]["status"] == "approved"

    service = _service()
    service.audit_repo = audit
    service._claims_for_resource = lambda _resource: ([object()], [object()])
    monkeypatch.setattr(reports_module, "compute_claim_metric", lambda _claims, _judgements: SimpleNamespace(
        metric_status=SimpleNamespace(value="complete"), claim_hallucination_rate=0.0,
        factual_claim_total=1, supported_claim_total=1, contradicted_claim_total=0,
        not_in_evidence_claim_total=0, incomplete_claim_total=0,
    ))

    item = service._resource_credibility(
        [_credibility_resource(source_refs=[_verified_ref()], review_id=review_id)],
        knowledge_base_id="kb",
    )["items"][0]
    assert item["publication_review"]["review_status"] == "approved"
    assert item["publication_review"]["status"] == "passed"
    assert item["score_breakdown"]["publication_review_score"] == 40.0
    assert item["credibility_score"] == 99.0


def test_resource_credibility_caps_claim_missing_and_hard_failures(monkeypatch):
    service = _service()
    service.audit_repo = SimpleNamespace(get_review_by_resource=lambda _resource_id: SimpleNamespace(
        review_id="review", status="approved", issues=[],
    ))
    service._claims_for_resource = lambda _resource: ([], [])

    capped = service._resource_credibility([_credibility_resource(source_refs=[_verified_ref()])], knowledge_base_id="kb")["items"][0]
    assert capped["credibility_score"] == 80.0
    assert capped["credibility_level"] == "good"
    assert capped["score_breakdown"]["claim_review_passed"] is False
    assert capped["score_breakdown"]["score_ceiling"] == 80.0
    assert capped["score_breakdown"]["ceiling_applied"] is True
    assert "CLAIM_REVIEW_NOT_MEASURED" in capped["score_breakdown"]["reason_codes"]

    partial = service._resource_credibility([_credibility_resource(source_refs=[_verified_ref(), SimpleNamespace(provenance_status="legacy", evidence_id=None, knowledge_base_id=None, doc_id="doc", document_version=None, chunk_id=None)])], knowledge_base_id="kb")["items"][0]
    assert partial["score_breakdown"]["source_traceability_score"] == 25.0
    assert partial["credibility_score"] == 65.0

    cross_base = service._resource_credibility([_credibility_resource(source_refs=[_verified_ref(knowledge_base_id="other")])], knowledge_base_id="kb")["items"][0]
    assert cross_base["score_breakdown"]["source_traceability_score"] == 0.0
    assert cross_base["credibility_level"] == "attention"
    assert "SOURCE_REF_CROSS_KNOWLEDGE_BASE" in cross_base["reason_codes"]


def test_resource_difficulty_curve_reuses_credibility_projection():
    resource = LearningResource(
        resource_id="foundation-guide", learner_id="learner", topic="基础", resource_type="讲义",
        difficulty="中级", content_text="", knowledge_points=["foundation"], source_refs=[],
        learning_path_node="foundation", publication_status="published",
    )
    credibility = {
        "resource_id": "foundation-guide", "resource_version": resource.version,
        "credibility_score": 80.0, "credibility_level": "good", "grade": "trusted",
        "score_breakdown": {"publication_review_score": 40.0, "source_traceability_score": 50.0,
                            "claim_review_score": 0.0, "claim_review_passed": False,
                            "score_ceiling": 80.0, "ceiling_applied": True, "reason_codes": []},
    }
    curve = _service()._build_resource_difficulty_curve(
        _projection(), [resource], credibility_items=[credibility],
        credibility_summary={"scoring_strategy_version": "audit-40/source-50/claim-10/v1", "scored_count": 1,
                             "average_credibility_score": 80.0, "claim_review_passed_count": 0,
                             "claim_ceiling_applied_count": 1},
    )
    point = curve["points"][0]
    assert point["credibility_score"] == credibility["credibility_score"]
    assert point["credibility_score_breakdown"] == credibility["score_breakdown"]
    assert curve["summary"]["average_credibility_score"] == 80.0


def test_learning_node_mastery_map_covers_all_nodes_without_dimension_axes():
    result = _service()._build_learning_node_mastery_map(
        _projection(),
        {
            "foundation": {
                "conclusion": "needs_reinforcement",
                "trust_status": "medium",
                "formal_session_count": 2,
                "independent_form_count": 2,
                "high_score_session_count": 0,
            },
            "advanced": {
                "conclusion": "unassessed",
                "trust_status": "none",
            },
        },
    )

    assert [item["skill_node_id"] for item in result["nodes"]] == ["foundation", "advanced"]
    foundation = result["nodes"][0]
    assert foundation["mastery_score"] == 0.4
    assert foundation["next_action"] == "remediate"
    assert foundation["independent_session_count"] == 2
    assert "dimensions" not in foundation
    assert result["summary"]["total_node_count"] == 2


def test_blind_spot_map_only_projects_dimension_scores_with_exact_question_trace():
    attempt = SimpleNamespace(
        attempt_id="attempt", submitted_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        metadata={"question_trace": [{
            "question_id": "q1", "skill_node_id": "foundation", "diagnostic_dimension": "concept",
        }]},
        knowledge_point_results=[KnowledgePointAttemptResult(
            knowledge_point_id="foundation", question_ids=["q1"], correct_count=0, total_count=1,
        )],
    )
    result = _service()._build_blind_spot_map(_projection(), [attempt])
    concept = next(item for item in result["cells"] if item["skill_node_id"] == "foundation" and item["dimension"] == "concept")
    scenario = next(item for item in result["cells"] if item["skill_node_id"] == "foundation" and item["dimension"] == "scenario")
    unassessed = next(item for item in result["cells"] if item["skill_node_id"] == "advanced" and item["dimension"] == "concept")
    assert concept["score"] == 0.0
    assert concept["status"] == "verified_weak"
    assert scenario["score"] is None
    assert scenario["status"] == "needs_evidence"
    assert unassessed["score"] is None
    assert unassessed["status"] == "unassessed"


def test_blind_spot_map_surfaces_verified_node_score_when_legacy_questions_lack_dimension():
    attempt = SimpleNamespace(
        attempt_id="attempt", submitted_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        metadata={"question_trace": [{"question_id": "q1", "skill_node_id": "foundation"}]},
        knowledge_point_results=[KnowledgePointAttemptResult(
            knowledge_point_id="foundation", question_ids=["q1"], correct_count=0, total_count=1,
        )],
    )

    result = _service()._build_blind_spot_map(_projection(), [attempt])

    concept = next(item for item in result["cells"] if item["skill_node_id"] == "foundation" and item["dimension"] == "concept")
    scenario = next(item for item in result["cells"] if item["skill_node_id"] == "foundation" and item["dimension"] == "scenario")
    assert concept["score"] == 0.4
    assert concept["status"] == "verified_weak"
    assert concept["reason_codes"] == ["FORMAL_NODE_EVIDENCE_NO_DIMENSION"]
    assert scenario["score"] is None
    assert result["summary"]["measured_node_count"] == 1


def test_blind_spot_map_consumes_deidentified_initial_diagnosis_trace():
    run = DiagnosticRunRecord(
        diagnostic_result_id="diagnosis-1", learner_id="learner", knowledge_base_id="kb",
        ability_level="初级", raw_result={"blind_spot_trace": [{
            "question_id": "diagnostic-q1", "skill_node_id": "foundation",
            "diagnostic_dimension": "concept", "correct": False, "measurement_status": "measured",
        }]},
        created_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )

    result = _service()._build_blind_spot_map(_projection(), [], [run])

    concept = next(item for item in result["cells"] if item["skill_node_id"] == "foundation" and item["dimension"] == "concept")
    assert concept["score"] == 0.0
    assert concept["status"] == "verified_weak"


def test_report_node_order_respects_prerequisites_then_tier():
    base = SimpleNamespace(skill_node_id="base", name="基础", tier=1, prerequisites=[])
    independent = SimpleNamespace(skill_node_id="independent", name="同阶", tier=1, prerequisites=[])
    advanced = SimpleNamespace(skill_node_id="advanced", name="进阶", tier=2, prerequisites=["base"])

    ordered = ReportService._ordered_ability_nodes([advanced, independent, base])

    assert [item.skill_node_id for item in ordered] == ["base", "independent", "advanced"]


def test_report_revision_changes_when_the_client_projection_changes(monkeypatch):
    service = _service()
    parts = {"profile": "profile", "mastery": "mastery"}

    previous_revision = service._revision(parts, 30)
    monkeypatch.setattr(reports_module, "REPORT_PROJECTION_VERSION", "4.1-test-projection")

    assert service._revision(parts, 30) != previous_revision


def test_resource_curve_and_path_graph_do_not_invent_readiness_or_prerequisites():
    resources = [
        LearningResource(
            resource_id="foundation-guide", learner_id="learner", topic="基础", resource_type="讲义",
            difficulty="中级", content_text="", knowledge_points=["foundation"], source_refs=[],
            learning_path_node="foundation", publication_status="published",
        ),
        LearningResource(
            resource_id="advanced-guide", learner_id="learner", topic="进阶", resource_type="讲义",
            difficulty="未知", content_text="", knowledge_points=["advanced"], source_refs=[],
            learning_path_node="advanced", publication_status="published",
        ),
    ]
    service = _service()
    curve = service._build_resource_difficulty_curve(_projection(), resources)
    foundation = next(item for item in curve["points"] if item["resource_id"] == "foundation-guide")
    advanced = next(item for item in curve["points"] if item["resource_id"] == "advanced-guide")
    assert foundation["learner_readiness_score"] == 0.4
    assert foundation["match_status"] == "challenging"
    assert advanced["learner_readiness_score"] is None
    assert advanced["resource_difficulty_score"] is None
    assert advanced["match_status"] == "not_measured"

    graph = service._build_learning_path_graph(_projection(), None, None)
    base = next(item for item in graph["nodes"] if item["skill_node_id"] == "foundation")
    next_node = next(item for item in graph["nodes"] if item["skill_node_id"] == "advanced")
    assert base["role"] == "remedial"
    assert next_node["blocked"] is True
    assert next_node["blocked_by_node_ids"] == ["foundation"]
    assert graph["edges"] == [{"source_skill_node_id": "foundation", "target_skill_node_id": "advanced", "relation": "prerequisite"}]


def test_resource_difficulty_curve_expands_latest_batch_and_averages_history():
    def resource(resource_id, batch_id, difficulty, published_at):
        return LearningResource(
            resource_id=resource_id, learner_id="learner", topic=resource_id, resource_type="讲义",
            difficulty=difficulty, content_text="", knowledge_points=["foundation"], source_refs=[],
            learning_path_node="foundation", publication_status="published", batch_id=batch_id,
            run_id=f"run-{batch_id}", published_at=published_at,
        )

    resources = [
        resource("old-a", "batch-old", "初级", datetime(2026, 8, 20, tzinfo=timezone.utc)),
        resource("old-b", "batch-old", "高级", datetime(2026, 8, 20, tzinfo=timezone.utc)),
        resource("new-a", "batch-new", "中级", datetime(2026, 8, 25, tzinfo=timezone.utc)),
        resource("new-b", "batch-new", "高级", datetime(2026, 8, 25, tzinfo=timezone.utc)),
    ]

    curve = _service()._build_resource_difficulty_curve(_projection(), resources)

    assert [point["resource_id"] for point in curve["points"]] == [
        "batch:batch-old", "new-a", "new-b",
    ]
    history = curve["points"][0]
    assert history["point_type"] == "batch_average"
    assert history["resource_count"] == 2
    assert history["resource_ids"] == ["old-a", "old-b"]
    assert history["learner_readiness_score"] == 0.4
    assert history["resource_difficulty_score"] == 0.6
    assert history["difficulty_gap"] == 0.2
    assert curve["summary"]["total_point_count"] == 3
    assert curve["summary"]["total_resource_count"] == 4
    assert curve["summary"]["aggregated_batch_count"] == 1
    assert curve["summary"]["expanded_resource_count"] == 2


def test_resource_difficulty_curve_calibrates_up_from_low_formal_feedback():
    resource = LearningResource(
        resource_id="feedback-resource", learner_id="learner", topic="反馈资源", resource_type="讲义",
        difficulty="中级", content_text="", knowledge_points=["foundation"], source_refs=[],
        learning_path_node="foundation", publication_status="published", batch_id="batch-current",
    )
    attempt = SimpleNamespace(
        source_resource_id="feedback-resource", source_resource_version=1, overall_score=0.2,
    )

    point = _service()._build_resource_difficulty_curve(
        _projection(), [resource], attempts=[attempt],
    )["points"][0]

    assert point["default_resource_difficulty_score"] == 0.65
    assert point["resource_difficulty_score"] > point["default_resource_difficulty_score"]
    assert point["difficulty_source"] == "calibrated_history"
    assert point["feedback_score"] == 0.2
    assert point["feedback_count"] == 1
    assert point["difficulty_adjustment"] > 0
    assert "DIFFICULTY_CALIBRATED_FROM_LOW_FEEDBACK" in point["reason_codes"]


def test_learning_path_current_nodes_use_latest_effective_generation_batch():
    old_job = SimpleNamespace(
        run_id="run-old", batch_id="batch-old", learner_id="learner", knowledge_base_id="kb",
        job_status="completed", superseded_by_run_id=None,
        created_at=datetime(2026, 8, 20, tzinfo=timezone.utc), started_at=None, finished_at=None,
        request_payload={"target_skill_nodes": ["foundation"]},
    )
    latest_job = SimpleNamespace(
        run_id="run-latest", batch_id="batch-latest", learner_id="learner", knowledge_base_id="kb",
        job_status="completed", superseded_by_run_id=None,
        created_at=datetime(2026, 8, 21, tzinfo=timezone.utc), started_at=None, finished_at=None,
        request_payload={"constraints": {"learner_focus_snapshot": {"adopted_node_ids": ["advanced", "foundation"]}}},
    )
    ignored_failed = SimpleNamespace(
        run_id="run-failed", batch_id="batch-failed", learner_id="learner", knowledge_base_id="kb",
        job_status="failed", superseded_by_run_id=None,
        created_at=datetime(2026, 8, 22, tzinfo=timezone.utc), started_at=None, finished_at=None,
        request_payload={"target_skill_nodes": ["foundation"]},
    )
    service = ReportService(
        MemoryResourceRepository(), MemoryFeedbackRepository(),
        generation_job_repo=SimpleNamespace(list_by_learner=lambda _learner_id: [ignored_failed, latest_job, old_job]),
    )
    profile = SimpleNamespace(learner_id="learner", knowledge_base_id="kb")
    projection = _projection().model_copy(update={"curriculum_nodes": [
        CurriculumNodeProgressV1(
            learner_id="learner", knowledge_base_id="kb", skill_node_id="foundation",
            progress_status=CurriculumProgressStatus.SCHEDULED, scheduled_run_id="run-old",
        ),
    ]})

    current_ids = service._latest_active_batch_target_ids(profile)
    graph = service._build_learning_path_graph(_projection(), None, None, current_batch_node_ids=current_ids)

    assert current_ids == {"advanced", "foundation"}
    assert graph["current_node_ids"] == ["advanced", "foundation"]
    advanced = next(item for item in graph["nodes"] if item["skill_node_id"] == "advanced")
    foundation = next(item for item in graph["nodes"] if item["skill_node_id"] == "foundation")
    assert advanced["role"] == "current"
    assert advanced["is_current_batch"] is True
    assert foundation["role"] == "current"
    assert foundation["is_current_batch"] is True
    assert graph["focus_node_ids"] == ["foundation", "advanced"]


def test_learning_path_focus_only_contains_latest_batch_nodes():
    generation_options = SimpleNamespace(
        recommended_node_ids=["advanced"],
        reinforce_weakness=[],
        learn_new_knowledge=[SimpleNamespace(skill_node_id="advanced")],
    )
    graph = _service()._build_learning_path_graph(
        _projection(), None, generation_options, current_batch_node_ids={"foundation"},
    )

    assert graph["current_node_ids"] == ["foundation"]
    assert graph["focus_node_ids"] == ["foundation"]
    advanced = next(item for item in graph["nodes"] if item["skill_node_id"] == "advanced")
    assert advanced["role"] == "next"
    assert advanced["is_current_batch"] is False


def test_learning_path_does_not_infer_current_from_learning_mastery():
    learning = _projection().model_copy(update={
        "nodes": [
            _projection().nodes[0].model_copy(update={
                "mastery": _projection().nodes[0].mastery.model_copy(update={
                    "status": AbilityStatus.LEARNING,
                }),
            }),
            _projection().nodes[1],
        ],
    })

    graph = _service()._build_learning_path_graph(
        learning, None, None, current_batch_node_ids=set(),
    )

    foundation = next(item for item in graph["nodes"] if item["skill_node_id"] == "foundation")
    assert foundation["role"] != "current"
    assert foundation["is_current_batch"] is False


def test_learning_path_graph_exposes_reverification_then_formal_reverification():
    pending = CurriculumNodeProgressV1(
        learner_id="learner", knowledge_base_id="kb", skill_node_id="foundation",
        placement_exempt=True, placement_verification_required=True,
    )
    projection = _projection().model_copy(update={"curriculum_nodes": [pending]})
    service = _service()
    graph = service._build_learning_path_graph(projection, None, None)
    node = next(item for item in graph["nodes"] if item["skill_node_id"] == "foundation")
    assert node["placement_verification_status"] == "verification_required"

    reverified = pending.model_copy(update={
        "placement_exempt": False, "placement_verification_required": False,
        "placement_evidence_id": "placement-evidence",
        "progress_status": CurriculumProgressStatus.COMPLETED,
    })
    graph = service._build_learning_path_graph(
        _projection().model_copy(update={"curriculum_nodes": [reverified]}), None, None,
    )
    node = next(item for item in graph["nodes"] if item["skill_node_id"] == "foundation")
    assert node["placement_verification_status"] == "formally_reverified"


def test_learning_path_graph_locks_unlearned_higher_tier_nodes():
    projection = _projection().model_copy(update={
        "nodes": [_projection().nodes[0], _projection().nodes[1].model_copy(update={"tier": 2})],
    })
    options = SimpleNamespace(
        tier_progress=SimpleNamespace(highest_unlocked_tier=1),
        recommended_node_ids=[], reinforce_weakness=[], learn_new_knowledge=[],
    )

    graph = _service()._build_learning_path_graph(
        projection, None, options, current_batch_node_ids=set(),
    )

    advanced = next(item for item in graph["nodes"] if item["skill_node_id"] == "advanced")
    assert advanced["progress_status"] == "unplanned"
    assert advanced["role"] == "verification"
    assert advanced["blocked"] is True
    assert "TIER_NOT_UNLOCKED" in advanced["reason_codes"]


def test_learning_path_graph_renders_initially_exempt_lower_tier_as_available_history():
    projection = _projection().model_copy(update={
        "nodes": [
            _projection().nodes[0],
            _projection().nodes[1].model_copy(update={"tier": 2}),
        ],
        "curriculum_nodes": [CurriculumNodeProgressV1(
            learner_id="learner", knowledge_base_id="kb", skill_node_id="foundation",
            placement_exempt=True,
        )],
    })
    options = SimpleNamespace(
        tier_progress=SimpleNamespace(highest_unlocked_tier=2),
        recommended_node_ids=[], reinforce_weakness=[], learn_new_knowledge=[],
    )

    graph = _service()._build_learning_path_graph(
        projection, None, options, current_batch_node_ids=set(),
    )

    foundation = next(item for item in graph["nodes"] if item["skill_node_id"] == "foundation")
    assert foundation["placement_exempt"] is True
    assert foundation["placement_verification_status"] == "placement_exempt"
    assert foundation["blocked"] is False
    assert "PLACEMENT_EXEMPT" in foundation["reason_codes"]


def test_learning_path_graph_keeps_failed_assessment_visible_during_prerequisite_review():
    failed = CurriculumNodeProgressV1(
        learner_id="learner", knowledge_base_id="kb", skill_node_id="advanced",
        progress_status=CurriculumProgressStatus.REINFORCEMENT_DUE,
        published_resource_count=4, verified_attempt_count=1,
    )
    projection = _projection().model_copy(update={
        "nodes": [_projection().nodes[0], _projection().nodes[1].model_copy(update={"tier": 2})],
        "curriculum_nodes": [failed],
    })
    options = SimpleNamespace(
        tier_progress=SimpleNamespace(highest_unlocked_tier=2),
        recommended_node_ids=[], reinforce_weakness=[], learn_new_knowledge=[],
    )

    graph = _service()._build_learning_path_graph(
        projection, None, options, current_batch_node_ids=set(),
    )

    advanced = next(item for item in graph["nodes"] if item["skill_node_id"] == "advanced")
    assert advanced["progress_status"] == "reinforcement_due"
    assert advanced["blocked"] is False


def test_weakness_groups_keep_ready_and_maintained_nodes_out_of_evidence_risk_groups():
    priorities = [
        SimpleNamespace(skill_node_id="ready", priority_group="ready_uncovered", reason_codes=[], mastery_score=None, confidence=SimpleNamespace(value="none")),
        SimpleNamespace(skill_node_id="maintained", priority_group="maintain_mastery", reason_codes=[], mastery_score=.9, confidence=SimpleNamespace(value="high")),
        SimpleNamespace(skill_node_id="blocked", priority_group="blocked_uncovered", reason_codes=["PREREQUISITE_REQUIRED"], mastery_score=None, confidence=SimpleNamespace(value="none")),
    ]
    groups = ReportService._weakness_groups(priorities, {"blocked": "被阻塞节点"})
    assert groups["verified_weak"] == []
    assert groups["regressing_learning"] == []
    assert groups["needs_evidence"][0]["skill_node_id"] == "blocked"
