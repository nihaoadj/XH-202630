from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.audit.sql_repository import SQLAuditRepository
from app.db.shared.models import Base, ResourceReviewORM


def test_sql_audit_repository_persists_canonical_review_status():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    repository = SQLAuditRepository(sessionmaker(bind=engine))

    review_id = repository.save_review(
        "resource",
        {"review_id": "review", "status": "approve", "passed": True, "issues": []},
        "run",
    )

    assert review_id == "review"
    assert repository.get_review_by_resource("resource").status == "approved"
    assert repository.list_reviews_by_run("run")[0]["status"] == "approved"
    with sessionmaker(bind=engine)() as db:
        assert db.get(ResourceReviewORM, "review").status == "approved"

        db.add(ResourceReviewORM(
            review_id="legacy-review",
            resource_id="legacy-resource",
            run_id="legacy-run",
            status="approve",
        ))
        db.commit()

    assert repository.get_review_by_resource("legacy-resource").status == "approved"
    assert repository.list_reviews_by_run("legacy-run")[0]["status"] == "approved"
