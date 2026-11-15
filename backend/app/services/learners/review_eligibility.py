"""A published target and a formal learning assessment jointly qualify review."""


def eligible_review_ids(profile, resource_repository, feedback_repository, job_repository):
    published = resource_repository.list_by_learner(profile.learner_id)
    jobs = {job.run_id: job for job in job_repository.list_by_learner(profile.learner_id)}
    covered = set()
    for resource in published:
        job = jobs.get(resource.run_id)
        if resource.publication_status != "published" or job is None or job.knowledge_base_id != profile.knowledge_base_id:
            continue
        targets = job.request_payload.get("target_skill_nodes", [])
        covered.update(targets)
        if resource.learning_path_node:
            covered.add(resource.learning_path_node)
    assessed = set()
    for attempt in feedback_repository.list_attempts(profile.learner_id, None):
        if attempt.metadata.get("assessment_kind") not in {"learning_check", "reassessment"}:
            continue
        job = jobs.get(attempt.source_run_id)
        if job is None or job.knowledge_base_id != profile.knowledge_base_id:
            continue
        assessed.update(point.knowledge_point_id for point in attempt.knowledge_point_results if point.total_count > 0)
    return covered & assessed
