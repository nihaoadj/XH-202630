"""Versioned single-node correction content and server-owned package contracts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.shared.persistence import canonical_hash

MAX_RENDERED_CHARACTERS = 14000
MAX_TEXT_CHARACTERS = 4000
MAX_SHORT_TEXT_CHARACTERS = 500
MAX_GOALS = MAX_OVERVIEW_ITEMS = 4
MAX_ERROR_PATTERNS = MAX_COMPARISONS = MAX_SELF_CHECKS = MAX_CRITERIA = MAX_REVIEW_ACTIONS = 6
MAX_CONCEPT_REPAIRS = MAX_FAILED_DIMENSIONS = 16
MIN_EXAMPLE_STEPS, MAX_EXAMPLE_STEPS = 2, 8
MAX_HINTS = 3
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TEXT_CHARACTERS)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_SHORT_TEXT_CHARACTERS)]


class CorrectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ErrorPattern(CorrectionModel):
    mistaken_view: Text
    explanation: Text


class ConceptRepair(CorrectionModel):
    point: ShortText
    explanation: Text


class Comparison(CorrectionModel):
    incorrect_statement: Text
    correct_statement: Text
    explanation: Text


class ExampleStep(CorrectionModel):
    action: Text
    explanation: Text


class WorkedExample(CorrectionModel):
    scenario: Text
    task: Text
    steps: list[ExampleStep] = Field(min_length=MIN_EXAMPLE_STEPS, max_length=MAX_EXAMPLE_STEPS)
    takeaway: Text


class CorrectionExercise(CorrectionModel):
    scenario: Text
    question: Text
    hints: list[Text] = Field(max_length=MAX_HINTS)
    reference_answer: Text
    explanation: Text
    self_check_points: list[Text] = Field(min_length=1, max_length=MAX_SELF_CHECKS)


class CorrectionExercises(CorrectionModel):
    guided: CorrectionExercise
    similar: CorrectionExercise
    transfer: CorrectionExercise


class CorrectionUnit(CorrectionModel):
    error_patterns: list[ErrorPattern] = Field(min_length=1, max_length=MAX_ERROR_PATTERNS)
    concept_repair: list[ConceptRepair] = Field(min_length=1, max_length=MAX_CONCEPT_REPAIRS)
    comparisons: list[Comparison] = Field(min_length=1, max_length=MAX_COMPARISONS)
    worked_example: WorkedExample
    exercises: CorrectionExercises


class LayeredFeedback(CorrectionModel):
    foundation: Text
    proficient: Text
    advanced: Text


class CorrectionPackageContentV1(CorrectionModel):
    """The complete model output: no personal state or model-selected node."""

    training_goals: list[Text] = Field(min_length=1, max_length=MAX_GOALS)
    focus_overview: list[Text] = Field(min_length=1, max_length=MAX_OVERVIEW_ITEMS)
    unit: CorrectionUnit
    layered_feedback: LayeredFeedback
    mastery_criteria: list[Text] = Field(min_length=1, max_length=MAX_CRITERIA)
    next_review_actions: list[Text] = Field(min_length=1, max_length=MAX_REVIEW_ACTIONS)
    summary: Text


class CorrectionTarget(CorrectionModel):
    node_id: ShortText
    node_name: ShortText
    mastery_status: Literal["weak", "learning", "unknown"]
    failed_dimensions: list[ShortText] = Field(max_length=MAX_FAILED_DIMENSIONS)


class CorrectionLearningStatus(CorrectionModel):
    target: CorrectionTarget


class CorrectionProvenance(CorrectionModel):
    run_id: ShortText
    focus_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    renderer_version: Literal["correction-markdown-v1"] = "correction-markdown-v1"


class CorrectionGenerationContractV1(CorrectionModel):
    version: Literal["correction-json-generation-v1"] = "correction-json-generation-v1"
    schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    renderer_version: Literal["correction-markdown-v1"] = "correction-markdown-v1"
    max_output_tokens: Literal[32768] = 32768
    timeout_seconds: Literal[300] = 300
    max_attempts: Literal[2] = 2


class CorrectionPackageV1(CorrectionModel):
    """Canonical server assembly; deliberately distinct from the model schema."""

    schema_version: Literal["correction-package-v1"] = "correction-package-v1"
    title: ShortText
    learning_status: CorrectionLearningStatus
    provenance: CorrectionProvenance
    content: CorrectionPackageContentV1
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_identity(self):
        if canonical_hash(self.model_dump(mode="json", exclude={"payload_hash"})) != self.payload_hash:
            raise ValueError("correction package hash mismatch")
        return self


def assemble_correction_package(*, content, title, target, run_id, focus_snapshot_hash):
    """Assemble trusted context separately; never accept the model's envelope."""
    body = CorrectionPackageContentV1.model_validate(content)
    status = CorrectionLearningStatus(target=CorrectionTarget.model_validate(target))
    provenance = CorrectionProvenance(run_id=run_id, focus_snapshot_hash=focus_snapshot_hash)
    values = {
        "schema_version": "correction-package-v1", "title": title,
        "learning_status": status.model_dump(mode="json"),
        "provenance": provenance.model_dump(mode="json"), "content": body.model_dump(mode="json"),
    }
    # Normalize the title before hashing, matching Pydantic's string contract.
    values["title"] = title.strip()
    return CorrectionPackageV1.model_validate({**values, "payload_hash": canonical_hash(values)})


