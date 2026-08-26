"""Public interactive-courseware workflow package."""

__all__ = ["InteractiveCoursewareWorkflow", "CoursewareSceneWorker"]


def __getattr__(name: str):
    if name == "InteractiveCoursewareWorkflow":
        from app.agents.resource_workflows.interactive_courseware.workflow import (
            InteractiveCoursewareWorkflow,
        )
        return InteractiveCoursewareWorkflow
    if name == "CoursewareSceneWorker":
        from app.agents.resource_workflows.interactive_courseware.worker import CoursewareSceneWorker
        return CoursewareSceneWorker
    raise AttributeError(name)
