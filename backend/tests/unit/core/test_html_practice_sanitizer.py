import pytest

from app.core.html_practice_sanitizer import (
    HtmlPracticeAdmissionError,
    has_forbidden_html_constructs,
    sanitize_html_practice_fragment,
)


def test_html_practice_sanitizer_repairs_executable_constructs():
    result = sanitize_html_practice_fragment(
        '<section data-source-step-id="step-01" onclick="steal()">'
        '<script>alert(1)</script><iframe src="https://invalid"></iframe>'
        '<a href="javascript:alert(1)">验证</a><input type="checkbox">完成'
        '</section>'
    )

    assert 'data-source-step-id="step-01"' in result.html_fragment
    assert "checkbox" in result.html_fragment
    assert not has_forbidden_html_constructs(result.html_fragment)
    assert {
        "blocked_tag_removed",
        "event_attribute_removed",
        "unsafe_url_removed",
    } <= set(result.warnings)


def test_html_practice_sanitizer_repairs_unclosed_allowed_tags():
    result = sanitize_html_practice_fragment("<section><p>步骤")

    assert result.html_fragment == "<section><p>步骤</p></section>"
    assert "unclosed_tag_repaired" in result.warnings


@pytest.mark.parametrize("fragment", ["", "   "])
def test_html_practice_sanitizer_rejects_empty(fragment):
    with pytest.raises(HtmlPracticeAdmissionError, match="html_fragment_empty"):
        sanitize_html_practice_fragment(fragment)


def test_html_practice_sanitizer_rejects_oversized_fragment():
    with pytest.raises(HtmlPracticeAdmissionError, match="too_large"):
        sanitize_html_practice_fragment("<p>too long</p>", max_bytes=4)
