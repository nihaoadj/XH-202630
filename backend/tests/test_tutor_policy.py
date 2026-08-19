import pytest

from app.agents.tutor_policy import (
    allowed_pedagogy_actions,
    decide_tutor_policy,
    max_context_turns,
    resolve_hint_level,
)
from app.models.tutor import TutorSessionCreateRequest, TutorTurnSubmitRequest


def test_first_help_is_directional_and_client_cannot_set_hint_level():
    decision = decide_tutor_policy(
        turn_count=0,
        current_hint_level=0,
        user_message="为什么需要 rerank？",
    )
    assert decision.hint_level == 1
    assert set(decision.allowed_actions) == {"hint", "guided_question"}
    assert decision.reveal_full_explanation is False

    with pytest.raises(ValueError):
        TutorTurnSubmitRequest(
            client_message_id="client-0001",
            message="给我提示",
            hint_level=3,
        )


def test_repeated_confusion_escalates_to_scaffold_then_explanation():
    second = resolve_hint_level(
        turn_count=1,
        current_hint_level=1,
        user_message="前面提示我还是不懂，请再解释",
    )
    third = resolve_hint_level(
        turn_count=2,
        current_hint_level=second,
        user_message="能结合证据说明吗？",
    )
    assert second == 2
    assert allowed_pedagogy_actions(second)[0] == "scaffold"
    assert third == 3
    assert "explanation" in allowed_pedagogy_actions(third)


def test_second_turn_without_continued_confusion_does_not_force_escalation():
    assert resolve_hint_level(
        turn_count=1,
        current_hint_level=1,
        user_message="我先试着回答：它是在召回以后排序，对吗？",
    ) == 1


def test_hint_level_never_decreases_or_exceeds_server_cap():
    assert resolve_hint_level(
        turn_count=99,
        current_hint_level=3,
        user_message="继续",
        max_hint_level=2,
    ) == 2
    assert resolve_hint_level(
        turn_count=1,
        current_hint_level=2,
        user_message="我已经理解了",
    ) == 2


def test_context_window_is_bounded():
    assert max_context_turns(0) == 1
    assert max_context_turns(6) == 6
    assert max_context_turns(99) == 12


def test_session_contract_requires_trusted_source_shape():
    with pytest.raises(ValueError):
        TutorSessionCreateRequest(
            learner_id="learner-1",
            source_type="resource",
            context_type="resource_help",
        )
    with pytest.raises(ValueError):
        TutorSessionCreateRequest(
            learner_id="learner-1",
            source_type="run",
            run_id="run-1",
            context_type="question_help",
        )
