import re

from app.core.courseware.renderer import render_courseware
from app.core.courseware.security import _sha256_csp, security_policy_for_artifact


def test_preview_csp_uses_the_rendered_theme_style_hash():
    artifact = render_courseware({
        "title": "主题课件",
        "scenes": [{
            "kind": "intro",
            "title": "开始",
            "blocks": ["内容"],
            "source_refs": ["lecture-1"],
            "source_block_ids": ["b1"],
        }],
    }, {"theme_id": "midnight"})

    text = artifact.decode("utf-8")
    style = re.search(r"<style>(.*?)</style>", text, re.DOTALL).group(1)
    script = re.search(r"<script>(.*?)</script>", text, re.DOTALL).group(1)
    policy = security_policy_for_artifact(artifact, include_frame_ancestors=True)

    assert f"style-src '{_sha256_csp(style)}'" in policy
    assert f"script-src '{_sha256_csp(script)}'" in policy
    assert "frame-ancestors 'self'" in policy
