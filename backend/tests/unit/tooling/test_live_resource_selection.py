import pytest

from scripts.live_lecture_claim_once import current_resources, single_current_resource


def resource(ident, parent=None, version=1, status="unpublished"):
    return dict(resource_id=ident, parent_resource_id=parent, version=version,
                resource_type="lecture", publication_status=status)


def test_single_current_resource_uses_leaf_independent_of_row_order():
    rows = [resource("v1"), resource("v3", "v2", 3, "published"), resource("v2", "v1", 2)]
    assert single_current_resource(rows)["resource_id"] == "v3"
    assert single_current_resource(list(reversed(rows)))["publication_status"] == "published"


def test_failed_leaf_does_not_fall_back_to_successful_parent():
    rows = [resource("v1", status="published"), resource("failed", "v1", 2)]
    assert single_current_resource(rows)["resource_id"] == "failed"
    assert single_current_resource(rows)["publication_status"] == "unpublished"


def test_multiple_lineages_are_not_silently_reduced_to_one():
    rows = [resource("a"), resource("b")]
    assert len(current_resources(rows)) == 2
    with pytest.raises(ValueError, match="found 2"):
        single_current_resource(rows)
    with pytest.raises(ValueError, match="found 0"):
        single_current_resource([])
