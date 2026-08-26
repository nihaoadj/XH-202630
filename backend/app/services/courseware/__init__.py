"""Public service interface for the interactive-courseware domain."""

__all__ = ["CandidateReleaseCoordinator", "CoursewareAdmissionError", "CoursewareEventProjector", "CoursewareService"]


def __getattr__(name: str):
    if name == "CandidateReleaseCoordinator":
        from app.services.courseware.release import CandidateReleaseCoordinator
        return CandidateReleaseCoordinator
    if name in {"CoursewareAdmissionError", "CoursewareService"}:
        from app.services.courseware.service import (
            CoursewareAdmissionError,
            CoursewareService,
        )
        return {
            "CoursewareAdmissionError": CoursewareAdmissionError,
            "CoursewareService": CoursewareService,
        }[name]
    if name == "CoursewareEventProjector":
        from app.services.courseware.events import CoursewareEventProjector
        return CoursewareEventProjector
    raise AttributeError(name)
