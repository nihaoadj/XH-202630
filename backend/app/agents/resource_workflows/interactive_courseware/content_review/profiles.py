from app.models.courseware.content_review import BatchResultV1, RevisionPatchV1
from .types import ReviewProfile
from .prompts.common import COMMON, OUTPUT
from .prompts.rules import RULES
from .prompts.specialties import SPECIALTIES
from .prompts.revision import REVISION

REVIEW_PROFILE = ReviewProfile("content-review", "1.0", BatchResultV1, "generator", (COMMON, *RULES, *SPECIALTIES, OUTPUT))
REVISION_PROFILE = ReviewProfile("content-revision", "1.0", RevisionPatchV1, "generator", (COMMON, *RULES, REVISION))
