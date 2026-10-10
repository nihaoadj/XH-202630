from app.agents.resource_workflows.interactive_courseware import contracts as legacy
from app.models.courseware import content
from app.agents.resource_workflows.learning_documents.state import AgentState
from app.models.shared.workflow import WorkflowState


def test_content_compatibility_exports_keep_model_identity():
    for name in legacy.__all__:
        assert getattr(legacy, name) is getattr(content, name), name
    assert AgentState is WorkflowState
