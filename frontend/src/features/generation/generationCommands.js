/** Only send the supplement flag when the caller actually decided it. */
function supplementValue(claim, supplement) {
  if (supplement === undefined) return undefined
  return Boolean(claim && supplement)
}

/** Continuation request plans have no page, storage, router or notification effects. */
export function planRetryGeneration(job) {
  const payload = job?.request_payload
  if (!job?.run_id || !payload?.learner_id || !Array.isArray(payload?.resource_types) || !payload.resource_types.length) return null
  const supplement = supplementValue(payload.include_claim_check === true, payload.include_claim_evidence_retrieval === true)
  return [{ batchId: job.batch_id || job.run_id, data: {
    learner_id: job.learner_id, resource_types: payload.resource_types,
    instructions: payload.constraints?.continuation_instructions || '重新生成失败任务的学习材料。',
    source_run_id: job.run_id,
    ...(payload.include_claim_check === true ? { include_claim_evidence_retrieval: Boolean(supplement) } : {}),
  } }]
}

export function planRegeneratePending(job, resourceTypes, includeClaimCheck, includeClaimEvidenceRetrieval) {
  if (!job?.learner_id || !resourceTypes.length) return null
  const supplement = supplementValue(includeClaimCheck, includeClaimEvidenceRetrieval)
  return [{ batchId: job.batch_id || job.run_id, data: {
    learner_id: job.learner_id, resource_types: includeClaimCheck ? [resourceTypes[0]] : resourceTypes,
    source_run_id: job.run_id, replace_existing_types: true,
    instructions: `统一重新生成本任务中未通过审核的资源：${resourceTypes.join('、')}。`,
    ...(supplement === undefined ? {} : { include_claim_evidence_retrieval: supplement }),
  } }]
}

export function planAppendResources(job, selectedTypes, includeClaimCheck, includeClaimEvidenceRetrieval) {
  const resourceTypes = [...new Set(selectedTypes)]
  if (!job?.learner_id || !resourceTypes.length) return null
  const groups = includeClaimCheck ? resourceTypes.map(type => [type]) : [resourceTypes]
  const supplement = supplementValue(includeClaimCheck, includeClaimEvidenceRetrieval)
  return groups.map(types => ({ batchId: job.batch_id || job.run_id, data: {
    learner_id: job.learner_id, resource_types: types,
    instructions: '追加指定类型的学习资源，并与本批次已有资源保持衔接。',
    source_run_id: job.run_id, include_claim_check: includeClaimCheck,
    ...(supplement === undefined ? {} : { include_claim_evidence_retrieval: supplement }),
  } }))
}

export function planRetryResource(job, item) {
  if (!job?.run_id || !job?.learner_id || !item?.resource_spec_id || item.representation !== 'text') return null
  return [{ kind: 'resource_retry', runId: job.run_id, resourceSpecId: item.resource_spec_id, representation: 'text' }]
}

/** Preserve ordered responses even when Claim requests complete out of order. */
export function executeGenerationPlan(plan, continueBatch, retryResourceRepresentation) {
  return Promise.all(plan.map(item => item.kind === 'resource_retry'
    ? retryResourceRepresentation(item.runId, item.resourceSpecId, item.representation)
    : continueBatch(item.batchId, item.data)))
}
