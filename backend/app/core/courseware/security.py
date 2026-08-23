"""CSP construction and deterministic artifact security gates."""

import base64
import hashlib
import re

from app.core.courseware.runtime import SCRIPT, STYLE


def _sha256_csp(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


def security_policy(*, include_frame_ancestors: bool = False, style_content: str = STYLE) -> str:
    directives = [
        "default-src 'none'", f"style-src '{_sha256_csp(style_content)}'",
        f"script-src '{_sha256_csp(SCRIPT)}'", "img-src data:", "connect-src 'none'",
        "font-src 'none'", "media-src 'none'", "object-src 'none'", "base-uri 'none'",
        "form-action 'none'", "frame-src 'none'",
    ]
    if include_frame_ancestors:
        directives.append("frame-ancestors 'self'")
    return "; ".join(directives)


def browser_smoke_check(artifact: bytes) -> None:
    text = artifact.decode("utf-8", errors="strict")
    forbidden = (r"<iframe\b", r"<form\b", r"\bon\w+\s*=", r"https?://", r"<script(?!>)")
    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in forbidden):
        raise ValueError("课件产物未通过浏览器安全校验")
    if "Content-Security-Policy" not in text or "courseware-init" not in text:
        raise ValueError("课件产物缺少安全运行时")
