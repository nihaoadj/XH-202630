"""Deterministic server-side progression for Socratic Tutor assistance."""

from __future__ import annotations

from dataclasses import dataclass


_CONTINUED_CONFUSION_MARKERS = (
    "还是不懂",
    "仍然不懂",
    "没懂",
    "不明白",
    "再解释",
    "前面提示",
    "依然",
    "still",
    "don't understand",
    "do not understand",
)


@dataclass(frozen=True)
class TutorPolicyDecision:
    hint_level: int
    allowed_actions: tuple[str, ...]
    reveal_full_explanation: bool


def max_context_turns(configured: int = 6) -> int:
    """Return the bounded recent-history window accepted by the Tutor prompt."""

    return max(1, min(int(configured), 12))


def allowed_pedagogy_actions(hint_level: int) -> tuple[str, ...]:
    normalized = max(0, min(int(hint_level), 3))
    return {
        0: ("guided_question",),
        1: ("hint", "guided_question"),
        2: ("scaffold", "guided_question", "hint"),
        3: ("explanation", "check_understanding"),
    }[normalized]


def should_reveal_full_explanation(hint_level: int) -> bool:
    return int(hint_level) >= 3


def resolve_hint_level(
    *,
    turn_count: int,
    current_hint_level: int,
    user_message: str,
    max_hint_level: int = 3,
) -> int:
    """Resolve the next level without accepting a client-provided override.

    The first effective help request receives a directional hint. A second turn
    escalates only when the learner explicitly remains confused. From the third
    help turn onward a grounded explanation is allowed. Levels never decrease.
    """

    cap = max(0, min(int(max_hint_level), 3))
    current = max(0, min(int(current_hint_level), cap))
    count = max(0, int(turn_count))
    normalized_message = user_message.strip().casefold()
    continued_confusion = any(
        marker.casefold() in normalized_message
        for marker in _CONTINUED_CONFUSION_MARKERS
    )

    if count == 0:
        proposed = 1
    elif count == 1:
        proposed = 2 if continued_confusion else max(current, 1)
    else:
        proposed = 3
    return min(cap, max(current, proposed))


def decide_tutor_policy(
    *,
    turn_count: int,
    current_hint_level: int,
    user_message: str,
    max_hint_level: int = 3,
) -> TutorPolicyDecision:
    level = resolve_hint_level(
        turn_count=turn_count,
        current_hint_level=current_hint_level,
        user_message=user_message,
        max_hint_level=max_hint_level,
    )
    return TutorPolicyDecision(
        hint_level=level,
        allowed_actions=allowed_pedagogy_actions(level),
        reveal_full_explanation=should_reveal_full_explanation(level),
    )
