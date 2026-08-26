from app.services.courseware.source import _practice_source_blocks
from app.services.courseware.composition import resource_courseware_title


def test_practice_snapshot_preserves_headings_code_and_paragraphs_as_semantic_blocks():
    blocks = _practice_source_blocks(
        "## 准备\n说明。\n\n### 步骤 1：建立索引\n先读取文档。\n\n```python\nbuild_index()\n```\n\n核对结果。",
        "guide-1",
    )

    assert [item["kind"] for item in blocks] == ["heading", "paragraph", "heading", "paragraph", "code", "paragraph"]
    assert blocks[2]["text"] == "### 步骤 1：建立索引"
    assert blocks[4]["text"].startswith("```python")


def test_resource_courseware_title_puts_the_resource_type_in_the_primary_heading():
    snapshots = [{"resource_type": "实操指南", "title": "RAG 最小闭环"}]

    assert resource_courseware_title("RAG 最小闭环", snapshots) == "实操指南｜RAG 最小闭环"
    assert resource_courseware_title("实操指南｜RAG 最小闭环", snapshots) == "实操指南｜RAG 最小闭环"
