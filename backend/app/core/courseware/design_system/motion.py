from __future__ import annotations

from app.models.courseware.design import MotionSpec

MOTIONS = {
    "subtle": {"motion_id": "subtle", "version": "1.0", "reduced_motion": False},
    "reduced": {"motion_id": "reduced", "version": "1.0", "reduced_motion": True},
}


def resolve_motion(motion_id: str | None, *, prefers_reduced_motion: bool = False) -> MotionSpec:
    if prefers_reduced_motion or motion_id == "reduced":
        return MotionSpec(motion_id="reduced", reduced_motion=True)
    return MotionSpec(motion_id="subtle")


__all__ = ["MOTIONS", "resolve_motion"]