class CorrectionExercisesV2(CorrectionModel):
    guided: CorrectionExercise
    transfer: CorrectionExercise


class CorrectionUnitV2(CorrectionModel):
    error_patterns: list[ErrorPattern] = Field(min_length=1, max_length=MAX_ERROR_PATTERNS)
    concept_repair: list[ConceptRepair] = Field(min_length=1, max_length=MAX_CONCEPT_REPAIRS)
    comparisons: list[Comparison] = Field(min_length=1, max_length=MAX_COMPARISONS)
    exercises: CorrectionExercisesV2


class CorrectionPackageContentV2(CorrectionPackageContentV1):
    unit: CorrectionUnitV2


class CorrectionProvenanceV2(CorrectionModel):
    run_id: ShortText
    focus_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    renderer_version: Literal["correction-markdown-v2"] = "correction-markdown-v2"


class CorrectionPackageV2(CorrectionPackageV1):
    schema_version: Literal["correction-package-v2"] = "correction-package-v2"
    provenance: CorrectionProvenanceV2
    content: CorrectionPackageContentV2


class CorrectionGenerationContractV2(CorrectionGenerationContractV1):
    version: Literal["correction-json-generation-v2"] = "correction-json-generation-v2"
    renderer_version: Literal["correction-markdown-v2"] = "correction-markdown-v2"


def parse_correction_package(value):
    if isinstance(value, (CorrectionPackageV1, CorrectionPackageV2)):
        value = value.model_dump(mode="json")
    version = value.get("schema_version") if isinstance(value, dict) else None
    schema = {"correction-package-v1": CorrectionPackageV1,
              "correction-package-v2": CorrectionPackageV2}.get(version)
    if schema is None:
        raise ValueError("unknown correction package version")
    return schema.model_validate(value)


def parse_correction_generation_contract(value):
    version = value.get("version") if isinstance(value, dict) else None
    schema = {"correction-json-generation-v1": CorrectionGenerationContractV1,
              "correction-json-generation-v2": CorrectionGenerationContractV2}.get(version)
    if schema is None:
        raise ValueError("unknown correction generation version")
    return schema.model_validate(value)


def assemble_compact_correction_package(*, content, title, target, run_id, focus_snapshot_hash):
    body = CorrectionPackageContentV2.model_validate(content)
    status = CorrectionLearningStatus(target=CorrectionTarget.model_validate(target))
    provenance = CorrectionProvenanceV2(run_id=run_id, focus_snapshot_hash=focus_snapshot_hash)
    values = {"schema_version": "correction-package-v2", "title": title.strip(),
              "learning_status": status.model_dump(mode="json"),
              "provenance": provenance.model_dump(mode="json"), "content": body.model_dump(mode="json")}
    return CorrectionPackageV2.model_validate({**values, "payload_hash": canonical_hash(values)})
