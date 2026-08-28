"""Shared protocol and bounded invocation helpers for specialized resource Agents."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.core.security.errors import ApplicationError, ErrorCode
from app.core.llm.gateway import LLMGateway
from app.models.shared.agent_contracts import (
    GeneratedArtifact,
    ResourceArtifactMetadata,
    ResourceGenerationContext,
    ResourceRepresentation,
    ResourceSpec,
)
from app.models.shared.llm import LLMCallContext, LLMCallResult


ArtifactOutputT = TypeVar("ArtifactOutputT", bound=BaseModel)


@runtime_checkable
class ResourceGenerationAgent(Protocol):
    """Interface implemented by every registered resource generation Agent."""

    resource_type: str
    agent_name: str
    prompt_version: str
    artifact_format: str

    def generate(
        self,
        spec: ResourceSpec,
        context: ResourceGenerationContext,
        *,
        llm_gateway: LLMGateway,
        **kwargs: Any,
    ) -> GeneratedArtifact: ...

    def validate(
        self,
        artifact: GeneratedArtifact,
        *,
        spec: ResourceSpec,
        context: ResourceGenerationContext,
    ) -> GeneratedArtifact: ...


class BaseResourceGenerationAgent(ABC, Generic[ArtifactOutputT]):
    """Provider-neutral base class for one evidence-scoped resource invocation."""

    resource_type: str
    agent_name: str
    prompt_version: str
    artifact_format: str
    default_max_output_tokens: int = 8192
    temperature: float = 0.2

    def _ensure_route(self, spec: ResourceSpec) -> None:
        if spec.resource_type != self.resource_type:
            raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)

    def _representation_spec(
        self,
        spec: ResourceSpec,
        representation: ResourceRepresentation,
    ):
        for item in spec.representations:
            if item.representation == representation:
                return item
        raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)

    def _scoped_evidence(
        self,
        spec: ResourceSpec,
        context: ResourceGenerationContext,
    ):
        by_id = {item.evidence_id: item for item in context.evidence}
        if any(evidence_id not in by_id for evidence_id in spec.evidence_ids):
            raise ApplicationError(ErrorCode.EVIDENCE_SCOPE_VIOLATION, status_code=422)
        return [by_id[evidence_id] for evidence_id in spec.evidence_ids]

    def common_prompt_payload(
        self,
        spec: ResourceSpec,
        context: ResourceGenerationContext,
    ) -> dict[str, Any]:
        evidence = self._scoped_evidence(spec, context)
        prompt_constraints = dict(context.constraints)
        # The prior artifact is exposed in its own clearly delimited field;
        # do not duplicate a potentially large document inside constraints.
        prompt_constraints.pop("previous_version_content", None)
        payload = {
            "topic": context.topic,
            "resource_spec_id": spec.resource_spec_id,
            "resource_type": spec.resource_type,
            "display_title": f"{context.topic} · {spec.resource_type}",
            "learning_objective": spec.learning_objective,
            "knowledge_points": spec.knowledge_points,
            "difficulty": spec.difficulty,
            "learner_profile_summary": context.learner_profile_summary,
            "learning_path": context.learning_path,
            "continuation_context": context.continuation_context,
            "constraints": prompt_constraints,
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "source": item.locator.source_path,
                    "section": item.locator.section,
                    "excerpt": item.excerpt,
                }
                for item in evidence
            ],
        }
        revision_feedback = context.constraints.get("revision_feedback")
        if revision_feedback:
            payload["revision_feedback"] = revision_feedback
            payload["previous_version_content"] = context.constraints.get(
                "previous_version_content", ""
            )
            payload["revision_guidance"] = (
                "这是一次审核返工。以下 previous_version_content 是上一版本原文；"
                "仅修改审核反馈指出的问题，保留其余正确内容；"
                "必须逐条落实 revision_instructions，并重新检查对应知识点覆盖。"
            )
        return payload

    @staticmethod
    def json_payload(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def invoke(
        self,
        *,
        spec: ResourceSpec,
        context: ResourceGenerationContext,
        llm_gateway: LLMGateway,
        messages: list[BaseMessage],
        output_schema: type[ArtifactOutputT],
        representation: ResourceRepresentation,
        max_output_tokens: int | None = None,
        request_timeout_seconds: float | None = None,
    ) -> LLMCallResult[ArtifactOutputT]:
        self._ensure_route(spec)
        representation_spec = self._representation_spec(spec, representation)
        option_node = {
            ("TextResourceAgent", "text"): "text_resource_agent",
            ("AssessmentAgent", "text"): "assessment_agent",
            ("PracticeGuideAgent", "text"): "practice_guide_agent",
        }.get((self.agent_name, representation), "generator")
        options = llm_gateway.options_for(option_node, temperature=self.temperature)
        requested_budget = max_output_tokens or representation_spec.max_output_tokens
        # The immutable ResourceSpec declares a safe minimum for its
        # representation.  The gateway may carry a larger, agent-specific
        # budget (notably the canonical Markdown phase of a practice guide).
        # Do not accidentally shrink that dedicated budget back to the generic
        # text representation limit.
        options = options.model_copy(update={
            "max_output_tokens": max(requested_budget, options.max_output_tokens),
            **({"request_timeout_seconds": request_timeout_seconds} if request_timeout_seconds is not None else {}),
        })
        return llm_gateway.invoke_structured(
            messages=messages,
            output_schema=output_schema,
            context=LLMCallContext(
                run_id=context.run_id,
                step_id=context.step_id,
                node_name=self.agent_name,
                schema_name=output_schema.__name__,
                generation_attempt=context.generation_attempt,
                workflow_deadline_at=context.workflow_deadline_at,
            ),
            options=options,
        )

    def invoke_plain_text(
        self,
        *,
        spec: ResourceSpec,
        context: ResourceGenerationContext,
        llm_gateway: LLMGateway,
        messages: list[BaseMessage],
        representation: ResourceRepresentation,
        max_output_tokens: int | None = None,
        strict_max_output_tokens: bool = False,
        request_timeout_seconds: float | None = None,
        max_attempts: int | None = None,
    ) -> LLMCallResult[str]:
        """Generate a long text artifact without serialising it into JSON."""

        self._ensure_route(spec)
        representation_spec = self._representation_spec(spec, representation)
        option_node = {
            ("TextResourceAgent", "text"): "text_resource_agent",
        }.get((self.agent_name, representation), "generator")
        options = llm_gateway.options_for(option_node, temperature=self.temperature)
        requested_budget = max_output_tokens or representation_spec.max_output_tokens
        # Most legacy text agents may use a deployment-wide long-document
        # allowance.  A tightly structured artifact can instead opt into an
        # explicit ceiling: otherwise a 6–10k-character package silently
        # inherits the 32k-token resource budget and becomes far more likely
        # to stall or time out at the provider.
        option_updates: dict[str, Any] = {
            "max_output_tokens": (
                requested_budget
                if strict_max_output_tokens
                else max(requested_budget, options.max_output_tokens)
            ),
        }
        if request_timeout_seconds is not None:
            option_updates["request_timeout_seconds"] = request_timeout_seconds
        if max_attempts is not None:
            option_updates["max_attempts"] = max_attempts
        options = options.model_copy(update=option_updates)
        return llm_gateway.invoke_plain_text(
            messages=messages,
            context=LLMCallContext(
                run_id=context.run_id,
                step_id=context.step_id,
                node_name=self.agent_name,
                schema_name="plain_markdown",
                generation_attempt=context.generation_attempt,
                workflow_deadline_at=context.workflow_deadline_at,
            ),
            options=options,
        )

    def metadata(
        self,
        *,
        spec: ResourceSpec,
        representation: ResourceRepresentation,
        source_evidence_ids: list[str],
        validation_status: str = "validated",
    ) -> ResourceArtifactMetadata:
        return ResourceArtifactMetadata(
            resource_spec_id=spec.resource_spec_id,
            resource_family_id=spec.resource_family_id,
            resource_type=spec.resource_type,
            representation=representation,
            agent_name=self.agent_name,
            prompt_version=self.prompt_version,
            artifact_format=self.artifact_format,
            validation_status=validation_status,
            source_evidence_ids=source_evidence_ids,
        )

    @abstractmethod
    def generate(
        self,
        spec: ResourceSpec,
        context: ResourceGenerationContext,
        *,
        llm_gateway: LLMGateway,
        **kwargs: Any,
    ) -> GeneratedArtifact:
        raise NotImplementedError

    @abstractmethod
    def validate(
        self,
        artifact: GeneratedArtifact,
        *,
        spec: ResourceSpec,
        context: ResourceGenerationContext,
    ) -> GeneratedArtifact:
        raise NotImplementedError
