"""Small versioned migrations required for additive schema upgrades."""

from app.db.migrations.p0_04 import apply_p0_04_migration
from app.db.migrations.p0_05 import apply_p0_05_migration
from app.db.migrations.p0_06 import apply_p0_06_migration
from app.db.migrations.p0_07 import apply_p0_07_migration
from app.db.migrations.p0_07_feedback import apply_p0_07_feedback_migration
from app.db.migrations.p0_09 import apply_p0_09_migration
from app.db.migrations.p0_10 import apply_p0_10_migration
from app.db.migrations.p0_11_resource_batches import apply_p0_11_resource_batches_migration
from app.db.migrations.p0_12_superseded_generation_jobs import apply_p0_12_superseded_generation_jobs_migration
from app.db.migrations.p0_13_resource_workflow import apply_p0_13_resource_workflow_migration
from app.db.migrations.p0_14_profile_skill_node_labels import apply_p0_14_profile_skill_node_labels_migration
from app.db.migrations.p0_15_courseware_execution import apply_p0_15_courseware_execution_migration
from app.db.migrations.p0_16_courseware_learning_events import apply_p0_16_courseware_learning_events_migration
from app.db.migrations.p0_17_courseware_request_options import apply_p0_17_courseware_request_options_migration
from app.db.migrations.p0_18_courseware_batch_integrity import apply_p0_18_courseware_batch_integrity_migration
from app.db.migrations.p0_19_learner_mastery import apply_p0_19_learner_mastery_migration
from app.db.migrations.p0_20_curriculum_progress import apply_p0_20_curriculum_progress_migration
from app.db.migrations.p0_21_learning_tiers import apply_p0_21_learning_tiers_migration
from app.db.migrations.p0_22_review_practice import apply_p0_22_review_practice_migration
from app.db.migrations.p0_23_curriculum_attempt_id import apply_p0_23_curriculum_attempt_id_migration
from app.db.migrations.p0_24_correction_package_batches import apply_p0_24_correction_package_batches_migration
from app.db.migrations.p0_25_practice_guide_json import apply_p0_25_practice_guide_json_migration
from app.db.migrations.p0_26_mastery_evidence_gate import apply_p0_26_mastery_evidence_gate_migration
from app.db.migrations.p0_27_assessment_evidence import apply_p0_27_assessment_evidence_migration
from app.db.migrations.p0_28_placement_reverification import apply_p0_28_placement_reverification_migration
from app.db.migrations.p0_29_feedback_decision_tiers import apply_p0_29_feedback_decision_tiers_migration
from app.db.migrations.p0_30_feedback_followup_multi_run import apply_p0_30_feedback_followup_multi_run_migration
from app.db.migrations.p0_31_claim_user_publication import apply_p0_31_claim_user_publication_migration
from app.db.migrations.p0_32_review_status import apply_p0_32_review_status_migration
from app.db.migrations.p0_33_chunk_skill_node_mappings import apply_p0_33_chunk_skill_node_mappings_migration
from app.db.migrations.tutor import apply_tutor_migration

__all__ = [
    "apply_p0_04_migration",
    "apply_p0_05_migration",
    "apply_p0_06_migration",
    "apply_p0_07_migration",
    "apply_p0_07_feedback_migration",
    "apply_p0_09_migration",
    "apply_p0_10_migration",
    "apply_p0_11_resource_batches_migration",
    "apply_p0_12_superseded_generation_jobs_migration",
    "apply_p0_13_resource_workflow_migration",
    "apply_p0_14_profile_skill_node_labels_migration",
    "apply_p0_15_courseware_execution_migration",
    "apply_p0_16_courseware_learning_events_migration",
    "apply_p0_17_courseware_request_options_migration",
    "apply_p0_18_courseware_batch_integrity_migration",
    "apply_p0_19_learner_mastery_migration",
    "apply_p0_20_curriculum_progress_migration",
    "apply_p0_21_learning_tiers_migration",
    "apply_p0_22_review_practice_migration",
    "apply_p0_23_curriculum_attempt_id_migration",
    "apply_p0_24_correction_package_batches_migration",
    "apply_p0_25_practice_guide_json_migration",
    "apply_p0_26_mastery_evidence_gate_migration",
    "apply_p0_27_assessment_evidence_migration",
    "apply_p0_28_placement_reverification_migration",
    "apply_p0_29_feedback_decision_tiers_migration",
    "apply_p0_30_feedback_followup_multi_run_migration",
    "apply_p0_31_claim_user_publication_migration",
    "apply_p0_32_review_status_migration",
    "apply_p0_33_chunk_skill_node_mappings_migration",
    "apply_tutor_migration",
]
