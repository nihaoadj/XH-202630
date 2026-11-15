"""Task labels use exact source identity and never expose frozen private content."""

import json
from types import SimpleNamespace

from app.agents.resource_workflows.interactive_courseware.source import source_display_summaries
from app.db.courseware.repository import MemoryCoursewareRepository
from app.agents.resource_workflows.interactive_courseware.workflow import InteractiveCoursewareWorkflow
from app.models.courseware.contracts import CoursewareJobCreateRequest
from app.models.learning_documents.schemas import LearningResource


def test_queued_courseware_has_original_source_title_and_node_on_create_list_detail():
    source = LearningResource(resource_id="guide", learner_id="owner", resource_type="实操指南", topic="Chunk切分",
                             difficulty="中级", knowledge_points=["chunking"], version=2, source_refs=[],
                             content_text="# 切分实战\n\n私有正文不出现在摘要", practice_guide_payload={"title": "固定长度与段落切分实战"})
    resources = SimpleNamespace(get=lambda rid: source if rid == "guide" else None)
    wf = InteractiveCoursewareWorkflow(MemoryCoursewareRepository(), resources, object())
    job = wf.create_job(CoursewareJobCreateRequest(learner_id="owner", source_resource_ids=["guide"]))
    expected = {"resource_id": "guide", "resource_type": "实操指南", "title": "固定长度与段落切分实战",
                "topic": "Chunk切分", "knowledge_points": ["chunking"], "version": 2}
    assert job.source_summary[0].model_dump() == expected
    assert wf.get_job(job.run_id).source_summary[0].model_dump() == expected
    assert wf.get_job_detail(job.run_id).source_summary[0].model_dump() == expected
    assert "私有正文" not in json.dumps(job.model_dump(), ensure_ascii=False, default=str)


def test_frozen_source_labels_win_over_live_latest_version_and_do_not_load_it():
    def forbidden(_rid):
        raise AssertionError("frozen label must not query latest version")

    job = {"learner_id": "owner", "source_resource_ids": ["old-guide"], "source_snapshots": [{
        "resource_id": "old-guide", "resource_type": "实操指南", "version": 1, "topic": "旧节点",
        "knowledge_points": ["old-node"], "practice_guide_payload": {"title": "已冻结的原资源名"},
        "content_review_evidence": [{"text": "不可公开的依据"}],
    }, {"resource_id": "unrelated", "resource_type": "复习清单", "topic": "其他资源"}]}
    result = source_display_summaries(SimpleNamespace(get=forbidden), job)
    assert result == [{"resource_id": "old-guide", "resource_type": "实操指南", "title": "已冻结的原资源名",
                       "version": 1, "topic": "旧节点", "knowledge_points": ["old-node"]}]
    assert "不可公开" not in json.dumps(result, ensure_ascii=False)


def test_source_labels_skip_missing_or_foreign_owner_and_use_markdown_heading():
    source = LearningResource(resource_id="checklist", learner_id="owner", resource_type="复习清单", topic="复习节点",
                             difficulty="初级", knowledge_points=[], source_refs=[], content_text="# 原始清单标题\n私有正文")
    service = SimpleNamespace(get=lambda rid: source if rid == "checklist" else None)
    job = {"learner_id": "owner", "source_resource_ids": ["missing", "checklist"], "source_snapshots": []}
    assert source_display_summaries(service, job)[0]["title"] == "原始清单标题"
    assert source_display_summaries(service, {**job, "learner_id": "other"}) == []
