/** Continuation request plans have no page, storage, router or notification effects. */
export function planRetryGeneration(job) {
  const payload = job?.request_payload
  if (!job?.run_id || !payload?.learner_id || !Array.isArray(payload?.resource_types) || !payload.resource_types.length) return null
  return [{ batchId: job.batch_id || job.run_id, data: {
    learner_id: job.learner_id, resource_types: payload.resource_types,
    instructions: payload.constraints?.continuation_instructions || '重新生成失败任务的学习材料。',
    source_run_id: job.run_id,
  } }]
}

export function planRegeneratePending(job, resourceTypes, includeClaimCheck) {
  if (!job?.learner_id || !resourceTypes.length) return null
  return [{ batchId: job.batch_id || job.run_id, data: {
    learner_id: job.learner_id, resource_types: includeClaimCheck ? [resourceTypes[0]] : resourceTypes,
    source_run_id: job.run_id, replace_existing_types: true,
    instructions: `统一重新生成本任务中未通过审核的资源：${resourceTypes.join('、')}。`,
  } }]
}

export function planAppendResources(job, selectedTypes, includeClaimCheck) {
  const resourceTypes = [...new Set(selectedTypes)]
  if (!job?.learner_id || !resourceTypes.length) return null
  const groups = includeClaimCheck ? resourceTypes.map(type => [type]) : [resourceTypes]
  return groups.map(types => ({ batchId: job.batch_id || job.run_id, data: {
    learner_id: job.learner_id, resource_types: types,
    instructions: '追加指定类型的学习资源，并与本批次已有资源保持衔接。',
    source_run_id: job.run_id, include_claim_check: includeClaimCheck,
  } }))
}

export function planRetryResource(job, item) {
  if (!job?.learner_id || !job.request_payload || !item?.resource_type) return null
  return [{ batchId: job.batch_id || job.run_id, data: {
    learner_id: job.learner_id, resource_types: [item.resource_type], source_run_id: job.run_id,
    replace_existing_types: true,
    instructions: `重新生成本批次的${item.resource_type}，用新版本替换学习列表中的旧版本。`,
  } }]
}

/** Preserve ordered responses even when Claim requests complete out of order. */
export function executeGenerationPlan(plan, continueBatch) {
  return Promise.all(plan.map(item => continueBatch(item.batchId, item.data)))
}
