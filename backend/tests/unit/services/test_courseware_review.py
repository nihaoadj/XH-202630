from app.services.courseware.review import quality_review


def _document(value: str) -> dict:
    return {
        "scenes": [
            {"kind": "intro", "title": "开始", "blocks": ["说明"]},
            {"kind": "practice", "title": "操作", "blocks": [value]},
            {"kind": "recap", "title": "总结", "blocks": ["完成"]},
        ]
    }


def test_fenced_python_comparisons_are_not_treated_as_html():
    issues = quality_review(_document("```python\nif score < limit:\n    return count > 0\n```"))
    assert not any(issue["code"] == "UNSAFE_LEARNER_CONTENT" for issue in issues)


def test_real_markup_and_urls_remain_blocked_outside_code():
    markup = quality_review(_document("请执行 <script>alert(1)</script>"))
    url = quality_review(_document("请访问 https://example.invalid"))
    assert any(issue["code"] == "UNSAFE_LEARNER_CONTENT" for issue in markup)
    assert any(issue["code"] == "UNSAFE_LEARNER_CONTENT" for issue in url)


def test_urls_in_a_source_bound_code_example_are_not_treated_as_learner_markup():
    issues = quality_review(_document("```python\nbase_url = 'https://api.example.invalid'\n```"))
    assert not any(issue["code"] == "UNSAFE_LEARNER_CONTENT" for issue in issues)


def test_structured_practice_reflection_is_the_guide_recap():
    issues = quality_review({
        "scenes": [
            {"kind": "intro", "title": "开始", "blocks": ["说明"]},
            {
                "kind": "practice", "page_role": "practice_workspace",
                "practice_json_schema_version": "3.0", "practice_variant": "reflect",
                "title": "复盘与小结", "blocks": ["完成复盘"],
            },
        ]
    })
    assert not any(issue["code"] == "MISSING_RECAP" for issue in issues)
