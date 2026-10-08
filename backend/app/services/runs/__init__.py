"""Workflow run and event query service domain."""

__all__ = [
    "DurableWorkflowRunner",
    "RecordedNode",
    "recorded_node",
    "WorkflowArtifactRecorder",
]


def __getattr__(name: str):
    if name == "DurableWorkflowRunner":
        from app.services.runs.durable_workflow_runner import DurableWorkflowRunner

        return DurableWorkflowRunner
    if name in {"RecordedNode", "recorded_node"}:
        from app.services.runs.recorded_node import RecordedNode, recorded_node

        return {"RecordedNode": RecordedNode, "recorded_node": recorded_node}[name]
    if name == "WorkflowArtifactRecorder":
        from app.services.runs.workflow_artifact_recorder import WorkflowArtifactRecorder

        return WorkflowArtifactRecorder
    raise AttributeError(name)
