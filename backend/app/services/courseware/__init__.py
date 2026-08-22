"""Public service interface for the interactive-courseware domain."""

from app.services.courseware.service import CoursewareAdmissionError, CoursewareService

__all__ = ["CoursewareAdmissionError", "CoursewareService"]
