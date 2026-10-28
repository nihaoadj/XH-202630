import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'
import { inspectDropdownMenu, inspectElementSelect, inspectNativeSelect } from './selectPresentation.mjs'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const distDir = path.join(frontendDir, 'dist')
const reportDir = path.join(frontendDir, 'tests', 'test-results', 'generation-ui')
const baseViewport = { width: 1393, height: 871 }
const fixtureUser = { user_id: 'fixture-user', username: 'fixture-user', display_name: '资源生产验收用户' }
const externalRequests = []
const browserErrors = []
const fixtureAudit = { requests: [], writes: [], unexpectedApi: [] }

if (!existsSync(path.join(distDir, 'index.html'))) {
  throw new Error('Run npm --prefix frontend run build before generation browser verification')
}
mkdirSync(reportDir, { recursive: true })

function profile(learnerId, displayName, directionId = 'track-1') {
  return {
    learner_id: learnerId,
    knowledge_base_id: directionId,
    skill_level: '中级',
    learner_type: '个人学习者',
    created_at: '2026-10-01T08:00:00Z',
    learning_preferences: { metadata: { user_profile_snapshot: { display_name: displayName } } },
  }
}

function resource(resourceId, learnerId, runId, type, kind = 'learning_document', content = '# 内容\n\n固定的验收材料。', extra = {}) {
  return {
    resource_id: resourceId,
    learner_id: learnerId,
    run_id: runId,
    batch_id: 'batch-1',
    resource_type: type,
    resource_kind: kind,
    topic: type + '主题',
    title: type + '验收资源',
    difficulty: '中级',
    knowledge_points: ['节点A', '节点B'],
    content_text: content,
    created_at: '2026-10-01T08:00:00Z',
    file_path: '/fixture/resources/' + resourceId + '.md',
    source_refs: [],
    ...extra,
  }
}

function execution(resourceSpecId, resourceId, type, status, extra = {}) {
  return {
    run_id: 'run-main',
    resource_spec_id: resourceSpecId,
    representation: 'text',
    resource_id: resourceId,
    resource_type: type,
    resource_execution_state: status,
    publication_status: status === 'approved' ? 'published' : 'unpublished',
    attempt: 1,
    display_order: 1,
    ...extra,
  }
}

function timelineEvents(runId, count = 5) {
  return Array.from({ length: count }, (_, index) => ({
    run_id: runId,
    event_id: 'evt-' + runId + '-' + (index + 1),
    sequence: index + 1,
    event_type: index % 2 ? 'step_succeeded' : 'step_started',
    step_id: 'step-' + (index + 1),
    step_sequence: index + 1,
    node_name: 'agent_' + (index + 1),
    agent_name: '学习资源 Agent ' + (index + 1),
    action: '生成与核验',
    status: index % 2 ? 'success' : 'running',
    input_summary: '根据来源快照处理任务 ' + (index + 1),
    output_summary: '已完成工作流阶段 ' + (index + 1) + '。'.repeat(1),
    payload: {},
  }))
}

function auditVisualizationEvents(runId) {
  const resource = (resourceId, version, parentResourceId, reviewId) => ({
    resource_id: resourceId,
    resource_spec_id: 'spec-guide',
    resource_family_id: 'family-guide',
    resource_type: '实操指南',
    representation: 'text',
    version,
    parent_resource_id: parentResourceId,
    review_id: reviewId,
  })
  const events = [
    {
      event_type: 'resource_version_created', status: 'generated',
      payload: { ...resource('resource-guide-v1', 1, null, 'review-guide-v1'), resource_execution_state: 'generated', attempt: 1 },
    },
    {
      event_type: 'review_persisted', status: 'revision_requested',
      payload: { ...resource('resource-guide-v1', 1, null, 'review-guide-v1'), resource_execution_state: 'revision_requested', attempt: 1, review_id: 'review-guide-v1' },
    },
    {
      event_type: 'revision_requested', status: 'revision_requested',
      payload: { resource_ids: ['resource-guide-v1'], revision_count: 1, decision_reason: '步骤缺少可核对的来源依据，请补充并修正版本说明。' },
    },
    {
      event_type: 'resource_version_created', status: 'generated',
      payload: { ...resource('resource-guide', 2, 'resource-guide-v1', 'review-guide-v2'), resource_execution_state: 'generated', attempt: 2 },
    },
    {
      event_type: 'review_persisted', status: 'approved',
      payload: { ...resource('resource-guide', 2, 'resource-guide-v1', 'review-guide-v2'), resource_execution_state: 'approved', attempt: 2, review_id: 'review-guide-v2' },
    },
    {
      event_type: 'followup_generation_created', status: 'queued',
      payload: { child_run_id: 'followup-run', attempt_id: 'followup-attempt' },
    },
    { event_type: 'run_completed', status: 'completed', payload: {} },
  ].map((event, index) => ({
    run_id: runId,
    event_id: 'evt-' + runId + '-audit-' + (index + 1),
    event_type: event.event_type,
    event_sequence: index + 1,
    sequence: index + 1,
    step_id: 'audit-step-' + (index + 1),
    step_sequence: index + 1,
    node_name: event.event_type === 'review_persisted' ? 'review' : event.event_type,
    agent_name: event.event_type === 'review_persisted' ? '审核 Agent' : '资源工作流',
    action: event.event_type,
    status: event.status,
    payload: event.payload,
    occurred_at: '2026-10-01T08:0' + (index + 1) + ':00Z',
  }))
  return events
}

const AUDIT_OTHER_SPEC_RESOURCE_ID = '3fa85f64-5717-4562-b3fc-2c963f66afa6'

function assertRenderedEvidenceLocator(content, evidence, label) {
  const locator = evidence?.locator || {}
  const expected = []
  if (locator.page != null) expected.push(`第 ${locator.page} 页`)
  if (locator.line_start != null) {
    expected.push(`行 ${locator.line_start}${locator.line_end != null ? `–${locator.line_end}` : ''}`)
  } else if (locator.line_end != null) {
    expected.push(`截止行 ${locator.line_end}`)
  }
  for (const part of expected) assert.ok(content.includes(part), `${label} should render recorded locator field ${part}`)
}

function auditVisualizationTimeline(runId) {
  const timestamp = '2026-10-01T08:00:00Z'
  const step = (stepId, stepSequence, nodeName, agentName, action, status, values = {}) => ({
    schema_version: '1.0',
    run_id: runId,
    step_id: stepId,
    step_sequence: stepSequence,
    node_name: nodeName,
    agent_name: agentName,
    action,
    status,
    generation_attempt: stepSequence > 2 ? 2 : 1,
    input_summary: '',
    output_summary: '',
    decision_reason: null,
    evidence_refs: [],
    resource_ids: [],
    review_ids: [],
    retry_count: 0,
    started_at: timestamp,
    ended_at: timestamp,
    duration_ms: 340,
    ...values,
  })
  const evidence = [
    {
      schema_version: '1.0',
      evidence_id: 'evidence-frozen-supported',
      run_id: runId,
      retrieval_step_id: 'step-retrieval',
      knowledge_base_id: 'track-1',
      document_id: 'doc-frozen-protocol',
      document_version: '3.2',
      chunk_id: 'chunk-protocol-07',
      query_hash: 'a'.repeat(64),
      query_rank: 1,
      rank: 1,
      raw_score: 0.93,
      score_kind: 'similarity',
      normalized_score: 0.93,
      excerpt: '冻结来源原文：每次提交后记录操作者、提交时间与结果状态。',
      excerpt_hash: 'b'.repeat(64),
      locator: {
        knowledge_base_id: 'track-1',
        document_id: 'doc-frozen-protocol',
        document_version: '3.2',
        chunk_id: 'chunk-protocol-07',
        source_type: 'markdown',
        source_path: 'docs/protocol.md',
        title: '发布审计操作规范',
        section: '2.4 提交记录',
        page: 5,
        line_start: 42,
        line_end: 46,
      },
      config_hash: 'c'.repeat(64),
      snapshot_hash: 'd'.repeat(64),
      retrieved_at: timestamp,
    },
    {
      schema_version: '1.0',
      evidence_id: 'evidence-frozen-contradiction',
      run_id: runId,
      retrieval_step_id: 'step-retrieval',
      knowledge_base_id: 'track-1',
      document_id: 'doc-frozen-protocol',
      document_version: '3.2',
      chunk_id: 'chunk-protocol-03',
      query_hash: 'e'.repeat(64),
      query_rank: 1,
      rank: 2,
      raw_score: 0.86,
      score_kind: 'similarity',
      normalized_score: 0.86,
      excerpt: '冻结来源原文：审核记录保留九十天，超过期限后按归档规则清理。',
      excerpt_hash: 'f'.repeat(64),
      locator: {
        knowledge_base_id: 'track-1',
        document_id: 'doc-frozen-protocol',
        document_version: '3.2',
        chunk_id: 'chunk-protocol-03',
        source_type: 'markdown',
        source_path: 'docs/protocol.md',
        title: '发布审计操作规范',
        section: '1.2 记录保存期限',
        page: 2,
        line_start: 18,
        line_end: 22,
      },
      config_hash: 'c'.repeat(64),
      snapshot_hash: '1'.repeat(64),
      retrieved_at: timestamp,
    },
  ]

  return {
    steps: [
      step('audit-diagnose-unbound', 1, 'diagnose', 'diagnosis', '学情诊断', 'success', {
        input_summary: '读取当前学习目标与已有学情。',
        output_summary: '形成诊断结果；此步骤没有关联资源。',
      }),
      step('audit-review-v1', 2, 'review', '审核 Agent', '审核资源 v1', 'failed', {
        input_summary: '检查资源 resource-guide-v1 的事实陈述与证据引用。',
        output_summary: '审核发现来源范围不一致，要求定向返工。',
        decision_reason: '保留期限与冻结来源不符，且未说明记录字段。',
        evidence_refs: ['evidence-frozen-contradiction'],
        resource_ids: ['resource-guide-v1'],
        review_ids: ['review-guide-v1'],
        retry_count: 1,
      }),
      step('audit-revision', 3, 'prepare_revision', 'supervisor', '安排定向返工', 'success', {
        input_summary: '依据 review-guide-v1 的修订指令重新生成。',
        output_summary: '返工范围限定为 spec-guide 的 text 资源。',
        decision_reason: '审核要求修正记录保存期限并补足提交记录字段。',
        resource_ids: ['resource-guide-v1'],
        review_ids: ['review-guide-v1'],
      }),
      step('audit-generate-v2', 4, 'generate', 'generator', '生成资源 v2', 'success', {
        input_summary: '根据审核意见和冻结来源生成 resource-guide v2。',
        output_summary: '生成新版本并保留与 v1 的父子关系。',
        decision_reason: '修订记录保留期限为九十天，并补充操作者、时间和结果字段。',
        evidence_refs: ['evidence-frozen-supported', 'evidence-frozen-contradiction'],
        resource_ids: ['resource-guide'],
        retry_count: 2,
      }),
      step('audit-review-v2', 5, 'review', '审核 Agent', '审核资源 v2', 'success', {
        input_summary: '复核 resource-guide v2 的修订内容及来源依据。',
        output_summary: '必要事实与冻结来源一致，审核通过。',
        decision_reason: '保存期限与记录字段均有直接冻结来源支持。',
        evidence_refs: ['evidence-frozen-supported'],
        resource_ids: ['resource-guide'],
        review_ids: ['review-guide-v2'],
      }),
      step('audit-unknown-node', 6, 'unknown_future_node', 'reviewer', '未知节点不能借 reviewer 别名打开详情', 'success'),
    ],
    reviews: [
      {
        review_id: 'review-guide-v1', resource_id: 'resource-guide-v1', run_id: runId,
        status: 'revision_requested', claim_total: 2, claim_supported: 0, claim_unsupported: 2,
        suspected_hallucinations: 1, hallucination_rate: 0.5, legacy_reviewer_score: 0.42,
        claim_hallucination_rate: null, claim_metric_status: 'incomplete', review_pass_rate: 0.42,
        revision_count: 1,
        issues: [{ code: 'evidence_conflict', severity: 'high', description: '保存期限陈述与冻结来源冲突。' }],
        revision_instructions: [{ issue_codes: ['evidence_conflict'], target_resource_type: '实操指南', action: '按冻结来源修订期限，并补充记录字段。', priority: 1 }],
        review_hash: '2'.repeat(64), created_at: '2026-10-01T08:01:00Z',
      },
      {
        review_id: 'review-guide-v2', resource_id: 'resource-guide', run_id: runId,
        status: 'approved', claim_total: 2, claim_supported: 2, claim_unsupported: 0,
        suspected_hallucinations: 0, hallucination_rate: 0, legacy_reviewer_score: 0.98,
        claim_hallucination_rate: 0, claim_metric_status: 'complete', review_pass_rate: 0.98,
        revision_count: 1, issues: [], revision_instructions: [],
        review_hash: '3'.repeat(64), created_at: '2026-10-01T08:03:00Z',
      },
    ],
    resource_versions: [
      {
        resource_id: 'resource-guide-v1', run_id: runId, resource_spec_id: 'spec-guide',
        resource_family_id: 'family-guide', representation: 'text', resource_type: '实操指南',
        version: 1, parent_resource_id: null, review_id: 'review-guide-v1', review_status: 'revision_requested',
        publication_status: 'unpublished',
        content_text: '# 提交审计指南\n\n每次提交后只需记录操作者。\n\n审核记录永久保存。',
        created_at: '2026-10-01T08:00:00Z',
      },
      {
        resource_id: 'resource-guide', run_id: runId, resource_spec_id: 'spec-guide',
        resource_family_id: 'family-guide', representation: 'text', resource_type: '实操指南',
        version: 2, parent_resource_id: 'resource-guide-v1', review_id: 'review-guide-v2', review_status: 'approved',
        publication_status: 'published',
        content_text: '# 提交审计指南\n\n每次提交后记录操作者、提交时间与结果状态。\n\n审核记录保留九十天，超过期限后按归档规则清理。',
        created_at: '2026-10-01T08:02:00Z',
      },
      {
        resource_id: AUDIT_OTHER_SPEC_RESOURCE_ID, run_id: runId, resource_spec_id: 'spec-guide-other',
        resource_family_id: 'family-guide-other', representation: 'text', resource_type: '实操指南',
        version: 1, parent_resource_id: null, review_id: 'review-guide-other', review_status: 'approved',
        publication_status: 'published', content_text: '# 另一条实操指南\n\n它与 resource-guide 属于不同资源规格。',
        created_at: '2026-10-01T08:04:00Z',
      },
    ],
    evidence,
  }
}

function auditVisualizationClaims(runId) {
  const claimValues = [
    {
      claim_id: 'clm_11111111111111111111111111111111',
      claim_text: '每次提交后记录操作者、提交时间与结果状态。',
      source_text: '每次提交后记录操作者、提交时间与结果状态。',
      source_evidence_ids: ['evidence-frozen-supported'],
      verdict: 'supported', evidence_ids: ['evidence-frozen-supported'],
      reason: '与冻结来源原文一致。',
    },
    {
      claim_id: 'clm_22222222222222222222222222222222',
      claim_text: '审核记录永久保存。',
      source_text: '审核记录永久保存。',
      source_evidence_ids: ['evidence-frozen-contradiction'],
      verdict: 'contradicted', evidence_ids: ['evidence-frozen-contradiction'],
      reason: '冻结来源明确规定保存九十天后按归档规则清理。',
    },
    {
      claim_id: 'clm_33333333333333333333333333333333',
      claim_text: '提交时还会自动通知所有关注者。',
      source_text: '提交时还会自动通知所有关注者。',
      source_evidence_ids: [],
      verdict: 'not_in_evidence', evidence_ids: [],
      reason: '当前 Run 冻结的证据快照没有支持该陈述。',
    },
  ]
  return {
    run_id: runId,
    audit_status: 'complete',
    claims: claimValues.map((item, claimIndex) => ({
      schema_version: '2.0',
      claim_id: item.claim_id,
      run_id: runId,
      resource_id: 'resource-guide',
      resource_version: 2,
      review_id: 'review-guide-v2',
      claim_index: claimIndex,
      claim_text: item.claim_text,
      claim_type: 'factual',
      source_text: item.source_text,
      source_start: 0,
      source_end: item.source_text.length,
      source_text_hash: '4'.repeat(64),
      source_evidence_ids: item.source_evidence_ids,
      extraction_method: 'deterministic',
      extractor_prompt_version: 'fixture-v1',
      claim_hash: '5'.repeat(64),
      created_at: '2026-10-01T08:03:00Z',
    })),
    judgements: claimValues.map((item) => ({
      judgement_id: 'jdg_' + item.claim_id.slice(4),
      claim_id: item.claim_id,
      run_id: runId,
      resource_id: 'resource-guide',
      resource_version: 2,
      review_id: 'review-guide-v2',
      status: 'completed',
      verdict: item.verdict,
      evidence_ids: item.evidence_ids,
      reason: item.reason,
      judge_type: 'deterministic',
      judge_prompt_version: 'fixture-v1',
      confidence: 0.96,
      created_at: '2026-10-01T08:03:00Z',
    })),
    resource_metrics: {
      'resource-guide': {
        metric_status: 'complete',
        claim_hallucination_rate: 2 / 3,
        claim_total: 3,
        factual_claim_total: 3,
        supported_claim_total: 1,
        contradicted_claim_total: 1,
        not_in_evidence_claim_total: 1,
        non_factual_claim_total: 0,
        incomplete_claim_total: 0,
      },
    },
  }
}

function fullChainTimeline(runId, running = false) {
  const nodes = [
    ['diagnose', '学习目标与薄弱点诊断'],
    ['retrieve', '检索学习所需知识'],
    ['evidence_gate', '核对冻结来源'],
    ['plan', '制定资源与学习路径'],
    ['generate', '生成资源 v1'],
    ['review', '审核资源 v1', 'failed'],
    ['prepare_revision', '准备定向修订'],
    ['generate', '生成资源 v2'],
    ['review', '复审资源 v2'],
    ['claim_extract', '抽取可核验事实'],
    ['claim_judge', '对照冻结证据核验事实', running ? 'running' : 'success'],
    ...(!running ? [['claim_decide', '汇总事实核验结果'], ['finalize', '整理本轮执行结果']] : []),
  ]
  return {
    steps: nodes.map(([nodeName, action, status = 'success'], index) => ({
      schema_version: '1.0', run_id: runId, step_id: `chain-${index + 1}`, step_sequence: index + 1,
      node_name: nodeName, agent_name: nodeName, action, status,
      resource_ids: [], review_ids: [], evidence_refs: [], retry_count: 0,
      input_summary: '', output_summary: '', duration_ms: status === 'running' ? null : (index + 1) * 180,
    })).reverse(),
    reviews: [], resource_versions: [], evidence: [],
  }
}

function makeJob(learnerId, runId, status = 'completed', overrides = {}) {
  const resourceTypes = ['讲义', '实操指南', '分阶测试题']
  return {
    run_id: runId,
    batch_id: 'batch-' + learnerId,
    learner_id: learnerId,
    job_status: status,
    status,
    created_at: '2026-10-01T08:00:00Z',
    finished_at: status === 'completed' ? '2026-10-01T08:06:00Z' : null,
    error_message: status === 'failed' ? '验收任务故障说明：可重新生成。' : null,
    request_payload: {
      learner_id: learnerId,
      resource_types: resourceTypes,
      include_review: true,
      include_claim_check: true,
      constraints: { continuation_instructions: '按原任务参数重试。' },
    },
    resource_progress_summary: { total: 3, completed: status === 'completed' ? 3 : 1, published: status === 'completed' ? 2 : 0, failed: 0 },
    ...overrides,
  }
}

function longMarkdown() {
  const paragraphs = Array.from({ length: 55 }, (_, index) => (
    '## 学习材料段落 ' + String(index + 1).padStart(2, '0') + '\n\n'
    + ('在冻结来源上建立清晰解释，保留概念、步骤与证据之间的关系。 ').repeat(9)
  ))
  paragraphs.push('## 末尾段落\n\n这是滚动到正文末尾后应当完整可读的标记。')
  return '# 长篇学习材料\n\n' + paragraphs.join('\n\n')
}

function scenarioState(name) {
  const profiles = name === 'no-profile' ? [] : [
    profile('learner-1', '林知行'),
    profile('learner-2', '周明远', 'track-2'),
  ]
  const long = name === 'long'
  const primaryStatus = name === 'queued' ? 'queued'
    : name === 'running' || name === 'sse-fallback' ? 'running'
      : name === 'resource-live' ? 'running'
      : name === 'failed' ? 'failed' : 'completed'
  const primaryRun = name === 'multi' ? 'run-one' : 'run-main'
  const jobsByLearner = {
    'learner-1': name === 'no-task' || name === 'no-profile' ? [] : [
      makeJob('learner-1', primaryRun, name === 'multi' ? 'running' : primaryStatus,
        name === 'no-output' ? { resource_progress_summary: { total: 3, completed: 3, published: 0, failed: 0 } }
          : name === 'claim-pending' ? { resource_progress_summary: { total: 3, completed: 3, published: 2, failed: 0 } }
            : name === 'resource-live' ? { request_payload: {
              learner_id: 'learner-1', resource_types: ['实操指南', '复习清单', '讲义'],
              include_review: true, include_claim_check: true,
            } } : {}),
    ],
    'learner-2': ['multi', 'audit-visualization'].includes(name) ? [makeJob('learner-2', 'run-alt', 'completed', {
      batch_id: 'batch-learner-2',
      request_payload: { learner_id: 'learner-2', resource_types: ['复习清单'], include_review: true, include_claim_check: false },
    })] : [],
  }
  if (name === 'multi') {
    jobsByLearner['learner-1'].push(makeJob('learner-1', 'run-queued', 'queued', { batch_id: 'batch-learner-1-queued' }))
  }
  if (name === 'command-race') {
    jobsByLearner['learner-1'].push(makeJob('learner-1', 'run-other', 'completed', {
      batch_id: 'batch-other', created_at: '2026-09-30T08:00:00Z',
    }))
  }
  if (name === 'followup-navigation') {
    jobsByLearner['learner-1'].push(makeJob('learner-1', 'followup-run', 'completed', {
      batch_id: 'batch-learner-1-followup',
      created_at: '2026-09-30T08:00:00Z',
      request_payload: { learner_id: 'learner-1', resource_types: ['复习清单'], include_review: true, include_claim_check: true },
    }))
  }
  const resourcesByRun = {
    [primaryRun]: ['no-task', 'no-profile', 'no-output', 'queued'].includes(name) ? [] : [
      resource('resource-guide', 'learner-1', primaryRun, long ? '多阶段知识迁移与证据核验实操指南资源类型' : '实操指南', 'learning_document', long ? longMarkdown() : '# 实操指南\n\n从验收来源中完成一个可复核步骤。', {
        claim_publish_decision_pending: name === 'claim-pending',
        ...(name === 'resource-live' ? { publication_status: 'unpublished', claim_publish_decision_pending: false } : {}),
        ...(name === 'audit-visualization' ? {
          resource_spec_id: 'spec-guide',
          resource_family_id: 'family-guide',
          representation: 'text',
          version: 2,
          parent_resource_id: 'resource-guide-v1',
          review_id: 'review-guide-v2',
          review_status: 'approved',
          publication_status: 'published',
          content_text: '# 提交审计指南\n\n每次提交后记录操作者、提交时间与结果状态。\n\n审核记录保留九十天，超过期限后按归档规则清理。',
        } : {}),
      }),
      resource('resource-checklist', 'learner-1', primaryRun, '复习清单', 'learning_document', '# 复习清单\n\n回忆关键概念并核对证据。'),
      resource('resource-lecture', 'learner-1', primaryRun, '讲义'),
    ],
    'run-alt': [
      resource('resource-alt', 'learner-2', 'run-alt', '复习清单'),
    ],
    'followup-run': [],
    'run-queued': [],
    ...(name === 'command-race' ? {
      'run-other': [resource('resource-other', 'learner-1', 'run-other', '复习清单', 'learning_document', '# 任务 B 的独立材料\n\n切换后应继续保留这份内容。')],
    } : {}),
  }
  const executionsByRun = {
    [primaryRun]: ['no-output', 'queued'].includes(name) ? [] : name === 'resource-live' ? [
      execution('spec-guide', 'resource-guide', '实操指南', 'generating', {
        attempt: 2, publication_status: 'unpublished', updated_at: '2026-10-01T08:00:00Z',
      }),
    ] : [
      execution('spec-guide', 'resource-guide', '实操指南', name === 'partial' ? 'revision_requested' : name === 'claim-pending' ? 'human_review' : 'approved', {
        error_message: name === 'partial' ? '审核要求再次生成此资源。' : '',
        ...(name === 'claim-pending' ? { publication_status: 'unpublished' } : {}),
        agent_name: long ? '资源生成与跨阶段证据核验协作 Agent' : undefined,
        validation_status: long ? 'validated' : undefined,
        claim_metric_status: 'complete',
        factual_claim_total: name === 'audit-visualization' ? 3 : 5,
        supported_claim_total: name === 'audit-visualization' ? 1 : 4,
        not_in_evidence_claim_total: name === 'audit-visualization' ? 1 : 1,
        claim_factual_pass_rate: name === 'audit-visualization' ? 1 / 3 : 0.8,
        claim_publish_decision_pending: name === 'claim-pending',
      }),
      execution('spec-checklist', 'resource-checklist', '复习清单', 'approved', { display_order: 2 }),
      execution('spec-lecture', 'resource-lecture', '讲义', name === 'partial' ? 'failed' : 'approved', {
        display_order: 3,
        error_message: name === 'partial' ? '验收故障：该资源生成失败。' : '',
      }),
    ],
    'run-alt': [execution('spec-alt', 'resource-alt', '复习清单', 'approved')],
    'followup-run': [],
    'run-queued': [],
    ...(name === 'command-race' ? {
      'run-other': [execution('spec-other', 'resource-other', '复习清单', 'approved', { run_id: 'run-other' })],
    } : {}),
  }
  const longCourseware = name === 'courseware-long'
  const coursewareJob = {
    run_id: 'cw-existing',
    learner_id: 'learner-1',
    source_batch_id: 'batch-learner-1',
    status: 'failed',
    title: '验收互动课件',
    created_at: '2026-10-01T08:20:00Z',
    updated_at: '2026-10-01T08:21:00Z',
    error_message: '验收课件故障，可重试。',
    request_options: { learning_goal: '掌握核心步骤', expected_duration_minutes: 30 },
    scenes: longCourseware
      ? Array.from({ length: 32 }, (_, index) => ({
        scene_id: 'scene-long-' + index,
        scene_order: index,
        title: '长课件场景 ' + String(index + 1).padStart(2, '0'),
        kind: index % 2 ? 'practice' : 'review',
        status: 'failed',
        attempt: 1,
      }))
      : [{ scene_id: 'scene-failed', scene_order: 0, title: '失败页面', kind: 'practice', status: 'failed', attempt: 1 }],
    warnings: longCourseware
      ? Array.from({ length: 16 }, (_, index) => ({
        code: 'fixture-long-warning-' + index,
        message: '长课件警告 ' + String(index + 1).padStart(2, '0'),
      }))
      : [],
  }
  const timelineCount = long ? 90 : ['running', 'resource-live'].includes(name) ? 8 : 5
  return {
    scenario: name,
    profiles,
    jobsByLearner,
    coursewareJobs: ['courseware-existing', 'courseware-long'].includes(name) ? [coursewareJob] : [],
    coursewareJob,
    resourcesByRun,
    executionsByRun,
    timelines: {
      [primaryRun]: ['audit-visualization', 'followup-navigation'].includes(name)
        ? auditVisualizationEvents(primaryRun)
        : timelineEvents(primaryRun, timelineCount),
      'run-alt': timelineEvents('run-alt', 6),
      'followup-run': name === 'followup-navigation' ? timelineEvents('followup-run', 2) : [],
      'run-queued': [],
      ...(name === 'command-race' ? { 'run-other': timelineEvents('run-other', 2) } : {}),
      'cw-existing': [],
    },
    timelineDetails: ['audit-visualization', 'followup-navigation'].includes(name) ? auditVisualizationTimeline(primaryRun) : null,
    sseMode: name === 'sse-fallback' ? 'stream_error' : 'normal',
    writes: [],
    requests: [],
    unexpectedApi: [],
    failureMessages: [],
    statusFailureCount: 0,
    resourceFailureCount: 0,
    statusResourceExecutions: {},
    statusGetGate: null,
    continuationGate: null,
    jobsGetGate: null,
    resourceDelayMs: 0,
    jobsDelayMs: 0,
    timelineDelayMs: 0,
    sseClients: new Set(),
    nextRun: 0,
    lastClaimDecision: null,
    claims: name === 'audit-visualization' ? auditVisualizationClaims(primaryRun) : {
      claims: [
        { claim_id: 'claim-1', resource_id: 'resource-guide', claim_type: 'factual', claim_text: '验收事实陈述。' },
      ],
      judgements: [
        { claim_id: 'claim-1', verdict: 'not_in_evidence', reason: ' fixture 缺少直接证据。' },
      ],
      resource_metrics: {
        'resource-guide': {
          metric_status: 'complete',
          factual_claim_total: 5,
          supported_claim_total: 4,
          not_in_evidence_claim_total: 1,
          contradicted_claim_total: 0,
          claim_warning_publish: false,
          claim_publish_decision_pending: true,
        },
      },
    },
  }
}

let state = scenarioState('completed')
const evidence = {
  scenarios: [],
  screenshots: [],
  layoutChecks: [],
  scrollChecks: [],
  interactionChecks: [],
  contrastChecks: [],
  motionChecks: [],
  errors: browserErrors,
  externalRequests,
}

function json(response, payload, status = 200) {
  response.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
  response.end(JSON.stringify(payload))
}

async function readBody(request) {
  let body = ''
  for await (const chunk of request) body += chunk
  if (!body) return {}
  try {
    return JSON.parse(body)
  } catch {
    return { __invalid_json: body }
  }
}

function allJobs() {
  return Object.values(state.jobsByLearner).flat()
}

function findJob(runId) {
  return allJobs().find((item) => item.run_id === runId)
}

function recordWrite(record) {
  state.writes.push(record)
  fixtureAudit.writes.push({ scenario: state.scenario, ...record })
}

function recordUnexpected(record) {
  state.unexpectedApi.push(record)
  fixtureAudit.unexpectedApi.push({ scenario: state.scenario, ...record })
}

function eventSource(response, request, runId) {
  response.writeHead(200, {
    'content-type': 'text/event-stream; charset=utf-8',
    'cache-control': 'no-cache, no-transform',
    connection: 'keep-alive',
  })
  response.flushHeaders?.()
  const clients = state.sseClients
  const close = () => clients.delete(response)
  request.on('close', close)
  response.on('close', close)
  state.sseClients.add(response)
  if (state.sseMode === 'stream_error') {
    response.write('event: stream_error\ndata: ' + JSON.stringify({ code: 'WORKFLOW_STREAM_UNAVAILABLE' }) + '\n\n')
    return
  }
  const events = state.timelines[runId] || []
  const job = findJob(runId)
  const terminal = ['completed', 'failed'].includes(job?.job_status)
  response.write('event: snapshot\ndata: ' + JSON.stringify({
    run_id: runId,
    run_status: job?.job_status === 'queued' ? null : job?.job_status || 'running',
    job_status: job?.job_status || 'running',
    is_terminal: terminal,
    last_event_sequence: events.at(-1)?.sequence || 0,
    replay_completeness: 'complete',
  }) + '\n\n')
  for (const event of events.slice(-4)) {
    response.write('event: ' + event.event_type + '\ndata: ' + JSON.stringify(event) + '\n\n')
  }
  if (terminal) response.end()
}

function coursewarePath(pathname) {
  const match = pathname.match(/^\/api\/resources\/courseware\/jobs\/([^/]+)\/detail$/)
  return match ? decodeURIComponent(match[1]) : ''
}

async function apiResponse(url, method, request, response) {
  const pathname = url.pathname
  const requestRecord = { method, path: pathname, query: Object.fromEntries(url.searchParams.entries()) }
  state.requests.push(requestRecord)
  fixtureAudit.requests.push({ scenario: state.scenario, ...requestRecord })

  if (pathname === '/api/auth/me' && method === 'GET') return json(response, { user: fixtureUser })
  if (pathname === '/api/profiles/' && method === 'GET') return json(response, { items: state.profiles, total: state.profiles.length })
  const profileDelete = pathname.match(/^\/api\/profiles\/([^/]+)$/)
  if (profileDelete && method === 'DELETE') {
    recordWrite({ method, path: pathname, body: await readBody(request) })
    state.profiles = state.profiles.filter((item) => item.learner_id !== decodeURIComponent(profileDelete[1]))
    return json(response, { learner_id: decodeURIComponent(profileDelete[1]), deleted: true })
  }
  if (pathname === '/api/knowledge/domains' && method === 'GET') {
    return json(response, { domains: [{ domain_id: 'domain-1', name: '软件工程', tracks: [
      { track_id: 'track-1', name: 'AI 应用开发' },
      { track_id: 'track-2', name: '数据工程' },
    ] }] })
  }
  if (pathname === '/api/skills/nodes' && method === 'GET') {
    return json(response, { nodes: [{ node_id: '节点A', tier: 1 }, { node_id: '节点B', tier: 2 }] })
  }
  if (pathname === '/api/generate/jobs' && method === 'GET') {
    const items = structuredClone(state.jobsByLearner[url.searchParams.get('learner_id')] || [])
    const gate = state.jobsGetGate
    if (gate && !gate.started) {
      // Two identical pending GET URLs need no-store headers up front, or the
      // browser may serialize the second request behind its HTTP cache lock.
      if (gate.flushHeaders) {
        response.writeHead(gate.status || 200, {
          'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store',
        })
        response.flushHeaders?.()
      }
      gate.started = true
      await gate.promise
      if (gate.flushHeaders) return response.end(JSON.stringify({ items }))
      return json(response, { items }, gate.status || 200)
    }
    if (state.jobsDelayMs) await new Promise((resolve) => setTimeout(resolve, state.jobsDelayMs))
    return json(response, { items: state.jobsByLearner[url.searchParams.get('learner_id')] || [] })
  }
  if (pathname === '/api/resources/courseware/jobs' && method === 'GET') {
    return json(response, { items: state.coursewareJobs.filter((item) => item.learner_id === url.searchParams.get('learner_id')) })
  }
  if (pathname === '/api/resource-library/learner-1' && method === 'GET') {
    const items = Object.values(state.resourcesByRun).flat().filter((item) => item.learner_id === 'learner-1')
    return json(response, items.map(({ resource_id, ...item }) => ({ ...item, id: resource_id })))
  }
  const coursewareDetailId = coursewarePath(pathname)
  if (coursewareDetailId && method === 'GET') {
    return json(response, { ...state.coursewareJob, run_id: coursewareDetailId })
  }
  if (pathname === '/api/tutor/sessions' && method === 'POST') {
    const body = await readBody(request)
    recordWrite({ method, path: pathname, body })
    return json(response, { ...body, session_id: 'tutor-fixture-session', status: 'active' })
  }
  if (pathname === '/api/generate/jobs' && method === 'POST') {
    recordUnexpected({ method, path: pathname, reason: 'GenerateView has no initial-job creation entry' })
    return json(response, { detail: 'Unexpected initial generation POST in /generate fixture' }, 501)
  }
  const resourceRetryMatch = pathname.match(/^\/api\/generate\/jobs\/([^/]+)\/resource-specs\/([^/]+)\/representations\/text\/retry$/)
  if (resourceRetryMatch && method === 'POST') {
    recordWrite({ method, path: pathname })
    const source = Object.values(state.jobsByLearner).flat().find(job => job.run_id === decodeURIComponent(resourceRetryMatch[1]))
    const runId = 'resource-retry-' + (++state.nextRun)
    const created = makeJob(source.learner_id, runId, 'queued', {
      batch_id: source.batch_id || source.run_id,
      request_payload: { ...source.request_payload, resource_types: ['实操指南'] },
      resource_progress_summary: { total: 1, completed: 0, published: 0, failed: 0 },
    })
    state.jobsByLearner[created.learner_id].unshift(created)
    state.timelines[runId] = []
    state.executionsByRun[runId] = []
    return json(response, { run_id: runId, batch_id: created.batch_id, learner_id: created.learner_id,
      topic: created.topic || '工程验收任务', job_status: 'queued' })
  }
  const continuationMatch = pathname.match(/^\/api\/resources\/batches\/([^/]+)\/continuations$/)
  if (continuationMatch && method === 'POST') {
    const body = await readBody(request)
    recordWrite({ method, path: pathname, body })
    const runId = 'continue-' + (++state.nextRun)
    const created = makeJob(body.learner_id || 'learner-1', runId, 'queued', {
      batch_id: decodeURIComponent(continuationMatch[1]),
      request_payload: { ...body, include_review: true },
      resource_progress_summary: { total: (body.resource_types || []).length, completed: 0, published: 0, failed: 0 },
    })
    ;(state.jobsByLearner[created.learner_id] ||= []).unshift(created)
    state.timelines[runId] = []
    state.executionsByRun[runId] = []
    const gate = state.continuationGate
    if (gate && !gate.started) {
      gate.started = true
      gate.runId = runId
      await gate.promise
      if (gate.status) return json(response, { detail: 'Delayed fixture continuation failure' }, gate.status)
    }
    return json(response, {
      run_id: runId, batch_id: created.batch_id, learner_id: created.learner_id,
      topic: created.topic || '工程验收任务', job_status: 'queued', status: 'success',
    })
  }
  const decisionMatch = pathname.match(/^\/api\/resources\/items\/([^/]+)\/claim-publication-decision$/)
  if (decisionMatch && method === 'POST') {
    const body = await readBody(request)
    state.lastClaimDecision = { resource_id: decodeURIComponent(decisionMatch[1]), body }
    recordWrite({ method, path: pathname, body })
    state.claims.resource_metrics[state.lastClaimDecision.resource_id] = {
      ...state.claims.resource_metrics[state.lastClaimDecision.resource_id],
      claim_publish_decision_pending: false,
    }
    const decidedResource = Object.values(state.resourcesByRun).flat()
      .find(item => item.resource_id === state.lastClaimDecision.resource_id)
    if (decidedResource) {
      decidedResource.publication_status = body.publish ? 'published' : 'unpublished'
      decidedResource.claim_publish_decision_pending = false
      if (body.publish) {
        const job = findJob(decidedResource.run_id)
        const summary = job?.resource_progress_summary || {}
        if (job) {
          job.resource_progress_summary = {
            ...summary,
            published: Math.min(Number(summary.total) || 0, (Number(summary.published) || 0) + 1),
          }
        }
      }
    }
    return json(response, { resource_id: state.lastClaimDecision.resource_id, published: Boolean(body.publish) })
  }
  const coursewareBatchPath = '/api/resources/courseware/jobs/batch'
  if (pathname === coursewareBatchPath && method === 'POST') {
    const body = await readBody(request)
    recordWrite({ method, path: pathname, body })
    const runId = 'courseware-created-' + (++state.nextRun)
    state.coursewareJob = {
      run_id: runId,
      learner_id: body.learner_id,
      source_batch_id: 'batch-' + body.learner_id,
      status: 'composing',
      title: '新增互动课件',
      created_at: '2026-10-09T08:00:00Z',
      updated_at: '2026-10-09T08:00:00Z',
      request_options: { learning_goal: body.learning_goal, expected_duration_minutes: body.expected_duration_minutes },
      scenes: [{ scene_id: 'scene-new', scene_order: 0, title: '验收页面', kind: 'practice', status: 'composing', attempt: 1 }],
      warnings: [],
    }
    state.coursewareJobs.unshift(state.coursewareJob)
    return json(response, { jobs: [state.coursewareJob] })
  }
  const coursewareRetryMatch = pathname.match(/^\/api\/resources\/courseware\/jobs\/([^/]+)\/retry$/)
  if (coursewareRetryMatch && method === 'POST') {
    recordWrite({ method, path: pathname, body: await readBody(request) })
    state.coursewareJob = { ...state.coursewareJob, status: 'composing', error_message: '' }
    return json(response, { status: 'composing' })
  }
  const sceneRetryMatch = pathname.match(/^\/api\/resources\/courseware\/jobs\/([^/]+)\/scenes\/([^/]+)\/retry$/)
  if (sceneRetryMatch && method === 'POST') {
    recordWrite({ method, path: pathname, body: await readBody(request) })
    state.coursewareJob = {
      ...state.coursewareJob,
      status: 'composing',
      scenes: state.coursewareJob.scenes.map((scene) => ({ ...scene, status: 'retry_queued' })),
    }
    return json(response, { status: 'retry_queued' })
  }
  const timelineMatch = pathname.match(/^\/api\/runs\/([^/]+)\/timeline$/)
  if (timelineMatch && method === 'GET') {
    if (state.timelineDelayMs) await new Promise((resolve) => setTimeout(resolve, state.timelineDelayMs))
    const runId = decodeURIComponent(timelineMatch[1])
    const events = state.timelines[runId] || []
    return json(response, {
      run: { run_id: runId, status: findJob(runId)?.job_status || 'completed' },
      events: events.filter((event) => event.sequence > Number(url.searchParams.get('after_sequence') || 0)),
      resource_executions: state.executionsByRun[runId] || [],
      next_event_sequence: null,
      replay_completeness: 'complete',
      ...(runId === 'run-main' && state.timelineDetails ? state.timelineDetails : {}),
    })
  }
  const resourceDetailMatch = pathname.match(/^\/api\/resources\/items\/([^/]+)$/)
  if (resourceDetailMatch && method === 'GET') {
    const resourceId = decodeURIComponent(resourceDetailMatch[1])
    const resourceItem = Object.values(state.resourcesByRun).flat().find((item) => item.resource_id === resourceId)
    return resourceItem ? json(response, { resource: resourceItem }) : json(response, { detail: 'Unknown fixture resource' }, 404)
  }
  const claimsMatch = pathname.match(/^\/api\/runs\/([^/]+)\/claims$/)
  if (claimsMatch && method === 'GET') return json(response, state.claims)
  const statusMatch = pathname.match(/^\/api\/generate\/jobs\/([^/]+)$/)
  if (statusMatch && method === 'GET') {
    if (state.statusFailureCount > 0) {
      state.statusFailureCount -= 1
      return json(response, {}, 503)
    }
    const runId = decodeURIComponent(statusMatch[1])
    const job = findJob(runId)
    const items = state.statusResourceExecutions[runId]
    const status = job && items
      ? { ...job, resource_progress_summary: { ...job.resource_progress_summary, items: items.map(item => ({ ...item })) } }
      : job ? JSON.parse(JSON.stringify(job)) : null
    const gate = state.statusGetGate
    if (status && gate?.runId === runId && !gate.started) {
      gate.snapshot = JSON.parse(JSON.stringify(status))
      response.writeHead(200, {
        'content-type': 'application/json; charset=utf-8',
        'cache-control': 'no-store',
        'x-fixture-status-snapshot': 'held',
      })
      response.flushHeaders?.()
      gate.started = true
      await gate.promise
      response.end(JSON.stringify(gate.snapshot))
      return
    }
    if (gate?.runId === runId) {
      gate.newerResponses = (gate.newerResponses || 0) + 1
      response.writeHead(200, {
        'content-type': 'application/json; charset=utf-8',
        'cache-control': 'no-store',
        'x-fixture-status-snapshot': 'current',
      })
      response.end(JSON.stringify(status))
      return
    }
    return status ? json(response, status) : json(response, { detail: 'Unknown fixture run' }, 404)
  }
  const resourceFileMatch = pathname.match(/^\/api\/resources\/file\/([^/]+)$/)
  if (resourceFileMatch && method === 'GET') {
    const resourceId = decodeURIComponent(resourceFileMatch[1])
    response.writeHead(200, { 'content-type': 'text/plain; charset=utf-8', 'content-disposition': 'inline; filename="' + resourceId + '.md"', 'cache-control': 'no-store' })
    response.end('Isolated fixture download for ' + resourceId)
    return
  }
  const resourceListMatch = pathname.match(/^\/api\/resources\/([^/]+)$/)
  if (resourceListMatch && method === 'GET') {
    if (state.resourceDelayMs) await new Promise((resolve) => setTimeout(resolve, state.resourceDelayMs))
    if (state.resourceFailureCount > 0) {
      state.resourceFailureCount -= 1
      return json(response, {}, 503)
    }
    const learnerId = decodeURIComponent(resourceListMatch[1])
    const runId = url.searchParams.get('run_id') || ''
    const resources = runId
      ? (state.resourcesByRun[runId] || [])
      : Object.values(state.resourcesByRun).flat()
    return json(response, { resources: resources.filter((item) => item.learner_id === learnerId) })
  }
  const runEventsMatch = pathname.match(/^\/api\/runs\/([^/]+)\/events$/)
  if (runEventsMatch && method === 'GET') return eventSource(response, request, decodeURIComponent(runEventsMatch[1]))
  const coursewareEventsMatch = pathname.match(/^\/api\/resources\/courseware\/jobs\/([^/]+)\/events$/)
  if (coursewareEventsMatch && method === 'GET') {
    const runId = decodeURIComponent(coursewareEventsMatch[1])
    response.writeHead(200, { 'content-type': 'text/event-stream; charset=utf-8', 'cache-control': 'no-cache' })
    const clients = state.sseClients
    const close = () => clients.delete(response)
    request.on('close', close)
    response.on('close', close)
    clients.add(response)
    response.write('event: courseware_progress\ndata: ' + JSON.stringify({ run_id: runId, status: state.coursewareJob.status }) + '\n\n')
    return
  }
  if (pathname === '/api/learning-history/learner-1/journey' && method === 'GET') {
    return json(response, { learner_id: 'learner-1', profile: state.profiles[0] || null, rounds: [], events: [], current_state: { current_nodes: [], completed_nodes: [] }, next_offset: null })
  }
  if (pathname === '/api/onboarding/questions' && method === 'GET') return json(response, { questions: [] })
  if (pathname === '/api/resources/learner-1' && method === 'GET') {
    return json(response, { resources: (state.resourcesByRun['run-main'] || []) })
  }

  recordUnexpected({ method, path: pathname })
  return json(response, { detail: 'Unexpected API in isolated generation fixture' }, 501)
}

function contentType(file) {
  return ({
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
  })[path.extname(file).toLowerCase()] || 'application/octet-stream'
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url || '/', 'http://generation-fixture')
  const method = (request.method || 'GET').toUpperCase()
  if (url.pathname.startsWith('/__fixture/scenario/')) {
    state = scenarioState(decodeURIComponent(url.pathname.split('/').at(-1)))
    response.writeHead(200, { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store' })
    response.end('scenario reset')
    return
  }
  if (url.pathname.startsWith('/api/')) {
    try {
      await apiResponse(url, method, request, response)
    } catch (error) {
      recordUnexpected({ method, path: url.pathname, reason: error.message })
      if (!response.headersSent) json(response, { detail: 'Fixture API error' }, 500)
      else response.destroy(error)
    }
    return
  }
  let decoded
  try {
    decoded = decodeURIComponent(url.pathname)
  } catch {
    response.writeHead(400)
    response.end('Invalid path')
    return
  }
  const candidate = path.resolve(distDir, '.' + decoded)
  const safe = candidate === distDir || candidate.startsWith(distDir + path.sep)
  const isFile = safe && existsSync(candidate) && statSync(candidate).isFile()
  const file = isFile ? candidate : path.join(distDir, 'index.html')
  if (!existsSync(file)) {
    response.writeHead(404)
    response.end('Not found')
    return
  }
  response.writeHead(200, { 'content-type': contentType(file), 'cache-control': 'no-cache' })
  response.end(readFileSync(file))
})

function resetScenario(name) {
  for (const response of state.sseClients) response.end()
  state = scenarioState(name)
  externalRequests.length = 0
  browserErrors.length = 0
}

async function newPage(browser, base, name, viewport = baseViewport, options = {}) {
  resetScenario(name)
  if (options.delayJobsMs) state.jobsDelayMs = options.delayJobsMs
  if (options.failStatus) state.statusFailureCount = options.failStatus
  if (options.failResources) state.resourceFailureCount = options.failResources
  if (options.delayResourcesMs) state.resourceDelayMs = options.delayResourcesMs
  if (options.delayTimelineMs) state.timelineDelayMs = options.delayTimelineMs
  if (options.claimEnabled === false) for (const jobs of Object.values(state.jobsByLearner)) for (const job of jobs) job.request_payload.include_claim_check = false
  if (options.timeline) {
    state.timelineDetails = options.timeline
    state.timelines['run-main'] = []
  }
  const page = await browser.newPage({
    viewport: { width: viewport.width, height: viewport.height },
    reducedMotion: options.reducedMotion ? 'reduce' : 'no-preference',
  })
  page.setDefaultTimeout(9000)
  page.setDefaultNavigationTimeout(15000)
  page.on('pageerror', (error) => browserErrors.push({ scenario: name, message: error.message }))
  page.on('request', (request) => {
    try {
      if (new URL(request.url()).origin !== base) externalRequests.push({ scenario: name, url: request.url(), method: request.method() })
    } catch {
      externalRequests.push({ scenario: name, url: request.url(), method: request.method() })
    }
  })
  await page.addInitScript(() => {
    localStorage.clear()
    sessionStorage.clear()
  })
  if (options.traceRunStatusXhr) {
    await page.addInitScript(() => {
      window.__t17RunStatusXhrTrace = []
      const xhrPrototype = window.XMLHttpRequest.prototype
      const xhrOpen = xhrPrototype.open
      const xhrSend = xhrPrototype.send
      xhrPrototype.open = function (method, url, ...args) {
        this.__t17TraceStatusRequest = String(url) === '/api/generate/jobs/run-main'
        if (this.__t17TraceStatusRequest) window.__t17RunStatusXhrTrace.push({ kind: 'open', method: String(method), url: String(url) })
        return xhrOpen.call(this, method, url, ...args)
      }
      xhrPrototype.send = function (...args) {
        if (this.__t17TraceStatusRequest) window.__t17RunStatusXhrTrace.push({ kind: 'send', url: '/api/generate/jobs/run-main' })
        return xhrSend.apply(this, args)
      }
    })
  }
  await page.goto(base + '/generate', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.generate-page', { state: 'visible' })
  await page.locator('.task-selector').waitFor({ state: 'visible' })
  await page.waitForTimeout(100)
  return page
}

async function waitForLayout(page, expectedFit = null) {
  await page.waitForFunction((fit) => {
    const root = document.querySelector('.generate-page')
    if (!root || root.classList.contains('is-layout-measuring')) return false
    if (document.querySelector('.app-shell.is-sidebar-animating')) return false
    return fit === null || root.classList.contains('is-fit-layout') === fit
  }, expectedFit, { timeout: 9000 })
  await page.waitForTimeout(50)
}

async function setSidebar(page, collapsed) {
  const current = await page.locator('.app-shell').evaluate((node) => node.classList.contains('is-sidebar-collapsed'))
  if (current !== collapsed) {
    await page.locator('.sidebar-toggle').click()
    await page.waitForFunction((expected) => {
      const shell = document.querySelector('.app-shell')
      return shell?.classList.contains('is-sidebar-collapsed') === expected
        && !shell.classList.contains('is-sidebar-animating')
    }, collapsed)
  }
  await waitForLayout(page, true)
}

async function geometry(page, label, requireFit = false) {
  const metrics = await page.evaluate(() => {
    const rect = (node) => {
      if (!node) return null
      const value = node.getBoundingClientRect()
      return { top: value.top, bottom: value.bottom, left: value.left, right: value.right, width: value.width, height: value.height }
    }
    const root = document.querySelector('.generate-page')
    const content = document.querySelector('.content-area')
    const studio = document.querySelector('.studio-grid')
    const coursewareGrid = document.querySelector('.courseware-generation-page .generation-grid')
    const process = studio?.querySelector('.process-panel') || coursewareGrid?.querySelector('.process-panel')
    const resources = studio?.querySelector('.resources-panel') || coursewareGrid?.querySelector('.details-panel')
    const processTitle = process?.querySelector('.panel-title')
    const resourcesTitle = resources?.querySelector('.panel-title')
    const processScroll = document.querySelector('.process-scroll')
    const resourceStage = document.querySelector('.resource-stage')
    const mainRegion = studio || coursewareGrid
    const selectorFields = [...document.querySelectorAll('.task-selector .selector-field')]
    const summaryItems = [...document.querySelectorAll('.job-summary .summary-item')]
    const status = document.querySelector('.job-summary .production-status')
    const textActions = document.querySelector('.resources-panel > .resource-toolbar .task-actions')
    const coursewareActions = document.querySelector('.courseware-generation-page .details-panel > .panel-title .task-actions')
    const actionToolbar = textActions || coursewareActions
    const readerCard = document.querySelector('.resource-stage .reader-card')
    const readerHeader = readerCard?.querySelector('.reader-header')
    const resourceToolbar = document.querySelector('.resources-panel .resource-toolbar')
    const resourceToolbarActions = resourceToolbar?.querySelector('.resource-toolbar-actions')
    const readerTaskActions = resourceToolbarActions?.querySelector('.task-actions')
    const readerToolbarActions = resourceToolbarActions?.querySelector('.reader-toolbar-actions')
    const readerActionAnchor = resourceToolbar?.querySelector('#generation-reader-actions.reader-resource-actions')
    const resourceDifficulty = resourceToolbar?.querySelector('#generation-resource-difficulty.resource-grade')
    const readerTitle = readerCard?.querySelector('.resource-content h1')
    const downloadButton = readerActionAnchor?.querySelector('.download-button')
    const learningModeButton = readerToolbarActions?.querySelector('.learning-mode-action')
    const appendButton = document.querySelector('.resources-panel > .resource-toolbar .task-actions .status-action-append')
    const selectors = ['.task-selector', '.job-summary', '.studio-grid', '.courseware-generation-page .generation-grid']
    return {
      viewport: { width: innerWidth, height: innerHeight },
      fit: Boolean(root?.classList.contains('is-fit-layout')),
      root: rect(root),
      rootScroll: root ? { top: root.scrollTop, width: root.scrollWidth, clientWidth: root.clientWidth, height: root.scrollHeight, clientHeight: root.clientHeight } : null,
      content: content ? { top: content.scrollTop, width: content.scrollWidth, clientWidth: content.clientWidth, height: content.scrollHeight, clientHeight: content.clientHeight } : null,
      document: { top: document.documentElement.scrollTop, width: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth, height: document.documentElement.scrollHeight, clientHeight: document.documentElement.clientHeight },
      sections: Object.fromEntries(selectors.map((selector) => [selector, rect(document.querySelector(selector))])),
      selectorFields: selectorFields.map(rect),
      summaryItems: summaryItems.map((node) => ({ ...rect(node), text: node.innerText.trim() })),
      summaryStatus: status ? { ...rect(status), text: status.innerText.trim(), role: status.getAttribute('role'), ariaLive: status.getAttribute('aria-live'), ariaAtomic: status.getAttribute('aria-atomic'), iconCount: status.querySelectorAll('svg').length } : null,
      actionToolbar: actionToolbar ? {
        ...rect(actionToolbar),
        container: rect(textActions ? resourceToolbar : coursewareActions.parentElement),
        buttons: [...actionToolbar.querySelectorAll('button')].map((node) => ({ ...rect(node), text: node.innerText.trim(), visible: node.getClientRects().length > 0 })),
      } : null,
      actionToolbarKind: textActions ? 'text' : coursewareActions ? 'courseware' : null,
      mainRegion: rect(mainRegion),
      studio: rect(studio),
      mainHeightShare: mainRegion && root?.clientHeight ? mainRegion.getBoundingClientRect().height / root.clientHeight : null,
      process: rect(process),
      resources: rect(resources),
      reader: readerCard ? {
        card: rect(readerCard),
        headerCount: readerCard.querySelectorAll('.reader-header').length,
        difficultyCount: resourceToolbar?.querySelectorAll('#generation-resource-difficulty.resource-grade .resource-difficulty').length || 0,
        resourceToolbarActionsCount: resourceToolbar?.querySelectorAll('.resource-toolbar-actions').length || 0,
        downloadCount: resourceToolbar?.querySelectorAll('.reader-resource-actions .download-button').length || 0,
        learningModeCount: resourceToolbarActions?.querySelectorAll('.learning-mode-action').length || 0,
        toolbar: resourceToolbar ? { ...rect(resourceToolbar), scrollWidth: resourceToolbar.scrollWidth, clientWidth: resourceToolbar.clientWidth } : null,
        toolbarActions: resourceToolbarActions ? rect(resourceToolbarActions) : null,
        learningModeLast: readerToolbarActions?.lastElementChild?.classList.contains('learning-mode-action') || false,
        actionAnchor: readerActionAnchor ? { ...rect(readerActionAnchor), id: readerActionAnchor.id, className: readerActionAnchor.className, role: readerActionAnchor.getAttribute('role'), ariaLabel: readerActionAnchor.getAttribute('aria-label') } : null,
        actionAnchorCount: resourceToolbar?.querySelectorAll('#generation-reader-actions.reader-resource-actions').length || 0,
        difficulty: resourceDifficulty ? {
          ...rect(resourceDifficulty), id: resourceDifficulty.id, className: resourceDifficulty.className,
          text: resourceDifficulty.innerText.trim(), visible: resourceDifficulty.getClientRects().length > 0,
          containsGrade: Boolean(resourceDifficulty.querySelector('.resource-difficulty')),
          inToolbarActions: resourceDifficulty.parentElement === resourceToolbarActions,
          beforeTaskActions: Boolean(readerTaskActions && (resourceDifficulty.compareDocumentPosition(readerTaskActions) & Node.DOCUMENT_POSITION_FOLLOWING)),
        } : null,
        taskActionsInToolbarActions: Boolean(readerTaskActions && readerTaskActions.parentElement === resourceToolbarActions),
        title: readerTitle ? { ...rect(readerTitle), text: readerTitle.innerText.trim(), whiteSpace: getComputedStyle(readerTitle).whiteSpace, textOverflow: getComputedStyle(readerTitle).textOverflow, overflowX: getComputedStyle(readerTitle).overflowX, overflowY: getComputedStyle(readerTitle).overflowY, scrollWidth: readerTitle.scrollWidth, clientWidth: readerTitle.clientWidth } : null,
        download: downloadButton ? { ...rect(downloadButton), text: downloadButton.innerText.trim(), visible: downloadButton.getClientRects().length > 0 } : null,
        learningMode: learningModeButton ? { ...rect(learningModeButton), text: learningModeButton.innerText.trim(), visible: learningModeButton.getClientRects().length > 0 } : null,
        append: appendButton ? rect(appendButton) : null,
      } : null,
      headings: { process: rect(processTitle), resources: rect(resourcesTitle) },
      bilingualTitles: studio ? [processTitle, resourcesTitle].map((title) => {
        const number = title.querySelector('.panel-section-number')
        const chinese = title.querySelector('h3')
        const english = title.querySelector('.eyebrow')
        return {
          number: rect(number),
          numberText: number?.textContent.trim() || '',
          numberBeforeChinese: Boolean(number && chinese && (number.compareDocumentPosition(chinese) & Node.DOCUMENT_POSITION_FOLLOWING)),
          chinese: rect(chinese),
          chineseBeforeEnglish: Boolean(chinese && english && (chinese.compareDocumentPosition(english) & Node.DOCUMENT_POSITION_FOLLOWING)),
          english: rect(english),
          englishText: english?.textContent.trim() || '',
          actions: title.querySelectorAll('button, .task-actions, .output-count').length,
        }
      }) : [],
      processScroll: processScroll ? { top: processScroll.scrollTop, height: processScroll.scrollHeight, clientHeight: processScroll.clientHeight, width: processScroll.scrollWidth, clientWidth: processScroll.clientWidth } : null,
      resourceStage: resourceStage ? { top: resourceStage.scrollTop, height: resourceStage.scrollHeight, clientHeight: resourceStage.clientHeight, width: resourceStage.scrollWidth, clientWidth: resourceStage.clientWidth } : null,
      externalOverflow: [...document.querySelectorAll('.generate-page *')].filter((node) => {
        const r = node.getBoundingClientRect()
        return r.width > 0 && (r.left < -1 || r.right > innerWidth + 1)
      }).slice(0, 12).map((node) => ({
        selector: node.className?.baseVal || node.className || node.tagName,
        tag: node.tagName,
        text: node.textContent.trim().slice(0, 100),
        parent: node.parentElement?.className?.baseVal || node.parentElement?.className || node.parentElement?.tagName || '',
        grandparent: node.parentElement?.parentElement?.className?.baseVal || node.parentElement?.parentElement?.className || node.parentElement?.parentElement?.tagName || '',
        left: node.getBoundingClientRect().left,
        right: node.getBoundingClientRect().right,
      })),
    }
  })
  assert.ok(metrics.root, label + ': missing generation root')
  assert.ok(metrics.document.width <= metrics.document.clientWidth + 1, label + ': document horizontal overflow')
  assert.ok(metrics.rootScroll.width <= metrics.rootScroll.clientWidth + 1, label + ': generation root horizontal overflow')
  assert.ok(metrics.content.width <= metrics.content.clientWidth + 1, label + ': app content horizontal overflow')
  assert.equal(metrics.document.top, 0, label + ': document must start at scrollTop 0')
  assert.equal(metrics.rootScroll.top, 0, label + ': generation root must start at scrollTop 0')
  assert.equal(metrics.content.top, 0, label + ': outer app content must start at scrollTop 0')
  for (const [index, title] of metrics.bilingualTitles.entries()) {
    assert.equal(title.numberText, ['01', '02'][index],
      label + ': compact bilingual title should retain its panel number')
    assert.equal(title.englishText, ['/ WORKFLOW', '/ OUTPUT'][index],
      label + ': English eyebrow should contain only its slash and panel label')
    assert.ok(title.number, label + ': numbered panel heading should render its section number')
    assert.ok(title.numberBeforeChinese, label + ': section number should precede the Chinese title in the heading')
    assert.ok(title.chineseBeforeEnglish, label + ': Chinese title should appear before the English eyebrow')
    assert.ok(title.number.right <= title.chinese.left + 1, label + ': section number should be visually left of the Chinese title')
    assert.ok(title.chinese.right <= title.english.left + 1, label + ': bilingual title should use adjacent columns')
    assert.ok(title.number.top < title.chinese.bottom && title.chinese.top < title.number.bottom
      && title.chinese.top < title.english.bottom && title.english.top < title.chinese.bottom,
    label + ': numbered bilingual title should share one line')
    assert.equal(title.actions, 0, label + ': panel heading should reserve its space for the title')
  }
  if (requireFit) {
    assert.equal(metrics.fit, true, label + ': measured desktop should enable fit layout')
    assert.ok(metrics.document.height <= metrics.document.clientHeight + 1, label + ': fit layout should prevent document scrolling')
    assert.ok(metrics.rootScroll.height <= metrics.rootScroll.clientHeight + 1, label + ': fit layout should contain generation content')
    assert.ok(Math.abs(metrics.headings.process.top - metrics.headings.resources.top) <= 1, label + ': process/resource headings should align')
    for (const [selector, rect] of Object.entries(metrics.sections)) {
      if (!rect) continue
      assert.ok(rect.top >= metrics.root.top - 1 && rect.bottom <= metrics.root.bottom + 1, label + ': section is clipped in fit layout: ' + selector)
    }
    assert.ok(metrics.processScroll.clientHeight >= 120, label + ': process reading region should retain usable height')
    assert.ok(metrics.resourceStage.clientHeight >= 120, label + ': resource reading region should retain usable height')
  }
  if (metrics.viewport.width >= 1100) {
    assert.equal(metrics.selectorFields.length, 2, label + ': profile and batch selectors should form two side-by-side fields')
    assert.ok(Math.abs(metrics.selectorFields[0].top - metrics.selectorFields[1].top) <= 1, label + ': selector fields should stay on one horizontal row')
    assert.ok(Math.abs(metrics.selectorFields[0].bottom - metrics.selectorFields[1].bottom) <= 1, label + ': selector fields should have aligned row bottoms')
    assert.ok(metrics.selectorFields[0].right <= metrics.selectorFields[1].left + 1, label + ': selector fields should occupy distinct adjacent columns')
    assert.ok(metrics.sections['.task-selector'].width >= metrics.root.width * 0.95, label + ': selector row should use the full control width')
    assert.ok(metrics.selectorFields[0].width + metrics.selectorFields[1].width >= metrics.sections['.task-selector'].width * 0.8, label + ': selector columns should fill the control row')
    assert.equal(metrics.summaryItems.length, 6, label + ': job summary should show all six facts')
    const summaryOrder = ['学习方向', '任务编号', '任务状态', '可读资源', '创建时间', '完成时间']
    const summaryTop = metrics.summaryItems[0].top
    const summaryBottom = metrics.summaryItems[0].bottom
    for (let index = 0; index < metrics.summaryItems.length; index += 1) {
      const item = metrics.summaryItems[index]
      assert.ok(item.text.includes(summaryOrder[index]), label + ': job summary fact order changed at index ' + index + ': ' + JSON.stringify(item))
      assert.ok(Math.abs(item.top - summaryTop) <= 1 && Math.abs(item.bottom - summaryBottom) <= 1, label + ': all six summary cells should share one full row: ' + JSON.stringify(item))
      if (index > 0) assert.ok(metrics.summaryItems[index - 1].right <= item.left + 1, label + ': summary cells should occupy separate columns')
    }
    assert.ok(metrics.sections['.job-summary'].width >= metrics.root.width * 0.95, label + ': six-fact summary should span the full page row')
    assert.ok(metrics.summaryStatus, label + ': task state should be included in the summary row')
    assert.equal(metrics.summaryStatus.role, 'status', label + ': moved production state should retain status semantics')
    assert.equal(metrics.summaryStatus.ariaLive, 'polite', label + ': moved production state should retain its live announcement')
    assert.equal(metrics.summaryStatus.ariaAtomic, 'true', label + ': moved production state should remain atomic')
    assert.ok(metrics.summaryStatus.iconCount > 0, label + ': task state should retain its semantic icon')
    assert.equal(await page.locator('.status-actions').count(), 0, label + ': deleted top-level action row should not return')
    assert.ok(metrics.actionToolbar, label + ': task actions should stay in their local tools area')
    assert.ok(metrics.actionToolbar.width > 0, label + ': local action toolbar should remain visible')
    assert.ok(metrics.actionToolbar.left >= metrics.actionToolbar.container.left - 1 && metrics.actionToolbar.right <= metrics.actionToolbar.container.right + 1, label + ': local toolbar should remain inside its tools area')
    for (const button of metrics.actionToolbar.buttons) {
      assert.ok(button.visible && button.left >= metrics.actionToolbar.left - 1 && button.right <= metrics.actionToolbar.right + 1, label + ': local action should remain visible inside its toolbar: ' + JSON.stringify(button))
      assert.ok(button.height >= 44, label + ': local task action should meet the 44px target: ' + JSON.stringify(button))
    }
    for (let index = 1; index < metrics.actionToolbar.buttons.length; index += 1) {
      const previous = metrics.actionToolbar.buttons[index - 1]
      const current = metrics.actionToolbar.buttons[index]
      const overlapX = previous.left < current.right && current.left < previous.right
      const overlapY = previous.top < current.bottom && current.top < previous.bottom
      assert.ok(!(overlapX && overlapY), label + ': local task action buttons should not overlap')
    }
  }
  if (metrics.viewport.width >= 1280 && metrics.studio) {
    assert.ok(metrics.process.width >= 280, label + ': text process column should remain at least 280px wide')
    assert.ok(metrics.process.width <= metrics.root.width * 0.34, label + ': text process column should stay within roughly one third of the page')
    assert.ok(metrics.resources.width > metrics.process.width && metrics.resources.width >= metrics.studio.width * 0.6, label + ': text resource preview should receive the wider column')
  }
  if (metrics.viewport.width >= 1280 && metrics.sections['.courseware-generation-page .generation-grid']) {
    assert.ok(metrics.process.width > metrics.mainRegion.width * 0.34 && metrics.process.width < metrics.mainRegion.width * 0.5, label + ': embedded courseware should keep its original two-column balance')
    assert.ok(metrics.resources.width > metrics.process.width, label + ': courseware details should remain the wider column')
  }
  if (metrics.viewport.width >= 1280 && metrics.viewport.height >= 800 && metrics.studio && metrics.mainHeightShare != null) {
    assert.ok(metrics.mainHeightShare >= 0.66, label + ': normal text work area should occupy at least 66% of available root height: ' + JSON.stringify({ mainHeightShare: metrics.mainHeightShare, mainRegion: metrics.mainRegion, root: metrics.root }))
  }
  if (metrics.reader) {
    assert.equal(metrics.reader.headerCount, 0, label + ': generation reader header should be removed')
    assert.ok(metrics.reader.toolbar && metrics.reader.toolbarActions && metrics.reader.actionAnchor, label + ': reader actions should be merged into the resource toolbar')
    assert.equal(metrics.reader.learningModeLast, true, label + ': learning mode should be the final toolbar action')
    assert.equal(metrics.reader.resourceToolbarActionsCount, 1, label + ': resource action area should remain a single layout group')
    assert.equal(metrics.reader.difficulty?.id, 'generation-resource-difficulty', label + ': difficulty should use the dedicated Teleport anchor')
    assert.ok(metrics.reader.difficulty?.className.split(/\s+/).includes('resource-grade'), label + ': difficulty anchor should retain its resource-grade class')
    assert.ok(metrics.reader.difficulty?.containsGrade, label + ': difficulty label should remain inside its Teleport anchor')
    assert.equal(metrics.reader.difficulty?.inToolbarActions, true, label + ': difficulty should belong to resource-toolbar-actions')
    assert.equal(metrics.reader.taskActionsInToolbarActions, true, label + ': task actions should remain in resource-toolbar-actions')
    assert.equal(metrics.reader.difficulty?.beforeTaskActions, true, label + ': difficulty anchor should precede task actions')
    assert.equal(metrics.reader.actionAnchorCount, 1, label + ': the download Teleport anchor should remain unique')
    assert.equal(metrics.reader.actionAnchor.id, 'generation-reader-actions', label + ': download should retain its Teleport target')
    assert.ok(metrics.reader.actionAnchor.className.split(/\s+/).includes('reader-resource-actions'), label + ': download target should retain its reader-resource-actions class')
    assert.equal(metrics.reader.actionAnchor.role, 'group', label + ': teleported download control should retain a named group')
    assert.equal(metrics.reader.actionAnchor.ariaLabel, '资源文件操作', label + ': teleported download group should remain accessible')
    assert.equal(metrics.reader.difficultyCount, 1, label + ': generation reader should show one difficulty control in its toolbar')
    assert.equal(metrics.reader.downloadCount, 1, label + ': generation reader should show one download control in its toolbar')
    assert.equal(metrics.reader.learningModeCount, 1, label + ': generation reader should show one learning mode action in its toolbar')
    assert.ok(metrics.reader.toolbar.scrollWidth <= metrics.reader.toolbar.clientWidth + 1, label + ': merged resource toolbar should not overflow horizontally')
    assert.ok(metrics.reader.difficulty?.visible, label + ': difficulty should remain visible in the resource toolbar')
    assert.ok(metrics.reader.download?.visible, label + ': fixture file path should expose download in the resource toolbar')
    assert.equal(metrics.reader.download.text, '下载材料', label + ': download control should retain its action label')
    assert.ok(metrics.reader.learningMode?.visible, label + ': learning mode should remain visible in the resource toolbar')
    assert.equal(metrics.reader.learningMode.text, '学习模式', label + ': learning mode action should use its compact label')
    for (const control of [metrics.reader.difficulty, metrics.reader.download, metrics.reader.learningMode]) {
      assert.ok(control.left >= metrics.reader.toolbar.left - 1 && control.right <= metrics.reader.toolbar.right + 1, label + ': reader control should remain inside the resource toolbar: ' + JSON.stringify(control))
    }
    for (const control of [metrics.reader.download]) {
      assert.ok(control.left >= metrics.reader.actionAnchor.left - 1 && control.right <= metrics.reader.actionAnchor.right + 1, label + ': teleported reader controls should remain in their resource action group: ' + JSON.stringify(control))
    }
    assert.ok(metrics.reader.download.height >= 44, label + ': download control should meet the 44px target')
    assert.ok(metrics.reader.learningMode.height >= 44, label + ': learning mode control should meet the 44px target')
    const controls = [metrics.reader.difficulty, metrics.reader.download, metrics.reader.learningMode]
    for (let index = 0; index < controls.length; index += 1) {
      for (let otherIndex = index + 1; otherIndex < controls.length; otherIndex += 1) {
        const left = controls[index]
        const right = controls[otherIndex]
        const overlapX = left.left < right.right && right.left < left.right
        const overlapY = left.top < right.bottom && right.top < left.bottom
        assert.ok(!(overlapX && overlapY), label + ': reader toolbar controls should not overlap')
      }
    }
    if (metrics.reader.title?.text.includes('多阶段知识迁移')) {
      assert.ok(metrics.reader.title.text.includes('节点A、节点B'), label + ': long resource type title should retain the complete resource identity')
      assert.equal(metrics.reader.title.whiteSpace, 'normal', label + ': long resource title should wrap in the resource body')
      assert.ok(!['hidden', 'clip'].includes(metrics.reader.title.overflowX) && !['hidden', 'clip'].includes(metrics.reader.title.overflowY), label + ': full resource title should not be clipped')
      if (metrics.reader.title.clientWidth > 0) assert.ok(metrics.reader.title.scrollWidth <= metrics.reader.title.clientWidth + 1, label + ': complete body title should fit its visible box')
    }
    if (metrics.viewport.width >= 1280) {
      assert.ok(metrics.reader.append, label + ': append action should remain available in the reading toolbar')
      assert.ok(Math.abs(metrics.reader.append.width - 112) <= 1, label + ': append action should retain its 112px target width')
      assert.ok(Math.abs(metrics.reader.learningMode.width - metrics.reader.append.width) <= 1, label + ': learning mode and append actions should have equal widths')
      const overlapX = metrics.reader.append.left < metrics.reader.learningMode.right && metrics.reader.learningMode.left < metrics.reader.append.right
      const overlapY = metrics.reader.append.top < metrics.reader.learningMode.bottom && metrics.reader.learningMode.top < metrics.reader.append.bottom
      assert.ok(!(overlapX && overlapY), label + ': append and learning controls should not overlap')
      if (state.scenario === 'completed' && metrics.viewport.width >= 1393) {
        const buttons = [...metrics.actionToolbar.buttons, metrics.reader.download, metrics.reader.learningMode]
        const orderedButtons = [...buttons].sort((left, right) => left.left - right.left)
        assert.equal(buttons.length, 4, label + ': completed resource toolbar should expose four primary resource actions')
        assert.ok(buttons.every((button) => Math.abs(button.top - buttons[0].top) <= 1),
          label + ': all four resource actions should share the same tool row: ' + JSON.stringify(buttons))
        assert.ok(metrics.reader.difficulty.right <= orderedButtons[0].left + 1,
          label + ': difficulty should be the first item before all four resource actions: ' + JSON.stringify({ difficulty: metrics.reader.difficulty, buttons }))
        assert.ok(metrics.reader.difficulty.top < orderedButtons[0].bottom && orderedButtons[0].top < metrics.reader.difficulty.bottom,
          label + ': difficulty should share the four-button row: ' + JSON.stringify({ difficulty: metrics.reader.difficulty, buttons }))
        for (const button of orderedButtons) {
          if (/^重新生成失败资源/.test(button.text)) {
            assert.ok(button.width > 112, label + ': long failed-resource retry should retain its adaptive width: ' + JSON.stringify(button))
          } else {
            assert.ok(Math.abs(button.width - 112) <= 1, label + ': resource action should retain its 112px width: ' + JSON.stringify(button))
          }
        }
        for (let index = 1; index < orderedButtons.length; index += 1) {
          const gap = orderedButtons[index].left - orderedButtons[index - 1].right
          assert.ok(Math.abs(gap - 8) <= 1,
            label + ': four resource actions should use an 8px gap within 1px: ' + JSON.stringify({ previous: orderedButtons[index - 1], current: orderedButtons[index], gap }))
        }
      }
    }
  }
  if (metrics.processScroll) assert.ok(metrics.processScroll.width <= metrics.processScroll.clientWidth + 1, label + ': process region horizontal overflow')
  if (metrics.resourceStage) assert.ok(metrics.resourceStage.width <= metrics.resourceStage.clientWidth + 1, label + ': resource region horizontal overflow')
  evidence.layoutChecks.push({ label, ...metrics })
  return metrics
}

async function assertSummaryAndActions(page, label) {
  const statusLocator = page.locator('.job-summary .production-status')
  const status = await statusLocator.innerText()
  const summary = await page.locator('.job-summary').innerText()
  for (const semantic of ['学习方向', '任务编号', '任务状态', '可读资源', '创建时间', '完成时间']) {
    assert.ok(summary.includes(semantic), label + ': missing job summary fact ' + semantic)
  }
  assert.ok(summary.includes('AI 应用开发'), label + ': summary should show the selected learning direction')
  assert.ok(status.includes('已完成'), label + ': production status should show the terminal task state')
  assert.equal(await statusLocator.getAttribute('role'), 'status', label + ': production state should retain status semantics')
  assert.equal(await statusLocator.getAttribute('aria-live'), 'polite', label + ': production state should retain its live announcement')
  assert.ok(await statusLocator.locator('svg').count(), label + ': production state icon should remain visible')
  assert.equal(await page.locator('.production-intro, .production-banner, .production-context').count(), 0, label + ': top-level intro and banner should be removed')
  await assertNoLocalHistoryAction(page, label)
  const localActions = page.locator('.resources-panel > .resource-toolbar .task-actions')
  assert.equal(await localActions.count(), 1, label + ': task actions should live in the resource toolbar')
  assert.ok(await localActions.getByRole('button', { name: '刷新资源', exact: true }).count(), label + ': resource refresh should keep its full label')
  assert.ok(await localActions.getByRole('button', { name: '追加资源', exact: false }).count(), label + ': append action should remain in the resource toolbar')
  assert.equal(await page.getByRole('combobox', { name: '学习画像' }).count(), 1, label + ': profile selector needs an accessible name')
  assert.equal(await page.getByRole('combobox', { name: '资源批次' }).count(), 1, label + ': batch selector needs an accessible name')
  const targets = await page.evaluate(() => [...document.querySelectorAll(
    '.task-actions button, .learning-mode-action, .primary-action',
  )].filter((node) => {
    const rect = node.getBoundingClientRect()
    return rect.width > 0 && rect.height > 0 && getComputedStyle(node).visibility !== 'hidden'
  }).map((node) => ({ text: node.innerText.trim(), height: node.getBoundingClientRect().height })))
  for (const target of targets) {
    assert.ok(target.height >= 44, label + ': primary action is shorter than 44px ' + JSON.stringify(target))
  }
  evidence.interactionChecks.push({ label, summaryFacts: 6, namedSelectors: 2, primaryTargets: targets })
}

async function assertNoLocalHistoryAction(page, label) {
  assert.equal(await page.locator('.status-actions').count(), 0, label + ': old top-level task action row should be removed')
  assert.equal(await page.locator('.status-action-history').count(), 0, label + ': duplicate local learning history action should be removed')
  assert.equal(await page.getByRole('button', { name: '查看学习历史', exact: true }).count(), 0, label + ': local history button should not be duplicated')
  assert.equal(await page.getByRole('button', { name: '学习历史', exact: true }).count(), 1, label + ': topbar learning history route should remain')
}

async function openResourceDelivery(page) {
  const delivery = page.locator('.resource-progress-tree')
  await delivery.waitFor({ state: 'visible' })
  assert.equal(await delivery.evaluate((node) => node.tagName), 'SECTION',
    'resource status should use a permanently visible section')
}

async function alignProcessScrollBelowTopbar(page, label) {
  if ((page.viewportSize()?.width || 0) > 600) return { skipped: true, reason: 'desktop viewport' }
  const alignment = await page.evaluate(() => {
    const processScroll = document.querySelector('.generate-page .process-scroll')
    const topbar = document.querySelector('.app-shell .topbar')
    const contentArea = processScroll?.closest('.content-area')
    if (!processScroll || !topbar) return { missing: true }

    const desiredTop = () => Math.max(0, topbar.getBoundingClientRect().bottom) + 12
    const initialScrollTop = processScroll.getBoundingClientRect().top
    const initialDesiredTop = desiredTop()
    const initialWindowY = window.scrollY

    // First move the outer document for fixed/sticky shell layouts, then move
    // the actual content scroller by the remaining measured overlap.
    window.scrollBy(0, initialScrollTop - initialDesiredTop)
    const afterWindowTop = processScroll.getBoundingClientRect().top
    const afterWindowDesired = desiredTop()
    const contentDelta = afterWindowTop - afterWindowDesired
    if (contentArea && contentDelta) contentArea.scrollTop += contentDelta

    const finalTop = processScroll.getBoundingClientRect().top
    const finalDesired = desiredTop()
    return {
      initialScrollTop,
      initialDesiredTop,
      finalTop,
      finalDesired,
      windowYBefore: initialWindowY,
      windowYAfter: window.scrollY,
      contentScrollTop: contentArea?.scrollTop ?? null,
      viewportHeight: window.innerHeight,
    }
  })
  assert.ok(!alignment.missing, label + ': mobile crop requires the real process scrollport and shared topbar')
  assert.ok(Math.abs(alignment.finalTop - alignment.finalDesired) <= 2,
    label + ': actual page/content scrolling must place the process area below the visible topbar: ' + JSON.stringify(alignment))
  assert.ok(alignment.finalTop < alignment.viewportHeight - 32,
    label + ': process area should remain inside the real mobile viewport after alignment: ' + JSON.stringify(alignment))
  return alignment
}

async function captureResourceDelivery(page, target, filename) {
  await target.scrollIntoViewIfNeeded()
  await target.evaluate((node) => {
    const scrollport = node.closest('.process-scroll')
    if (!scrollport) return
    const targetTop = node.getBoundingClientRect().top
    const scrollportTop = scrollport.getBoundingClientRect().top
    scrollport.scrollTop += targetTop - scrollportTop - 8
  })
  const alignment = await alignProcessScrollBelowTopbar(page, filename)
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
  })
  const geometry = await target.evaluate((node) => {
    const target = node.getBoundingClientRect()
    const delivery = node.closest('.resource-progress-tree')?.getBoundingClientRect() || target
    const scrollport = node.closest('.process-scroll')?.getBoundingClientRect() || target
    const topbar = document.querySelector('.app-shell .topbar')?.getBoundingClientRect()
    const left = Math.max(target.left, delivery.left, scrollport.left, 0)
    const top = Math.max(target.top, delivery.top, scrollport.top, topbar?.bottom || 0, 0)
    const right = Math.min(target.right, delivery.right, scrollport.right, window.innerWidth)
    const bottom = Math.min(target.bottom, delivery.bottom, scrollport.bottom, window.innerHeight)
    return { clip: { x: left, y: top, width: right - left, height: bottom - top }, topbarBottom: topbar?.bottom || 0 }
  })
  const { clip } = geometry
  assert.ok(clip.width > 0 && clip.height > 0, 'resource evidence crop must intersect the visible delivery area: ' + JSON.stringify(clip))
  const pathName = path.join(reportDir, filename + '.png')
  await page.screenshot({ path: pathName, clip, animations: 'disabled' })
  evidence.screenshots.push({ filename: path.basename(pathName), path: pathName, viewport: page.viewportSize(), clip, alignment, topbarBottom: geometry.topbarBottom, crop: 'visible-resource' })
}

async function captureResourceDeliveryOverview(page, filename) {
  await openResourceDelivery(page)
  const first = page.locator('.resource-progress-tree .execution-card').nth(0)
  const second = page.locator('.resource-progress-tree .execution-card').nth(1)
  assert.equal(await first.count(), 1, 'delivery overview should include a first resource card')
  assert.equal(await second.count(), 1, 'delivery overview should include an adjacent second resource card')
  await first.scrollIntoViewIfNeeded()
  await first.evaluate((node) => {
    const scrollport = node.closest('.process-scroll')
    if (!scrollport) return
    scrollport.scrollTop += node.getBoundingClientRect().top - scrollport.getBoundingClientRect().top - 8
  })
  const alignment = await alignProcessScrollBelowTopbar(page, filename)
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
  })
  const geometry = await first.evaluate((node) => {
    const secondNode = node.parentElement?.querySelectorAll('.execution-card')[1]
    const wrapper = node.closest('.resource-execution-list')
    const delivery = node.closest('.resource-progress-tree')
    const scrollport = node.closest('.process-scroll')
    const firstRect = node.getBoundingClientRect()
    const secondRect = secondNode?.getBoundingClientRect()
    const wrapperRect = wrapper?.getBoundingClientRect() || firstRect
    const deliveryRect = delivery?.getBoundingClientRect() || firstRect
    const scrollRect = scrollport?.getBoundingClientRect() || firstRect
    const titleRect = node.querySelector('.execution-title')?.getBoundingClientRect() || firstRect
    const topbarRect = document.querySelector('.app-shell .topbar')?.getBoundingClientRect()
    const left = Math.max(wrapperRect.left, deliveryRect.left, scrollRect.left, 0)
    const right = Math.min(wrapperRect.right, deliveryRect.right, scrollRect.right, window.innerWidth)
    const top = Math.max(firstRect.top, deliveryRect.top, scrollRect.top, topbarRect?.bottom || 0, 0)
    const bottom = Math.min(secondRect?.bottom || firstRect.bottom, deliveryRect.bottom, scrollRect.bottom, window.innerHeight)
    return {
      clip: { x: left, y: top, width: right - left, height: bottom - top },
      firstTop: firstRect.top,
      firstBottom: firstRect.bottom,
      firstTitleTop: titleRect.top,
      firstTitleBottom: titleRect.bottom,
      secondTop: secondRect?.top || 0,
      secondHeight: secondRect?.height || 0,
      topbarBottom: topbarRect?.bottom || 0,
    }
  })
  const { clip } = geometry
  assert.ok(clip.width > 0 && clip.height > 0, 'delivery overview crop must intersect the visible resource list: ' + JSON.stringify(geometry))
  assert.ok(clip.y <= geometry.firstTitleTop && clip.y + clip.height >= geometry.firstTitleBottom,
    'delivery overview crop must show the first resource title below the shared topbar: ' + JSON.stringify(geometry))
  assert.ok(clip.y + clip.height >= geometry.secondTop + Math.min(32, geometry.secondHeight),
    'delivery overview crop should show the first resource and the adjacent second resource boundary: ' + JSON.stringify(geometry))
  const pathName = path.join(reportDir, filename + '.png')
  await page.screenshot({ path: pathName, clip, animations: 'disabled' })
  evidence.screenshots.push({ filename: path.basename(pathName), path: pathName, viewport: page.viewportSize(), clip, alignment, topbarBottom: geometry.topbarBottom, crop: 'visible-resource-overview' })
}

async function assertResourcePhases(page, label, {
  longMetadata = false, captureName = '', expectFailedUnpublished = false,
  expectedPhase = '', expectAllPublished = false, captureTitle = '实操指南',
} = {}) {
  const delivery = page.locator('.resource-progress-tree')
  await openResourceDelivery(page)
  const metrics = await page.locator('.resource-progress-tree').evaluate((tree) => {
    const cards = [...tree.querySelectorAll('.execution-card')]
    const graph = tree.ownerDocument.querySelector('.execution-graph')
    return {
      tagName: tree.tagName,
      visible: Boolean(tree.getClientRects().length),
      beforeGraph: Boolean(graph && (tree.compareDocumentPosition(graph) & Node.DOCUMENT_POSITION_FOLLOWING)),
      disclosureElements: tree.querySelectorAll('details, summary, .execution-metadata').length,
      labels: [...tree.querySelectorAll('.phase-name')].map((node) => node.textContent.trim()),
      deliveryCount: tree.querySelector('.delivery-count')?.innerText.trim() || '',
      phasePanels: tree.querySelectorAll('.resource-phase, .el-collapse').length,
      width: tree.clientWidth,
      scrollWidth: tree.scrollWidth,
      cards: cards.map((node) => ({
        className: node.className,
        title: node.querySelector('.execution-title strong')?.textContent.trim() || '',
        representation: node.querySelector('.execution-title > span')?.textContent.trim() || '',
        phase: node.querySelector('.execution-phase')?.innerText.trim() || '',
        rect: (() => {
          const rect = node.getBoundingClientRect()
          return { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
        })(),
        border: (() => {
          const style = getComputedStyle(node)
          return {
            widths: [style.borderTopWidth, style.borderRightWidth, style.borderBottomWidth, style.borderLeftWidth],
            styles: [style.borderTopStyle, style.borderRightStyle, style.borderBottomStyle, style.borderLeftStyle],
            color: style.borderTopColor,
            background: style.backgroundColor,
          }
        })(),
        statusFields: [...node.querySelectorAll('.execution-status-field')].map((field) => ({
          label: field.querySelector('small')?.innerText.trim() || '',
          value: field.querySelector('strong')?.innerText.trim() || '',
          width: field.querySelector('strong')?.clientWidth || 0,
          scrollWidth: field.querySelector('strong')?.scrollWidth || 0,
        })),
        statusText: node.querySelector('.execution-status-line')?.innerText.trim() || '',
        metadataText: node.querySelector('.execution-meta')?.innerText.trim() || '',
        metadataVisible: Boolean(node.querySelector('.execution-meta')?.getClientRects().length),
        errorText: node.querySelector('.execution-error')?.innerText.trim() || '',
        notices: [...node.querySelectorAll('.execution-notice')].map((notice) => notice.innerText.trim()),
        cardWidth: node.clientWidth,
        cardHeight: node.getBoundingClientRect().height,
        cardScrollWidth: node.scrollWidth,
        actionsWidth: node.querySelector('.execution-actions')?.getBoundingClientRect().width || 0,
        actionsHeight: node.querySelector('.execution-actions')?.getBoundingClientRect().height || 0,
        actionsDisplay: getComputedStyle(node.querySelector('.execution-actions')).display,
        actionsWrap: getComputedStyle(node.querySelector('.execution-actions')).flexWrap,
        actionsGap: getComputedStyle(node.querySelector('.execution-actions')).columnGap,
        actionLabels: [...node.querySelectorAll('.execution-actions button')].map((button) => button.innerText.trim()),
        actionButtons: [...node.querySelectorAll('.execution-actions button')].map((button) => {
          const rect = button.getBoundingClientRect()
          const style = getComputedStyle(button)
          return {
            label: button.innerText.trim(),
            ariaLabel: button.getAttribute('aria-label') || '',
            className: button.className,
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
            scrollWidth: button.scrollWidth,
            fontSize: style.fontSize,
            borderRadius: style.borderRadius,
          }
        }),
      })),
      outerBackground: getComputedStyle(tree.querySelector('.resource-execution-list')).backgroundColor,
      cardGaps: cards.slice(1).map((node, index) => {
        const previous = cards[index].getBoundingClientRect()
        return node.getBoundingClientRect().top - previous.bottom
      }),
      metadata: [...tree.querySelectorAll('.execution-meta')].map((node) => ({
        text: node.innerText.trim(),
        flexWrap: getComputedStyle(node).flexWrap,
        width: node.clientWidth,
        scrollWidth: node.scrollWidth,
        spans: [...node.querySelectorAll(':scope > span')].map((span) => ({
          text: span.innerText.trim(),
          width: span.clientWidth,
          scrollWidth: span.scrollWidth,
          whiteSpace: getComputedStyle(span).whiteSpace,
          textOverflow: getComputedStyle(span).textOverflow,
          overflowX: getComputedStyle(span).overflowX,
        })),
      })),
      actionTargetMode: window.matchMedia('(pointer: coarse), (max-width: 720px)').matches ? 'touch' : 'desktop',
    }
  })
  assert.equal(metrics.tagName, 'SECTION', label + ': resource status should be a normal section')
  assert.ok(metrics.visible, label + ': resource status should be visible by default')
  assert.ok(metrics.beforeGraph, label + ': resource status should precede the execution graph')
  assert.equal(metrics.disclosureElements, 0, label + ': resource status and processing records should not require disclosure')
  assert.deepEqual(metrics.labels, ['资源状态'], label + ': resources should appear in one status section')
  assert.ok(metrics.deliveryCount.includes('已发布') && metrics.deliveryCount.includes('/'), label + ': delivery summary should keep the published-to-total count')
  assert.equal(metrics.phasePanels, 0, label + ': delivery should not render nested phase panels or collapse groups')
  assert.ok(metrics.scrollWidth <= metrics.width + 1, label + ': expanded delivery should not overflow horizontally')
  assert.equal(metrics.cards.length, 3, label + ': each fixture resource should appear once in the delivery section')
  assert.equal(new Set(metrics.cards.map((card) => card.title)).size, metrics.cards.length,
    label + ': a resource must not be duplicated between generation and review summaries')
  assert.ok(metrics.cards.every((card) => /\bis-(success|warning|danger|info)\b/.test(card.className) && card.phase), label + ': each resource should expose its real phase and status tone')
  if (expectedPhase) assert.ok(metrics.cards.every((card) => card.phase === expectedPhase), label + ': existing phase labels should be preserved')
  assert.ok(metrics.cards.every((card) => card.statusFields.some((field) => field.label === '发布状态' && field.value)),
    label + ': each resource should expose its publication status as a labeled field')
  assert.ok(metrics.cards.every((card) => card.statusFields.filter((field) => field.label === '校验').length <= 1),
    label + ': a resource should expose at most one explicit validation status')
  if (longMetadata) {
    const validated = metrics.cards.find((card) => card.title === '实操指南')
    assert.ok(validated?.statusFields.some((field) => field.label === '校验' && field.value === '已通过'),
      label + ': the persisted validated status should be presented as 已通过')
  } else {
    assert.ok(metrics.cards.every((card) => !card.statusFields.some((field) => field.label === '校验' && field.value === '已通过')),
      label + ': absent validation evidence must not be presented as passed')
  }
  assert.ok(metrics.cards.every((card) => card.border.widths.every((width) => width === '1px')
    && card.border.styles.every((style) => style === 'solid')
    && card.border.background === 'rgb(255, 255, 255)'),
  label + ': each delivery item should be a distinct white article with a one-pixel solid border')
  assert.ok(metrics.cardGaps.every((gap) => gap >= 10), label + ': adjacent resource articles should have at least 10px separation')
  const outerRgb = metrics.outerBackground.match(/\d+(?:\.\d+)?/g)?.slice(0, 3).map(Number) || []
  assert.equal(outerRgb.length, 3, label + ': delivery list should expose a measurable outer background')
  assert.ok(outerRgb.every((channel) => channel >= 235) && outerRgb.some((channel) => channel < 255),
    label + ': white resource articles should sit against a light neutral outer surface')
  if (expectAllPublished) {
    assert.ok(metrics.cards.every((card) => card.statusFields.some((field) => field.label === '发布状态' && field.value === '已发布')),
      label + ': published resources should retain their true publication state')
  }
  assert.ok(metrics.cards.every((card) => card.cardScrollWidth <= card.cardWidth + 1), label + ': resource card content should not overflow horizontally')
  assert.ok(metrics.cards.every((card) => card.statusFields.every((field) => field.scrollWidth <= field.width + 1)),
    label + ': publication and Claim status text should remain fully readable')
  assert.ok(metrics.cards.every((card) => card.metadataVisible), label + ': attempt and agent records should remain visible on each card')
  const firstAction = delivery.locator('.execution-actions button').first()
  await firstAction.focus()
  const actionFocus = await firstAction.evaluate((node) => ({
    visible: node.matches(':focus-visible'),
    outlineStyle: getComputedStyle(node).outlineStyle,
    outlineWidth: getComputedStyle(node).outlineWidth,
  }))
  assert.ok(actionFocus.visible && actionFocus.outlineStyle !== 'none' && actionFocus.outlineWidth !== '0px',
    label + ': keyboard focus should remain visible on resource actions')
  await firstAction.evaluate((node) => node.blur())
  for (const card of metrics.cards) {
    if (metrics.actionTargetMode === 'touch') {
      assert.ok(card.actionButtons.every((button) => button.height >= 44), label + ': touch actions should retain 44px targets: ' + card.title)
    } else {
      assert.ok(card.actionButtons.every((button) => button.height >= 32 && button.height <= 36),
        label + ': desktop actions should use compact 32–36px targets: ' + card.title)
    }
    assert.ok(card.actionButtons.every((button) => button.scrollWidth <= button.width + 1), label + ': action labels should wrap without horizontal clipping: ' + card.title)
    assert.equal(card.actionsDisplay, 'flex', label + ': compact resource actions should use a wrapping flex row: ' + card.title)
    assert.equal(card.actionsWrap, 'wrap', label + ': compact resource actions should wrap when space is limited: ' + card.title)
    assert.ok(card.actionButtons.every((button) => button.width < card.actionsWidth * 0.75),
      label + ': action buttons should keep compact fit-content widths instead of stretching: ' + card.title)
    const expectedActionLabels = {
      '查看资源': '查看已发布资源',
      '审核报告': '查看审核报告',
      '重新生成': '重新生成此资源',
      '过程详情': '查看过程详情',
    }
    for (const button of card.actionButtons) {
      assert.equal(expectedActionLabels[button.label], button.ariaLabel,
        label + ': compact action text should preserve its original accessible name: ' + JSON.stringify(button))
    }
    if (card.actionButtons.length === 2) {
      assert.ok(Math.abs(card.actionButtons[0].y - card.actionButtons[1].y) <= 2,
        label + ': two ordinary resource actions should remain on the same row: ' + card.title)
      if (!card.errorText && card.notices.length === 0) {
        assert.ok(card.actionsHeight / card.cardHeight < 0.35,
          label + ': a normal two-action row should stay compact relative to its resource article: ' + card.title)
      }
    } else if (card.actionButtons.length >= 3) {
      const gap = Number.parseFloat(card.actionsGap) || 0
      const requiredWidth = card.actionButtons.reduce((sum, button) => sum + button.width, 0) + gap * (card.actionButtons.length - 1)
      if (requiredWidth <= card.actionsWidth + 1) {
        assert.ok(card.actionButtons.every((button) => Math.abs(button.y - card.actionButtons[0].y) <= 2),
          label + ': three compact actions should share one row when their measured widths fit: ' + card.title)
      }
    }
  }
  for (const metadata of metrics.metadata) {
    assert.equal(metadata.flexWrap, 'wrap', label + ': execution metadata should wrap instead of clipping')
    assert.ok(metadata.scrollWidth <= metadata.width + 1, label + ': execution metadata row should not overflow horizontally')
    for (const span of metadata.spans) {
      assert.ok(span.scrollWidth <= span.width + 1, label + ': execution metadata should remain fully readable: ' + JSON.stringify(span))
      assert.equal(span.textOverflow, 'clip', label + ': execution metadata should not be ellipsized: ' + JSON.stringify(span))
      assert.ok(!['hidden', 'clip'].includes(span.overflowX), label + ': execution metadata should not be clipped: ' + JSON.stringify(span))
    }
  }
  if (longMetadata) {
      const longCard = page.locator('.resource-progress-tree .execution-card').first()
    const longRow = await longCard.locator('.execution-meta').evaluate((node) => ({
      text: node.innerText.trim(),
      flexWrap: getComputedStyle(node).flexWrap,
      width: node.clientWidth,
      scrollWidth: node.scrollWidth,
      spans: [...node.querySelectorAll(':scope > span')].map((span) => ({
        text: span.innerText.trim(), width: span.clientWidth, scrollWidth: span.scrollWidth,
        textOverflow: getComputedStyle(span).textOverflow, overflowX: getComputedStyle(span).overflowX,
      })),
    }))
    assert.ok(longRow.text.includes('资源生成与跨阶段证据核验协作 Agent'), label + ': visible processing row should show the agent metadata')
    assert.ok(longRow.spans.some((span) => span.text.includes('第 1 次生成')), label + ': visible processing row should retain the attempt')
    assert.ok(longRow.spans.length >= 2, label + ': visible processing row should preserve each available metadata field')
    assert.equal(longRow.flexWrap, 'wrap', label + ': visible metadata should wrap instead of clipping')
    assert.ok(longRow.scrollWidth <= longRow.width + 1, label + ': visible metadata should not overflow horizontally')
    for (const span of longRow.spans) {
      assert.ok(span.scrollWidth <= span.width + 1, label + ': visible metadata should remain fully readable: ' + JSON.stringify(span))
      assert.equal(span.textOverflow, 'clip', label + ': visible metadata should not be ellipsized: ' + JSON.stringify(span))
      assert.ok(!['hidden', 'clip'].includes(span.overflowX), label + ': visible metadata should not be clipped: ' + JSON.stringify(span))
    }
    if (captureName) await captureResourceDelivery(page, longCard, captureName)
  }
  if (expectFailedUnpublished) {
    const failed = metrics.cards.find((card) => card.title === '讲义')
    assert.ok(failed, label + ': failed resource should retain its own delivery entry')
    assert.match(failed.className, /\bis-danger\b/, label + ': failed resource should keep its failure status tone')
    assert.match(failed.phase, /失败/, label + ': failed resource phase should remain explicit')
    const revision = metrics.cards.find((card) => card.title === '实操指南')
    assert.ok(revision?.phase.includes('返工中'), label + ': the revision phase label should remain unchanged')
    assert.ok(failed.statusFields.some((field) => field.label === '发布状态' && field.value === '尚未发布'),
      label + ': failed resource should remain explicitly unpublished')
    assert.ok(failed.errorText.includes('验收故障'), label + ': failed resource reason should remain visible')
  }
  evidence.layoutChecks.push({ label: label + '-resource-phases', ...metrics })
  if (captureName && !longMetadata) {
    const captureIndex = metrics.cards.findIndex((card) => card.title === captureTitle)
    assert.ok(captureIndex >= 0, label + ': requested delivery crop resource should exist: ' + captureTitle)
    await captureResourceDelivery(page, delivery.locator('.execution-card').nth(captureIndex), captureName)
  }
}

async function capture(page, filename) {
  const pathName = path.join(reportDir, filename + '.png')
  await page.screenshot({ path: pathName, animations: 'disabled' })
  evidence.screenshots.push({ filename: path.basename(pathName), path: pathName, viewport: page.viewportSize() })
}

async function assertNoExternalOrUnexpected(label) {
  assert.deepEqual(externalRequests, [], label + ': browser requested an external origin')
  assert.deepEqual(state.unexpectedApi, [], label + ': fixture saw an unmocked API call')
  assert.deepEqual(browserErrors, [], label + ': pageerror was reported')
}

async function assertContrast(page, label) {
  const checks = await page.evaluate(() => {
  const selectors = [
      '.job-summary .production-status', '.job-summary .production-status strong',
      '.job-summary .summary-item span', '.job-summary .summary-item strong',
      '.studio-grid .panel-title h3', '.process-scroll', '.resource-stage', '.execution-card strong',
      '.process-scroll .el-tag__content', '.resource-toolbar .resource-difficulty', '.resource-toolbar .download-button',
      '.execution-phase', '.execution-objective', '.execution-meta', '.execution-notice', '.execution-actions button',
      '.execution-graph-node-title', '.execution-graph-status', '.execution-graph-node-secondary',
      '.execution-graph-sequence', '.execution-graph-call-count', '.execution-graph-revision-label',
      '.resource-content h2', '.resource-content p',
      '.el-dialog__title', '.source-hint', '.source-list .el-checkbox__label', '.source-list span',
      '.audit-dialog-heading h2', '.audit-header-code', '.audit-refresh', '.audit-kicker',
      '.context-heading-copy strong', '.context-heading-copy small', '.context-fields dt', '.context-fields dd',
      '.audit-main h3', '.audit-main h4', '.audit-main .node-output', '.audit-main .path-index', '.audit-main .path-label', '.audit-main .result-caption', '.audit-main .result-context p', '.audit-main .source-excerpt', '.detail-execution-status', '.audit-main .section-number', '.review-card-heading h4', '.review-issue p', '.issue-level', '.retrieval-result', '.claim-verification', '.review-revisions summary',
      '.revision-instructions li', '.claim-verdict-counts > span', '.claim-statement', '.claim-summary-reason',
      '.claim-number', '.verdict', '.claim-detail-body p', '.evidence-section-label', '.evidence-section-label > span',
      '.source-locator', '.evidence-excerpt', '.audit-main summary', '.coverage-note',
      '.el-dialog__footer button', '.courseware-generation-page .scene-list strong',
      '.courseware-generation-page .scene-list small', '.courseware-generation-page .warnings',
      '.courseware-generation-page .scene-list button', '.courseware-generation-page .process-actions button',
      '.task-actions button', '.learning-mode-action',
      '.library-empty .library-preparation-actions .el-button--primary',
      '.resources-page .learning-toolbar .field-label', '.resources-page .toolbar-actions button',
      '.resources-page .resource-feedback-button', '.resources-page .resource-item.is-active strong',
      '.resources-page .resource-item.is-active small', '.resources-page .resource-item strong',
      '.resources-page .resource-item small', '.resources-page .focus-resource-switcher button.is-active strong',
      '.resources-page .focus-resource-switcher button.is-active small', '.resources-page .focus-exit',
      '.resources-page .tutor-trigger', '.resources-page .reader-header .download-button',
      '.resources-page .resource-content h1', '.resources-page .resource-content h2',
      '.resources-page .resource-content p',
    ]
    const parseColor = (value) => {
      const match = value.match(/rgba?\(([^)]+)\)/i)
      if (!match) return null
      const values = match[1].split(',').map((part) => Number.parseFloat(part.trim()))
      return { rgb: values.slice(0, 3), alpha: values.length > 3 ? values[3] : 1 }
    }
    const blend = (top, bottom) => {
      const alpha = top.alpha
      return top.rgb.map((value, index) => value * alpha + bottom[index] * (1 - alpha))
    }
    const luminance = (rgb) => {
      const channels = rgb.map((value) => {
        const v = value / 255
        return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    }
    const contrast = (a, b) => {
      const values = [luminance(a), luminance(b)].sort((x, y) => y - x)
      return (values[0] + 0.05) / (values[1] + 0.05)
    }
    const results = []
    for (const selector of selectors) {
      for (const node of document.querySelectorAll(selector)) {
        const style = getComputedStyle(node)
        const text = node.textContent.trim() || node.getAttribute('aria-label') || node.getAttribute('title') || ''
        if (!node.getClientRects().length || !text) continue
        const foreground = parseColor(style.color)
        if (!foreground) continue
        let backgrounds = [[255, 255, 255]]
        const chain = []
        let current = node
        while (current && current !== document.documentElement) {
          chain.push(current)
          current = current.parentElement
        }
        for (current of chain.reverse()) {
          const computed = getComputedStyle(current)
          const imageColors = computed.backgroundImage === 'none'
            ? []
            : [...computed.backgroundImage.matchAll(/rgba?\([^)]+\)/gi)].map((match) => parseColor(match[0])).filter(Boolean)
          if (imageColors.length) {
            const underlying = backgrounds
            backgrounds = imageColors.flatMap((color) => underlying.map((bg) => blend(color, bg)))
          }
          const color = parseColor(computed.backgroundColor)
          if (color && color.alpha > 0) backgrounds = backgrounds.map((bg) => blend(color, bg))
        }
        const composedForeground = foreground.alpha < 1 ? blend(foreground, backgrounds[0]) : foreground.rgb
        const ratios = backgrounds.map((background) => contrast(composedForeground, background))
        results.push({ selector, text: text.slice(0, 70), color: style.color, backgrounds, contrast: Math.min(...ratios) })
      }
    }
    return results
  })
  assert.ok(checks.length > 0, label + ': no visible contrast samples were collected')
  for (const check of checks) {
    assert.ok(check.contrast >= 4.5, label + ': contrast below 4.5:1 for ' + check.selector + ' ' + JSON.stringify(check))
  }
  evidence.contrastChecks.push({ label, checks })
}

async function resourcesCardColorSnapshot(page, label) {
  const snapshot = await page.evaluate((name) => {
    const card = document.querySelector('.resources-page .resource-item.is-active')
    const strong = card?.querySelector('strong')
    const small = card?.querySelector('small')
    const cardStyle = card ? getComputedStyle(card) : null
    const textStyle = strong ? getComputedStyle(strong) : null
    const detailStyle = small ? getComputedStyle(small) : null
    return {
      label: name,
      cardText: card?.innerText.trim() || '',
      foreground: textStyle?.color || null,
      detailForeground: detailStyle?.color || null,
      backgroundColor: cardStyle?.backgroundColor || null,
      backgroundImage: cardStyle?.backgroundImage || null,
      transitionProperty: cardStyle?.transitionProperty || null,
      transitionDuration: cardStyle?.transitionDuration || null,
    }
  }, label)
  evidence.resourcesStyleSnapshots ||= []
  evidence.resourcesStyleSnapshots.push(snapshot)
  return snapshot
}

async function assertResourcesCardContrast(page, label) {
  const immediate = await resourcesCardColorSnapshot(page, label + '-immediate')
  try {
    await assertContrast(page, label)
  } catch (error) {
    await page.waitForTimeout(300)
    const settled = await resourcesCardColorSnapshot(page, label + '-after-300ms')
    error.message += '\nResources card computed style diagnostic: ' + JSON.stringify({ immediate, settled })
    throw error
  }
  return immediate
}

async function assertInternalScroll(page, label) {
  const regions = ['.process-scroll', '.resource-stage']
  for (const selector of regions) {
    const locator = page.locator(selector)
    assert.equal(await locator.count(), 1, label + ': expected exactly one scroll region ' + selector)
    const expectedLabel = selector === '.process-scroll' ? '生成协作轨迹' : '学习资源预览'
    assert.equal(await locator.getAttribute('aria-label'), expectedLabel, label + ': scroll region accessible name changed')
    assert.equal(await locator.getAttribute('tabindex'), '0', label + ': scroll region should be keyboard focusable')
    // Disclosure inspection may have scrolled to the delivery section at the
    // bottom. Establish a known starting point before checking forward motion.
    await locator.evaluate((node) => { node.scrollTop = 0 })
    const before = await locator.evaluate((node) => ({ top: node.scrollTop, max: node.scrollHeight - node.clientHeight, height: node.clientHeight }))
    assert.ok(before.max > 0, label + ': long fixture should create scrollable content in ' + selector)
    await locator.evaluate((node) => { node.scrollTop = Math.min(140, node.scrollHeight) })
    await page.waitForTimeout(60)
    const afterProgram = await locator.evaluate((node) => node.scrollTop)
    assert.ok(afterProgram > before.top, label + ': programmatic scroll should move ' + selector)
    await locator.evaluate((node) => { node.scrollTop = 0 })
    const box = await locator.boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.wheel(0, 260)
    await page.waitForTimeout(60)
    const afterWheel = await locator.evaluate((node) => node.scrollTop)
    assert.ok(afterWheel > 0, label + ': wheel should scroll ' + selector)
    await locator.evaluate((node) => { node.scrollTop = 0; node.focus() })
    await page.keyboard.press('PageDown')
    await page.waitForTimeout(60)
    const afterKeyboard = await locator.evaluate((node) => node.scrollTop)
    assert.ok(afterKeyboard > 0, label + ': PageDown should scroll ' + selector)
    const focusVisible = await locator.evaluate((node) => ({
      active: document.activeElement === node,
      focusVisible: node.matches(':focus-visible'),
      outlineStyle: getComputedStyle(node).outlineStyle,
      outlineWidth: getComputedStyle(node).outlineWidth,
      boxShadow: getComputedStyle(node).boxShadow,
    }))
    assert.equal(focusVisible.active, true, label + ': scroll region should be keyboard focusable')
    assert.ok(focusVisible.focusVisible || focusVisible.outlineStyle !== 'none' || focusVisible.boxShadow !== 'none', label + ': scroll region focus indicator is not visible')
    evidence.scrollChecks.push({ label, selector, before, afterProgram, afterWheel, afterKeyboard, focusVisible })
  }
  const outerBefore = await page.evaluate(() => ({
    document: document.documentElement.scrollTop,
    content: document.querySelector('.content-area')?.scrollTop ?? null,
    root: document.querySelector('.generate-page')?.scrollTop ?? null,
  }))
  for (const selector of regions) {
    const locator = page.locator(selector)
    await locator.evaluate((node) => { node.scrollTop = node.scrollHeight })
    const box = await locator.boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.wheel(0, 700)
    await page.waitForTimeout(80)
    const outerAfter = await page.evaluate(() => ({
      document: document.documentElement.scrollTop,
      content: document.querySelector('.content-area')?.scrollTop ?? null,
      root: document.querySelector('.generate-page')?.scrollTop ?? null,
    }))
    assert.deepEqual(outerAfter, outerBefore, label + ': edge wheel must stay inside ' + selector)
    evidence.scrollChecks.push({ label, kind: 'edge-containment', selector, outerBefore, outerAfter })
  }
}

async function waitForFixture(predicate, label, timeoutMs = 7000) {
  const deadline = Date.now() + timeoutMs
  while (!predicate()) {
    if (Date.now() >= deadline) throw new Error(label + ': fixture condition timed out')
    await new Promise((resolve) => setTimeout(resolve, 20))
  }
}

async function chooseOption(page, name, optionName) {
  const input = page.getByRole('combobox', { name })
  const shell = input.locator('xpath=ancestor::div[contains(@class,"el-select__wrapper")]')
  await assertWrappedFieldFocus(page, `generation-${name}`, input, shell)
  await input.click()
  await page.getByRole('option', { name: optionName }).click()
}

async function assertWrappedFieldFocus(page, label, control, shell, screenshotName = null, { singleBorderControl = false, keyboardFocus = true } = {}) {
  const baseline = await shell.evaluate((node) => {
    const style = getComputedStyle(node)
    return { borderColor: style.borderTopColor, borderWidth: style.borderTopWidth, boxShadow: style.boxShadow }
  })
  await control.click()
  await page.waitForTimeout(240)
  const shellHandle = await shell.elementHandle()
  const controlHandle = await control.elementHandle()
  const focused = await page.evaluate(({ shell, control }) => {
    const outer = getComputedStyle(shell)
    const inner = getComputedStyle(control)
    return {
      active: document.activeElement === control,
      focusWithin: shell.matches(':focus-within'),
      hovered: shell.matches(':hover'),
      shell: { outlineStyle: outer.outlineStyle, outlineWidth: outer.outlineWidth, borderColor: outer.borderTopColor, borderWidth: outer.borderTopWidth, boxShadow: outer.boxShadow },
      control: {
        outlineStyle: inner.outlineStyle, outlineWidth: inner.outlineWidth,
        borderWidths: ['Top', 'Right', 'Bottom', 'Left'].map((side) => Number.parseFloat(inner['border' + side + 'Width']) || 0),
      },
    }
  }, { shell: shellHandle, control: controlHandle })
  if (screenshotName) await capture(page, screenshotName)
  const details = JSON.stringify({ baseline, focused })
  assert.equal(focused.active, true, label + ': click should focus the inner control: ' + details)
  assert.equal(focused.focusWithin, true, label + ': outer shell should retain focus-within: ' + details)
  assert.equal(focused.hovered, true, label + ': focus sample should retain hover: ' + details)
  assert.ok(focused.control.outlineStyle === 'none' || Number.parseFloat(focused.control.outlineWidth) === 0,
    label + ': inner control should not draw a separate outline: ' + details)
  assert.ok(focused.shell.outlineStyle === 'none' || Number.parseFloat(focused.shell.outlineWidth) === 0,
    label + ': wrapper should use its focus shadow/border without a second outline: ' + details)
  if (!singleBorderControl) assert.ok(focused.control.borderWidths.every((width) => width <= 0.5),
    label + ': inner input should not draw a second border: ' + details)
  const shadowVisible = focused.shell.boxShadow !== 'none'
    && focused.shell.boxShadow !== baseline.boxShadow
    && !/rgba\([^)]*,\s*0(?:\.0+)?\)/i.test(focused.shell.boxShadow)
  const borderVisible = focused.shell.borderColor !== baseline.borderColor && Number.parseFloat(focused.shell.borderWidth) > 0
  assert.ok(shadowVisible || borderVisible,
    label + ': focused wrapper should show a clear border or shadow while hovered: ' + details)
  evidence.interactionChecks.push({ scenario: 'wrapped-field-focus', label, baseline, focused })
  if (keyboardFocus) {
    await page.keyboard.press('Escape')
    await page.keyboard.press('Tab')
    await page.keyboard.press('Shift+Tab')
    const keyboard = await control.evaluate((node) => ({ active: document.activeElement === node, focusVisible: node.matches(':focus-visible') }))
    assert.equal(keyboard.active, true, label + ': keyboard tab navigation should return to the control: ' + JSON.stringify(keyboard))
    assert.equal(keyboard.focusVisible, true, label + ': keyboard focus should remain visible: ' + JSON.stringify(keyboard))
    evidence.interactionChecks.push({ scenario: 'wrapped-field-keyboard-focus', label, keyboard })
  }
}

async function chooseFilterableOptionWithKeyboard(page, select, searchText, expectedText, label) {
  const input = select.locator('input').first()
  await input.click()
  await input.fill(searchText)
  await input.press('ArrowDown')
  await input.press('Enter')
  await page.waitForTimeout(30)
  const selectedText = await select.innerText()
  assert.ok(selectedText.includes(expectedText), label + ': keyboard selection should choose ' + expectedText + '; got ' + selectedText)
  evidence.interactionChecks.push({ scenario: 'filterable-select-keyboard', label, selectedText })
}

async function openAppendDialog(page, command) {
  await page.locator('.resources-panel > .resource-toolbar .task-actions').getByRole('button', { name: '追加资源', exact: false }).click()
  await page.getByRole('menuitem', { name: command, exact: true }).click()
  if (command === '文本学习资源') await page.getByRole('heading', { name: '追加学习资源' }).waitFor()
  else await page.getByRole('heading', { name: '创建互动课件' }).waitFor()
}

async function appendTextTypes(page, claimEnabled, keepTypes, screenshotName = null) {
  await openAppendDialog(page, '文本学习资源')
  if (!evidence.interactionChecks.some((item) => item.scenario === 'append-checkbox-keyboard-focus')) {
    const keyboardOption = page.locator('.append-resource-options input:not(:disabled)').first()
    assert.ok(await keyboardOption.count(), 'append resource checkbox should be enabled in the fixture')
    let reachedCheckbox = false
    for (let index = 0; index < 24; index += 1) {
      if (await keyboardOption.evaluate((input) => document.activeElement === input)) {
        reachedCheckbox = true
        break
      }
      await page.keyboard.press('Tab')
    }
    assert.equal(reachedCheckbox || await keyboardOption.evaluate((input) => document.activeElement === input), true,
      'Tab navigation should reach an append resource checkbox')
    const focusCue = await keyboardOption.evaluate((input) => {
      const shell = input.closest('.el-checkbox__input')
      const mark = shell?.querySelector('.el-checkbox__inner')
      const style = mark ? getComputedStyle(mark) : null
      return { active: document.activeElement === input, checked: input.checked, focusVisible: input.matches(':focus-visible'), focusClass: shell?.classList.contains('is-focus'), borderColor: style?.borderTopColor, boxShadow: style?.boxShadow }
    })
    assert.equal(focusCue.active, true, 'append resource checkbox should receive keyboard focus')
    assert.equal(focusCue.focusVisible, true, 'append resource checkbox should show :focus-visible')
    evidence.interactionChecks.push({ scenario: 'append-checkbox-keyboard-focus', focusCue })
  }
  const claim = page.locator('.append-claim-option .el-checkbox')
  const current = await claim.getAttribute('aria-checked')
  const checked = current === 'true' || await claim.locator('input').isChecked().catch(() => false)
  if (checked !== claimEnabled) await claim.click()
  const options = page.locator('.append-resource-options .el-checkbox')
  const count = await options.count()
  for (let index = 0; index < count; index += 1) {
    const option = options.nth(index)
    const text = (await option.innerText()).trim()
    const desired = keepTypes.some((type) => text.includes(type))
    const input = option.locator('input')
    const isChecked = await input.isChecked().catch(async () => option.getAttribute('aria-checked').then((value) => value === 'true'))
    if (isChecked !== desired) await option.click()
  }
  if (screenshotName) await capture(page, screenshotName)
  await page.getByRole('button', { name: '开始追加' }).click()
  await waitForFixture(() => state.writes.some((item) => item.path.endsWith('/continuations')), 'append request')
}

async function assertRouteFixtureReady(page, expectedPath) {
  await page.waitForFunction((pathName) => location.pathname === pathName, expectedPath)
  await page.waitForTimeout(100)
}

async function setResourcesSidebar(page, collapsed) {
  const shell = page.locator('.app-shell')
  const current = await shell.evaluate((node) => node.classList.contains('is-sidebar-collapsed'))
  if (current !== collapsed) {
    await page.locator('.sidebar-toggle').click()
    await page.waitForFunction((expected) => {
      const node = document.querySelector('.app-shell')
      return node?.classList.contains('is-sidebar-collapsed') === expected
        && !node.classList.contains('is-sidebar-animating')
    }, collapsed)
  }
  await page.waitForTimeout(40)
}

async function assertResourcesGeometry(page, label) {
  const metrics = await page.evaluate(() => {
    const rect = (selector) => {
      const node = document.querySelector(selector)
      if (!node) return null
      const value = node.getBoundingClientRect()
      return { top: value.top, bottom: value.bottom, left: value.left, right: value.right, width: value.width, height: value.height }
    }
    return {
      viewport: { width: innerWidth, height: innerHeight },
      document: { width: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth },
      shell: rect('.app-shell'),
      toolbar: rect('.resources-page .learning-toolbar'),
      workspace: rect('.resources-page .learning-workspace'),
      shelf: rect('.resources-page .resource-shelf'),
      reader: rect('.resources-page .reading-stage'),
      activeResource: rect('.resources-page .resource-item.is-active'),
      focusMode: document.querySelector('.resources-layout')?.classList.contains('is-focus-mode') || false,
    }
  })
  assert.ok(metrics.toolbar, label + ': learning toolbar should remain present')
  assert.ok(metrics.workspace, label + ': learning workspace should remain present')
  assert.ok(metrics.document.width <= metrics.document.clientWidth + 1, label + ': Resources view should not create page-level horizontal overflow')
  if (!metrics.focusMode && metrics.shelf && metrics.reader) {
    const overlapX = Math.min(metrics.shelf.right, metrics.reader.right) - Math.max(metrics.shelf.left, metrics.reader.left)
    const overlapY = Math.min(metrics.shelf.bottom, metrics.reader.bottom) - Math.max(metrics.shelf.top, metrics.reader.top)
    assert.ok(overlapX <= 1 || overlapY <= 1, label + ': resource shelf and reader should not overlap')
  }
  evidence.layoutChecks.push({ label, resourcesView: metrics })
  return metrics
}

async function assertResourcesControls(page, label, selectors) {
  const controls = await page.evaluate((items) => items.map((selector) => {
    const node = document.querySelector(selector)
    if (!node) return { selector, missing: true }
    const rect = node.getBoundingClientRect()
    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
    return {
      selector,
      text: node.innerText?.trim() || node.getAttribute('aria-label') || '',
      visible: node.getClientRects().length > 0 && getComputedStyle(node).visibility !== 'hidden',
      rect: { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, width: rect.width, height: rect.height },
      viewport: { width: innerWidth, height: innerHeight },
      unobscured: Boolean(hit && (hit === node || node.contains(hit))),
    }
  }), selectors)
  for (const control of controls) {
    assert.equal(control.missing, undefined, label + ': expected control is missing: ' + control.selector)
    assert.equal(control.visible, true, label + ': control should be visible: ' + JSON.stringify(control))
    assert.ok(control.rect.width >= 44 && control.rect.height >= 44, label + ': primary control should have a 44px target: ' + JSON.stringify(control))
    assert.ok(control.rect.left >= -1 && control.rect.right <= control.viewport.width + 1
      && control.rect.top >= -1 && control.rect.bottom <= control.viewport.height + 1,
    label + ': control should not be clipped outside the viewport: ' + JSON.stringify(control))
    assert.equal(control.unobscured, true, label + ': control center should remain unobscured: ' + JSON.stringify(control))
  }
  evidence.layoutChecks.push({ label, resourcesControls: controls })
}

async function assertResourcesMobileSidebarGeometry(page, label, collapsed) {
  const expectedNavigation = [
    { label: '工作台', href: '/dashboard' },
    { label: '新建方向', href: '/learning/new' },
    { label: '资源生成', href: '/generate' },
    { label: '学习资源', href: '/resources' },
    { label: '学习反馈', href: '/feedback' },
  ]
  const metrics = await page.evaluate((expected) => {
    const rect = (node) => {
      const value = node.getBoundingClientRect()
      return { top: value.top, bottom: value.bottom, left: value.left, right: value.right, width: value.width, height: value.height }
    }
    const nav = [...document.querySelectorAll('.sidebar .nav-list .nav-item')].map((node) => {
      const box = rect(node)
      const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2)
      return {
        label: node.getAttribute('aria-label'),
        href: node.getAttribute('href'),
        current: node.getAttribute('aria-current'),
        rect: box,
        centerHitsTarget: Boolean(hit && (hit === node || node.contains(hit))),
      }
    })
    const button = (selector) => {
      const node = document.querySelector(selector)
      if (!node) return null
      const box = rect(node)
      const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2)
      return {
        label: node.getAttribute('aria-label'),
        expanded: node.getAttribute('aria-expanded'),
        rect: box,
        centerHitsTarget: Boolean(hit && (hit === node || node.contains(hit))),
      }
    }
    const brand = document.querySelector('.sidebar .brand-block')
    return {
      viewport: { width: innerWidth, height: innerHeight },
      collapsed: document.querySelector('.app-shell')?.classList.contains('is-sidebar-collapsed') || false,
      brand: brand ? { display: getComputedStyle(brand).display, visible: brand.getClientRects().length > 0 } : null,
      nav,
      toggle: button('.sidebar .sidebar-toggle'),
      logout: button('.sidebar .logout-button'),
      expected,
    }
  }, expectedNavigation)
  assert.equal(metrics.collapsed, collapsed, label + ': sidebar should retain the requested expanded/collapsed state')
  assert.deepEqual(metrics.brand, { display: 'none', visible: false }, label + ': small-screen Resources view should hide the brand block')
  assert.equal(metrics.nav.length, expectedNavigation.length, label + ': all five navigation links should remain present')
  for (let index = 0; index < expectedNavigation.length; index += 1) {
    const item = metrics.nav[index]
    const expected = expectedNavigation[index]
    assert.equal(item.label, expected.label, label + ': navigation aria-label should remain unchanged')
    assert.equal(item.href, expected.href, label + ': navigation href should remain unchanged')
    assert.equal(item.current, expected.href === '/resources' ? 'page' : null,
      label + ': current route semantics should remain on the Resources navigation item')
    assert.ok(item.rect.width >= 44 && item.rect.height >= 44, label + ': each navigation link needs a 44px target: ' + JSON.stringify(item))
    assert.ok(item.rect.left >= -1 && item.rect.right <= metrics.viewport.width + 1
      && item.rect.top >= -1 && item.rect.bottom <= metrics.viewport.height + 1,
    label + ': navigation link should be fully visible: ' + JSON.stringify(item))
    assert.equal(item.centerHitsTarget, true, label + ': navigation link center should hit itself: ' + JSON.stringify(item))
  }
  assert.ok(metrics.toggle, label + ': sidebar toggle should be present')
  assert.ok(metrics.logout, label + ': logout button should be present')
  assert.equal(metrics.toggle.label, collapsed ? '展开侧栏' : '收起侧栏', label + ': toggle aria-label should describe its action')
  assert.equal(metrics.toggle.expanded, collapsed ? 'false' : 'true', label + ': toggle aria-expanded should match its state')
  assert.equal(metrics.logout.label, '退出登录', label + ': logout aria-label should remain unchanged')
  for (const [name, control] of [['toggle', metrics.toggle], ['logout', metrics.logout]]) {
    assert.ok(control.rect.width >= 44 && control.rect.height >= 44, label + ': ' + name + ' needs a 44px target: ' + JSON.stringify(control))
    assert.ok(control.rect.left >= -1 && control.rect.right <= metrics.viewport.width + 1
      && control.rect.top >= -1 && control.rect.bottom <= metrics.viewport.height + 1,
    label + ': ' + name + ' should be fully visible: ' + JSON.stringify(control))
    assert.equal(control.centerHitsTarget, true, label + ': ' + name + ' center should hit itself: ' + JSON.stringify(control))
  }
  const allTargets = [...metrics.nav.map((item) => ({ name: item.label, ...item.rect })),
    { name: 'sidebar-toggle', ...metrics.toggle.rect }, { name: 'logout', ...metrics.logout.rect }]
  for (let leftIndex = 0; leftIndex < allTargets.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < allTargets.length; rightIndex += 1) {
      const left = allTargets[leftIndex]
      const right = allTargets[rightIndex]
      const overlapWidth = Math.min(left.right, right.right) - Math.max(left.left, right.left)
      const overlapHeight = Math.min(left.bottom, right.bottom) - Math.max(left.top, right.top)
      assert.ok(overlapWidth <= 1 || overlapHeight <= 1,
        label + ': navigation/control targets should not overlap: ' + JSON.stringify({ left: left.name, right: right.name, overlapWidth, overlapHeight }))
    }
  }
  evidence.layoutChecks.push({ label, resourcesMobileSidebar: metrics })
  return metrics
}

async function compactTopbarMetrics(page) {
  return page.evaluate(() => {
    const rect = (node) => {
      if (!node) return null
      const value = node.getBoundingClientRect()
      return { top: value.top, bottom: value.bottom, left: value.left, right: value.right, width: value.width, height: value.height }
    }
    const topbar = document.querySelector('.app-shell .topbar')
    const title = topbar?.querySelector('.topbar-copy h1')
    const actions = topbar?.querySelector('.topbar-actions')
    const meta = topbar?.querySelector('.topbar-meta')
    const subtitle = topbar?.querySelector('.topbar-copy p')
    return {
      topbar: rect(topbar),
      title: rect(title),
      actions: rect(actions),
      meta: rect(meta),
      subtitle: subtitle ? { display: getComputedStyle(subtitle).display, rect: rect(subtitle) } : null,
      titleText: title?.innerText.trim() || '',
      metaText: meta?.innerText.trim() || '',
      actionCount: actions?.querySelectorAll('button').length || 0,
      actionRects: [...(actions?.querySelectorAll('button') || [])].map(rect),
    }
  })
}

async function assertResourcesCompactTopbar(page, label, reference) {
  const metrics = await compactTopbarMetrics(page)
  assert.ok(await page.locator('.app-shell').evaluate((node) => node.classList.contains('is-resources')),
    label + ': Resources route should use its route-scoped compact shell style')
  assert.equal(metrics.titleText, '学习资源', label + ': topbar should retain the Resources page title')
  assert.ok(metrics.metaText.includes('fixture-user'), label + ': compact topbar should retain the current-user metadata')
  assert.equal(metrics.actionCount, 3, label + ': compact topbar should retain the three primary app actions')
  assert.ok(metrics.topbar.height >= 56 && metrics.topbar.height <= 72,
    label + ': desktop topbar should remain compact near the shared 60px workspace header: ' + JSON.stringify(metrics.topbar))
  assert.ok(metrics.title && metrics.actions && metrics.meta, label + ': title, actions, and user metadata should remain present')
  assert.ok(Math.abs((metrics.title.top + metrics.title.bottom) / 2 - (metrics.actions.top + metrics.actions.bottom) / 2) <= 2,
    label + ': title and app actions should share one compact header row')
  assert.ok(metrics.title.right <= metrics.actions.left + 1 && metrics.actions.right <= metrics.meta.left + 1,
    label + ': title, actions, and user metadata should not overlap')
  assert.ok(metrics.subtitle && metrics.subtitle.display === 'none'
    && metrics.subtitle.rect.height <= 1, label + ': legacy page subtitle should not consume topbar height')
  for (const action of metrics.actionRects) {
    assert.ok(action.height >= 44, label + ': shared app actions should retain 44px targets: ' + JSON.stringify(action))
  }
  for (const key of ['topbar', 'title', 'actions', 'meta']) {
    for (const coordinate of ['top', 'bottom', 'left', 'right', 'width', 'height']) {
      assert.ok(Math.abs(metrics[key][coordinate] - reference[key][coordinate]) <= 2,
        label + ': Resources topbar should match the existing generation header geometry (' + key + '.' + coordinate + '): '
        + JSON.stringify({ resources: metrics[key], generation: reference[key] }))
    }
  }
  evidence.layoutChecks.push({ label, compactTopbar: metrics, generationReference: reference })
  return metrics
}

async function assertSelectedResourceVisualState(page, label, selector, inactiveSelector) {
  const styles = await page.evaluate(({ active, inactive }) => {
    const describe = (node) => {
      if (!node) return null
      const style = getComputedStyle(node)
      return {
        color: style.color,
        backgroundColor: style.backgroundColor,
        backgroundImage: style.backgroundImage,
        borderColor: style.borderColor,
      }
    }
    return {
      active: describe(document.querySelector(active)),
      inactive: describe(document.querySelector(inactive)),
    }
  }, { active: selector, inactive: inactiveSelector })
  assert.ok(styles.active && styles.inactive, label + ': selected and unselected resources should both be rendered')
  const distinguishable = ['color', 'backgroundColor', 'backgroundImage', 'borderColor']
    .some((key) => styles.active[key] !== styles.inactive[key])
  assert.equal(distinguishable, true, label + ': selected resource should remain visually distinguishable without fixed palette assumptions: ' + JSON.stringify(styles))
  evidence.interactionChecks.push({ label, selectionStyles: styles })
}

async function testStateMatrix(browser, base) {
  for (const scenario of ['queued', 'running', 'sse-fallback', 'completed', 'partial', 'failed', 'no-task', 'no-profile', 'no-output']) {
    const page = await newPage(browser, base, scenario)
    const text = await page.locator('.generate-page').innerText()
    await assertNoLocalHistoryAction(page, scenario)
    assert.equal(await page.locator('.production-intro, .production-banner, .production-context').count(), 0, scenario + ': top-level intro and banner should be removed')
    const summary = await page.locator('.job-summary').innerText()
    for (const semantic of ['学习方向', '任务编号', '任务状态', '可读资源', '创建时间', '完成时间']) {
      assert.ok(summary.includes(semantic), scenario + ': missing job summary fact ' + semantic)
    }
    const actionToolbar = page.locator('.resources-panel > .resource-toolbar .task-actions')
    const shouldHaveActions = !['no-task', 'no-profile'].includes(scenario)
    assert.equal(await actionToolbar.count(), shouldHaveActions ? 1 : 0, scenario + ': conditional task controls should be placed in the resource toolbar')
    if (scenario === 'queued') {
      assert.ok(text.includes('排队中'), 'queued task state should be visible')
      assert.ok(await actionToolbar.getByRole('button', { name: '刷新状态', exact: true }).count(), 'queued job should expose its refresh control in the resource toolbar')
      const requestedTypes = state.jobsByLearner['learner-1'][0].request_payload.resource_types
      const queuedSection = page.locator('.resource-progress-tree')
      assert.ok(await queuedSection.isVisible(), 'queued task should show the resource status section before execution records exist')
      const queuedCards = await queuedSection.locator('.execution-card').evaluateAll((cards) => cards.map((card) => ({
        type: card.querySelector('.execution-title strong')?.textContent.trim() || '',
        phase: card.querySelector('.execution-phase')?.textContent.trim() || '',
        actions: card.querySelectorAll('.execution-actions button').length,
        validation: [...card.querySelectorAll('.execution-status-field')].find((field) => field.querySelector('small')?.textContent.trim() === '校验')
          ?.querySelector('strong')?.textContent.trim() || '',
      })))
      assert.deepEqual(queuedCards.map((card) => card.type), requestedTypes,
        'queued placeholders should come only from the real request payload and preserve its resource order')
      assert.ok(queuedCards.every((card) => /等待生成/.test(card.phase) && card.actions === 0),
        'queued placeholders should say they are waiting and expose no resource operations')
      assert.ok(queuedCards.every((card) => !card.validation || card.validation !== '已通过'),
        'queued placeholders must not claim validation passed')
      await capture(page, 'desktop-pending')
    }
    if (scenario === 'running') {
      assert.ok(text.includes('生成中'), 'running task state should be visible')
      assert.ok(await actionToolbar.getByRole('button', { name: '刷新状态', exact: true }).count(), 'running job should retain refresh in the resource toolbar')
      assert.ok(text.includes('节点级同步') || text.includes('任务记录'), 'running task should expose stream status')
    }
    if (scenario === 'sse-fallback') {
      await page.locator('.connection-state.is-fallback').waitFor({ state: 'visible' })
      assert.ok(state.requests.some((item) => item.path === '/api/runs/run-main/events'), 'fallback fixture should exercise the real run event endpoint')
      assert.equal(state.sseClients.size, 0, 'the run client should close the unavailable stream before polling')
    }
    if (scenario === 'completed') {
      assert.ok(text.includes('已完成'), 'completed task state should be visible')
      assert.ok(await page.locator('.resource-stage').count(), 'completed task should render the resource reader')
      await assertSummaryAndActions(page, scenario)
      await assertResourcePhases(page, scenario, {
        captureName: 'desktop-resource-delivery-normal', expectedPhase: '已发布', expectAllPublished: true,
      })
      for (const viewport of [
        { width: 1301, height: 871, name: 'desktop-resource-status-1301x871' },
        { width: 1886, height: 1290, name: 'desktop-resource-status-1886x1290' },
        { width: 390, height: 844, name: 'mobile-resource-status-390' },
      ]) {
        await page.setViewportSize({ width: viewport.width, height: viewport.height })
        await waitForLayout(page, viewport.width > 720)
        const statusSection = page.locator('.resource-progress-tree')
        assert.ok(await statusSection.isVisible(), viewport.name + ': resource status should stay visible without interaction')
        assert.ok(await statusSection.locator('.execution-card').count() > 0, viewport.name + ': visible status overview should contain resource cards')
        await captureResourceDeliveryOverview(page, viewport.name)
      }
      assert.ok((await page.locator('.process-panel .connection-state').innerText()).includes('已结束'), 'terminal run should retain its terminal connection status')
    }
    if (scenario === 'partial') {
      assert.ok(text.includes('失败') || text.includes('审核') || text.includes('重新生成'), 'partial failures should remain visible')
      assert.ok(await actionToolbar.getByRole('button', { name: /重新生成失败资源/ }).count(), 'failed resource batch action should remain in the resource toolbar')
    }
    if (scenario === 'failed') {
      assert.ok(text.includes('验收任务故障说明'), 'failed task reason should be readable')
      assert.ok(await actionToolbar.getByRole('button', { name: '重新生成', exact: true }).count(), 'failed batch retry should remain in the resource toolbar')
      await capture(page, 'desktop-failed')
    }
    if (scenario === 'no-task') {
      assert.ok(await page.locator('.empty-studio').isVisible(), 'empty task state should be explicit')
      assert.ok(await page.locator('.empty-studio .preparation-panel').isVisible(), 'no-task state should use the shared preparation panel')
      await assertGenerationPreparationPanel(page, scenario)
      assert.equal(await page.locator('.empty-studio .el-empty').count(), 0, 'no-task state should not retain the legacy empty illustration')
      assert.ok(text.includes('把学习目标，转化为专属内容。'), 'empty task state should explain the next step')
      const primary = page.getByRole('button', { name: '新建学习方向' })
      assert.ok((await primary.boundingBox())?.height >= 44, 'empty state main action should remain at least 44px high')
      await inspectElementSelect({
        page, suite: 'generation', evidenceDir: reportDir, id: 'generation-disabled-batch',
        select: page.locator('.task-selector .task-select').nth(1), disabled: true,
        getWriteCount: () => state.writes.length,
      })
      await capture(page, 'desktop-empty')
      await page.getByRole('button', { name: '新建学习方向' }).click()
      await assertRouteFixtureReady(page, '/learning/new')
      evidence.interactionChecks.push({ scenario, route: page.url(), action: 'new-learning-direction' })
    }
    if (scenario === 'no-profile') {
      assert.ok(text.includes('学习画像') || text.includes('新建学习方向'), 'no-profile state should remain understandable')
      assert.ok(await page.locator('.empty-studio .preparation-panel').isVisible(), 'no-profile state should use the shared preparation panel')
      await assertGenerationPreparationPanel(page, scenario)
      assert.equal(await page.locator('.empty-studio .el-empty').count(), 0, 'no-profile state should not retain the legacy empty illustration')
      assert.equal(state.profiles.length, 0, 'no-profile fixture should remain empty')
      await capture(page, 'desktop-no-profile')
    }
    if (scenario === 'no-output') {
      await page.locator('.resource-stage[aria-busy="false"]').waitFor({ state: 'visible' })
      const noOutputLayout = await geometry(page, scenario, true)
      assert.ok(noOutputLayout.studio && noOutputLayout.process && noOutputLayout.resources,
        'no-output selected-job state should retain both workbench panels: ' + JSON.stringify(noOutputLayout))
      assert.ok(Math.abs(noOutputLayout.headings.process.top - noOutputLayout.headings.resources.top) <= 1
        && Math.abs(noOutputLayout.headings.process.bottom - noOutputLayout.headings.resources.bottom) <= 1,
      'no-output selected-job state should keep process and resource panel headings aligned: ' + JSON.stringify(noOutputLayout.headings))
      const placeholder = page.locator('.resource-stage .resource-placeholder')
      assert.ok(await placeholder.isVisible(), 'completed task without published output should show a preparation panel inside the resource stage')
      assert.ok(await placeholder.locator('.preparation-heading').isVisible(), 'no-output state should explain the next step with the shared preparation panel')
      const placeholderGeometry = await page.evaluate(() => {
        const stage = document.querySelector('.resource-stage')
        const panel = stage?.querySelector('.resource-placeholder')
        const rect = (node) => {
          if (!node) return null
          const value = node.getBoundingClientRect()
          return { top: value.top, bottom: value.bottom, left: value.left, right: value.right }
        }
        return { stage: rect(stage), panel: rect(panel), contained: Boolean(stage && panel && stage.contains(panel)) }
      })
      assert.equal(placeholderGeometry.contained, true, 'no-output preparation should remain inside the selected-job resource reading region')
      assert.ok(placeholderGeometry.panel.left >= placeholderGeometry.stage.left - 1
        && placeholderGeometry.panel.right <= placeholderGeometry.stage.right + 1
        && placeholderGeometry.panel.top >= placeholderGeometry.stage.top - 1
        && placeholderGeometry.panel.bottom <= placeholderGeometry.stage.bottom + 1,
      'no-output preparation should fit the resource reading region: ' + JSON.stringify(placeholderGeometry))
      assert.equal(await placeholder.locator('.el-empty').count(), 0, 'no-output state should not retain the legacy empty illustration')
      assert.equal(await page.locator('.resource-toolbar').count(), 1, 'no-output state should retain its real task controls in the toolbar')
      assert.equal(await page.locator('.resource-toolbar .resource-select, .resource-toolbar .reader-toolbar-actions').count(), 0,
        'no-output state should not fabricate a resource selector or reader actions')
      assert.equal(await page.locator('.resource-stage .reader-card').count(), 0, 'no-output state should not render a fabricated reader')
      assert.ok(text.includes('已完成'), 'no-output state should preserve the actual completed job status')
      assert.equal(state.jobsByLearner['learner-1'][0]?.job_status, 'completed', 'no-output fixture should have a completed task')
      assert.equal(state.resourcesByRun['run-main'].length, 0, 'no-output fixture must not fabricate published resources')
      await assertSummaryAndActions(page, scenario)
      assert.ok(await actionToolbar.getByRole('button', { name: '刷新资源', exact: true }).count(), 'no-output task should keep its real resource refresh action')
      assert.ok(await actionToolbar.getByRole('button', { name: '追加资源', exact: false }).count(), 'no-output task should keep its append action')
      await capture(page, 'desktop-no-output')
    }
    evidence.scenarios.push({ name: scenario, taskText: text.slice(0, 180) })
    assert.equal(state.writes.length, 0, scenario + ': page entry/state inspection must not write to the fixture API')
    await assertNoExternalOrUnexpected(scenario)
    await page.close()
  }
}

async function assertGenerationPreparationPanel(page, label) {
  const metrics = await page.evaluate(() => {
    const rect = (node) => {
      if (!node) return null
      const value = node.getBoundingClientRect()
      return { top: value.top, bottom: value.bottom, left: value.left, right: value.right, width: value.width, height: value.height }
    }
    const root = document.querySelector('.generate-page')
    const empty = document.querySelector('.empty-studio')
    const panel = empty?.querySelector('.preparation-panel')
    const processHeading = document.querySelector('.process-panel .panel-title')
    const resourcesHeading = document.querySelector('.resources-panel .panel-title')
    const flowArt = empty?.querySelector('.production-flow-art')
    const productionPipeline = flowArt?.querySelector('svg.production-pipeline')
    const capabilityZones = [...(empty?.querySelectorAll('.production-capability-zone') || [])]
    const footer = panel?.querySelector('.preparation-footer')
    const footerAction = footer?.querySelector('button')
    const productionFooter = root?.querySelector(':scope > .production-footer')
    const buttons = [...(panel?.querySelectorAll('button') || [])].map((node) => ({
      ...rect(node), text: node.innerText.trim() || node.getAttribute('aria-label') || '',
    }))
    return {
      viewport: { width: innerWidth, height: innerHeight },
      document: { width: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth },
      root: rect(root), rootScrollWidth: root?.scrollWidth || 0, rootClientWidth: root?.clientWidth || 0,
      empty: rect(empty), panel: rect(panel), processHeading: rect(processHeading), resourcesHeading: rect(resourcesHeading),
      heading: panel?.querySelector('.preparation-heading h3')?.innerText.trim() || '',
      text: panel?.innerText.trim() || '',
      legacyEmptyCount: empty?.querySelectorAll('.el-empty').length || 0,
      productionFlowArt: flowArt && {
        ...rect(flowArt),
        tagName: flowArt.tagName.toLowerCase(),
        visible: flowArt.getClientRects().length > 0 && getComputedStyle(flowArt).display !== 'none' && getComputedStyle(flowArt).visibility !== 'hidden',
        learningPlaneCount: flowArt.querySelectorAll('.learning-plane').length,
      },
      productionPipeline: productionPipeline && {
        ...rect(productionPipeline),
        viewBox: productionPipeline.getAttribute('viewBox'),
        visible: productionPipeline.getClientRects().length > 0 && getComputedStyle(productionPipeline).display !== 'none' && getComputedStyle(productionPipeline).visibility !== 'hidden',
      },
      productionCapabilityZones: capabilityZones.map((node) => ({
        ...rect(node),
        text: node.innerText.trim(),
        visible: node.getClientRects().length > 0 && getComputedStyle(node).display !== 'none' && getComputedStyle(node).visibility !== 'hidden',
      })),
      footerActionCount: footer?.querySelectorAll('button').length || 0,
      footerAction: footerAction && {
        ...rect(footerAction),
        text: footerAction.innerText.trim() || footerAction.getAttribute('aria-label') || '',
        visible: footerAction.getClientRects().length > 0 && getComputedStyle(footerAction).display !== 'none' && getComputedStyle(footerAction).visibility !== 'hidden',
      },
      productionFooter: rect(productionFooter),
      productionFooterGap: productionFooter && empty
        ? productionFooter.getBoundingClientRect().top - empty.getBoundingClientRect().bottom
        : null,
      studioGrid: Boolean(document.querySelector('.studio-grid')),
      workbenchPanelCount: document.querySelectorAll('.studio-grid > .process-panel, .studio-grid > .resources-panel').length,
      buttons,
    }
  })
  assert.ok(metrics.panel && metrics.heading && metrics.text, `${label}: generation preparation state should have readable structure: ${JSON.stringify(metrics)}`)
  assert.equal(metrics.legacyEmptyCount, 0, `${label}: old Element Plus empty art should not remain: ${JSON.stringify(metrics)}`)
  assert.ok(metrics.productionFlowArt?.tagName === 'figure' && metrics.productionFlowArt.visible,
    `${label}: initial generation should show its visible production flow figure: ${JSON.stringify(metrics.productionFlowArt)}`)
  assert.ok(metrics.productionPipeline?.visible && metrics.productionFlowArt.learningPlaneCount === 0,
    `${label}: production should use its dedicated pipeline drawing instead of the learning-plane SVG: ${JSON.stringify({ art: metrics.productionFlowArt, pipeline: metrics.productionPipeline })}`)
  assert.equal(metrics.productionCapabilityZones.length, 3,
    `${label}: initial generation should retain three capability zones: ${JSON.stringify(metrics.productionCapabilityZones)}`)
  assert.ok(metrics.productionCapabilityZones.every((zone) => zone.visible && zone.text.length > 0),
    `${label}: each initial production capability zone should be visible and readable: ${JSON.stringify(metrics.productionCapabilityZones)}`)
  assert.equal(metrics.footerActionCount, 1,
    `${label}: initial generation should retain one action in its preparation footer: ${JSON.stringify(metrics.footerAction)}`)
  assert.ok(metrics.footerAction?.visible && metrics.footerAction.text.includes('新建学习方向'),
    `${label}: the new-learning action should remain visible in the preparation footer: ${JSON.stringify(metrics.footerAction)}`)
  assert.ok(metrics.productionFooter && metrics.productionFooterGap >= 0 && metrics.productionFooterGap <= 8,
    `${label}: page footer should stay separated from the main preparation area by 0–8px: ${JSON.stringify({ footer: metrics.productionFooter, empty: metrics.empty, gap: metrics.productionFooterGap })}`)
  assert.ok(metrics.document.width <= metrics.document.clientWidth + 1, `${label}: document horizontal overflow: ${JSON.stringify(metrics)}`)
  assert.ok(metrics.rootScrollWidth <= metrics.rootClientWidth + 1, `${label}: generation root horizontal overflow: ${JSON.stringify(metrics)}`)
  assert.ok(metrics.panel.left >= metrics.empty.left - 1 && metrics.panel.right <= metrics.empty.right + 1,
    `${label}: preparation panel should fit its resource region: ${JSON.stringify(metrics)}`)
  assert.equal(metrics.studioGrid, false, `${label}: no-task/no-profile state should use the standalone empty-studio layout`)
  assert.equal(metrics.workbenchPanelCount, 0, `${label}: empty-studio state should not render process/resource workbench panels`)
  for (const button of metrics.buttons) {
    assert.ok(button.height >= 44, `${label}: preparation actions should remain 44px targets: ${JSON.stringify(button)}`)
    assert.ok(button.left >= -1 && button.right <= metrics.viewport.width + 1, `${label}: preparation action should not be clipped: ${JSON.stringify(button)}`)
  }
  if (metrics.viewport.width >= 1100) {
    assert.ok(Math.abs(metrics.productionPipeline.height - 220) <= 1,
      `${label}: compact desktop production pipeline should be 220px tall: ${JSON.stringify(metrics.productionPipeline)}`)
    assert.ok(metrics.productionPipeline.top >= metrics.panel.top - 1 && metrics.productionPipeline.bottom <= metrics.panel.bottom + 1,
      `${label}: the 220px production pipeline should fit inside the preparation panel: ${JSON.stringify({ pipeline: metrics.productionPipeline, panel: metrics.panel })}`)
    if (metrics.processHeading && metrics.resourcesHeading) {
      assert.ok(Math.abs(metrics.processHeading.top - metrics.resourcesHeading.top) <= 1
        && Math.abs(metrics.processHeading.bottom - metrics.resourcesHeading.bottom) <= 1,
      `${label}: workbench column headings should stay aligned around the compact preparation area: ${JSON.stringify(metrics)}`)
    } else {
      assert.ok(metrics.empty.width >= metrics.root.width * 0.9,
        `${label}: standalone preparation state should use the available desktop width: ${JSON.stringify(metrics)}`)
    }
  }
  evidence.layoutChecks.push({ label, generationPreparation: metrics })
  return metrics
}

async function assertLearningPreparationState(page, label, { busy = false } = {}) {
  await page.locator('.library-empty.preparation-panel').waitFor({ state: 'visible' })
  const metrics = await page.evaluate(() => {
    const panel = document.querySelector('.library-empty.preparation-panel')
    const rect = (node) => {
      if (!node) return null
      const value = node.getBoundingClientRect()
      return { x: value.x, y: value.y, right: value.right, bottom: value.bottom, width: value.width, height: value.height }
    }
    return {
      viewport: { width: innerWidth, height: innerHeight },
      document: { scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth },
      page: { scrollWidth: document.querySelector('.resources-page')?.scrollWidth || 0, clientWidth: document.querySelector('.resources-page')?.clientWidth || 0 },
      pageRect: rect(document.querySelector('.resources-page')),
      contentRect: rect(document.querySelector('.content-area')),
      toolbarRect: rect(document.querySelector('.learning-toolbar')),
      panel: rect(panel),
      busy: panel?.getAttribute('aria-busy'),
      heading: panel?.querySelector('.preparation-heading h3')?.innerText.trim() || '',
      text: panel?.innerText.trim() || '',
      preparationHeading: rect(panel?.querySelector('.preparation-heading')),
      preparationSteps: [...(panel?.querySelectorAll('.preparation-steps > li') || [])].map(rect),
      preparationFooter: rect(panel?.querySelector('.preparation-footer')),
      preparationFooterCount: panel?.querySelectorAll('.preparation-footer').length || 0,
      flowArt: (() => {
        const art = panel?.querySelector('.library-flow-art')
        const style = art ? getComputedStyle(art) : null
        return art ? {
          ...rect(art),
          text: art.innerText?.trim() || '',
          childCount: art.children.length,
          visible: art.getClientRects().length > 0 && style.display !== 'none' && style.visibility !== 'hidden',
          learningPlaneCount: art.querySelectorAll('svg.learning-plane').length,
          productionPipelineCount: art.querySelectorAll('svg.production-pipeline').length,
        } : null
      })(),
      flowZones: [...(panel?.querySelectorAll('.library-flow-zone, .library-capability-zone, [data-flow-zone], [data-capability-zone]') || [])]
        .map(node => ({ text: node.innerText.trim(), ...rect(node) })),
      stepsCount: panel?.querySelectorAll('.preparation-steps > li').length || 0,
      legacyEmptyCount: panel?.querySelectorAll('.el-empty').length || 0,
      shelfCount: document.querySelectorAll('.resource-shelf').length,
      readerCount: document.querySelectorAll('.reading-stage .reader-card, .reading-stage .courseware-viewer').length,
      panelButtons: [...(panel?.querySelectorAll('button') || [])].map((node) => {
        const value = node.getBoundingClientRect()
        return { text: node.innerText.trim() || node.getAttribute('aria-label') || '', x: value.x, y: value.y, right: value.right, bottom: value.bottom, width: value.width, height: value.height, visible: node.getClientRects().length > 0 && getComputedStyle(node).visibility !== 'hidden' }
      }),
      toolbarButtons: [...document.querySelectorAll('.learning-toolbar button')].map((node) => {
        const value = node.getBoundingClientRect()
        return { text: node.innerText.trim() || node.getAttribute('aria-label') || '', x: value.x, right: value.right, width: value.width, height: value.height, visible: node.getClientRects().length > 0 && getComputedStyle(node).visibility !== 'hidden' }
      }),
    }
  })
  assert.ok(metrics.panel, `${label}: learning should show a preparation panel instead of a blank workspace`)
  assert.ok(metrics.heading.length > 0 && metrics.text.length > 0, `${label}: preparation state should have a readable heading and explanation`)
  assert.equal(metrics.busy, String(busy), `${label}: preparation busy state should match the actual resource load: ${JSON.stringify(metrics)}`)
  assert.equal(metrics.legacyEmptyCount, 0, `${label}: the old Element Plus empty illustration should not remain`)
  assert.equal(metrics.shelfCount, 0, `${label}: resource shelf should not appear before any resource is published`)
  assert.equal(metrics.readerCount, 0, `${label}: reader should not be fabricated before a resource exists`)
  assert.equal(metrics.stepsCount, 3, `${label}: learning preparation should retain its three practical next steps`)
  assert.ok(metrics.flowArt?.visible && metrics.flowArt.childCount > 0,
    `${label}: the learning preparation should show its scientific learning-flow mark: ${JSON.stringify(metrics.flowArt)}`)
  assert.equal(metrics.flowArt.learningPlaneCount, 1,
    `${label}: library preparation should preserve its original learning-plane illustration: ${JSON.stringify(metrics.flowArt)}`)
  assert.equal(metrics.flowArt.productionPipelineCount, 0,
    `${label}: the production pipeline should remain separate from the learning illustration: ${JSON.stringify(metrics.flowArt)}`)
  assert.ok(metrics.flowZones.length === 3 && metrics.flowZones.every(zone => zone.text.length > 0),
    `${label}: the flow illustration should expose three readable capability zones: ${JSON.stringify(metrics.flowZones)}`)
  assert.ok(metrics.document.scrollWidth <= metrics.document.clientWidth + 1, `${label}: document horizontal overflow: ${JSON.stringify(metrics)}`)
  assert.ok(metrics.page.scrollWidth <= metrics.page.clientWidth + 1, `${label}: Resources page horizontal overflow: ${JSON.stringify(metrics)}`)
  for (const target of [...metrics.panelButtons, ...metrics.toolbarButtons]) {
    if (!target.visible) continue
    assert.ok(target.height >= 44, `${label}: preparation action must remain a 44px target: ${JSON.stringify(target)}`)
    assert.ok(target.x >= -1 && target.right <= metrics.viewport.width + 1, `${label}: preparation action should fit the viewport: ${JSON.stringify(target)}`)
  }
  if (metrics.viewport.width >= 1100) {
    assert.ok(metrics.contentRect && metrics.toolbarRect, `${label}: desktop preparation should be measured against the available content height`)
    assert.ok(metrics.panel.bottom <= metrics.contentRect.bottom + 1 && metrics.panel.bottom >= metrics.contentRect.bottom - 32,
      `${label}: desktop preparation should use the available lower workspace instead of leaving a large blank tail: ${JSON.stringify({ panel: metrics.panel, content: metrics.contentRect })}`)
    if (!busy) {
      assert.ok(metrics.preparationFooter && metrics.preparationFooterCount === 1,
        `${label}: settled desktop preparation should retain its action footer`)
      assert.ok(metrics.preparationFooter.bottom >= metrics.panel.bottom - 48,
        `${label}: desktop footer should remain near the bottom of the expanded preparation area: ${JSON.stringify({ footer: metrics.preparationFooter, panel: metrics.panel })}`)
      for (const button of metrics.panelButtons.filter(item => item.visible)) {
        assert.ok(button.bottom <= metrics.viewport.height + 1,
          `${label}: settled desktop preparation actions should be visible without scrolling: ${JSON.stringify(button)}`)
      }
    }
  }
  evidence.layoutChecks.push({ label, learningPreparation: metrics })
  return metrics
}

async function assertLearningPreparationActionsReachable(page, label) {
  const actions = page.locator('.library-empty.preparation-panel button:visible')
  const count = await actions.count()
  assert.ok(count > 0, `${label}: mobile preparation state should expose an existing action`)
  for (let index = 0; index < count; index += 1) {
    const action = actions.nth(index)
    await action.scrollIntoViewIfNeeded()
    const metrics = await action.evaluate((node) => {
      const rect = node.getBoundingClientRect()
      return {
        text: node.innerText.trim() || node.getAttribute('aria-label') || '',
        viewport: { width: innerWidth, height: innerHeight },
        rect: { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, width: rect.width, height: rect.height },
        visible: node.getClientRects().length > 0 && getComputedStyle(node).visibility !== 'hidden',
      }
    })
    assert.ok(metrics.visible && metrics.rect.height >= 44, `${label}: preparation action should remain visible and at least 44px high: ${JSON.stringify(metrics)}`)
    assert.ok(metrics.rect.left >= -1 && metrics.rect.right <= metrics.viewport.width + 1
      && metrics.rect.top >= -1 && metrics.rect.bottom <= metrics.viewport.height + 1,
    `${label}: natural scrolling should make each preparation action fully reachable: ${JSON.stringify(metrics)}`)
    evidence.layoutChecks.push({ label: `${label}-action-${index + 1}`, learningPreparationAction: metrics })
  }
}

async function assertLearningPrimaryVisualAndFocus(page, label) {
  const primary = page.locator('.library-empty .library-preparation-actions .el-button--primary:visible')
  assert.equal(await primary.count(), 1, `${label}: the initial learning state should expose one visible body primary action`)
  const initial = await primary.evaluate((node) => {
    const rect = node.getBoundingClientRect()
    const style = getComputedStyle(node)
    return {
      text: node.innerText.trim(),
      rect: { x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom, height: rect.height },
      color: style.color,
      backgroundColor: style.backgroundColor,
      backgroundImage: style.backgroundImage,
      borderColor: style.borderColor,
      outlineColor: style.outlineColor,
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      boxShadow: style.boxShadow,
    }
  })
  assert.ok(initial.rect.height >= 44, `${label}: primary action should remain a 44px target: ${JSON.stringify(initial)}`)
  const contrastStart = evidence.contrastChecks.length
  await assertContrast(page, label)
  const contrastChecks = evidence.contrastChecks.slice(contrastStart).flatMap(item => item.checks)
    .filter(item => item.selector === '.library-empty .library-preparation-actions .el-button--primary')
  assert.equal(contrastChecks.length, 1, `${label}: contrast should be measured on the visible body primary only: ${JSON.stringify(contrastChecks)}`)
  assert.ok(contrastChecks[0].contrast >= 4.5, `${label}: initial-state primary contrast should be at least 4.5:1: ${JSON.stringify(contrastChecks[0])}`)

  await primary.focus()
  await page.keyboard.press('Tab')
  await page.keyboard.press('Shift+Tab')
  await page.waitForTimeout(50)
  const focused = await primary.evaluate((node) => {
    const style = getComputedStyle(node)
    return {
      active: document.activeElement === node,
      focusVisible: node.matches(':focus-visible'),
      outlineColor: style.outlineColor,
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      boxShadow: style.boxShadow,
    }
  })
  assert.equal(focused.active, true, `${label}: primary action should retain keyboard focus`)
  assert.equal(focused.focusVisible, true, `${label}: primary action should expose keyboard focus-visible styling`)
  assert.ok((focused.outlineStyle !== 'none' && Number.parseFloat(focused.outlineWidth) >= 2)
    || (focused.boxShadow !== 'none' && focused.boxShadow !== initial.boxShadow),
  `${label}: keyboard focus ring should be visible: ${JSON.stringify({ initial, focused })}`)
  evidence.interactionChecks.push({ label, initial, contrast: contrastChecks[0], focused })
}

async function openLearningPreparationPage(browser, base, scenario, viewport = baseViewport, { delayJobsMs = 0 } = {}) {
  const page = await newPage(browser, base, scenario, viewport)
  if (delayJobsMs) state.jobsDelayMs = delayJobsMs
  await page.goto(base + '/resources?learnerId=learner-1&runId=run-main', { waitUntil: 'domcontentloaded' })
  await page.locator('.resources-layout').waitFor({ state: 'visible' })
  return page
}

async function testPreparationResponsiveStates(browser, base) {
  const generationPage = await newPage(browser, base, 'no-task')
  try {
    for (const viewport of [{ width: 390, height: 844 }, { width: 375, height: 667 }]) {
      await generationPage.setViewportSize(viewport)
      await generationPage.evaluate(() => {
        document.querySelector('.content-area')?.scrollTo(0, 0)
        document.querySelector('.generate-page')?.scrollTo(0, 0)
      })
      await waitForLayout(generationPage, false)
      const metrics = await geometry(generationPage, `generation-empty-${viewport.width}x${viewport.height}`, false)
      const preparation = generationPage.locator('.empty-studio .preparation-panel')
      assert.ok(await preparation.isVisible(), 'mobile no-task state should retain its preparation panel')
      await assertGenerationPreparationPanel(generationPage, `mobile-${viewport.width}x${viewport.height}`)
      assert.equal(await generationPage.locator('.empty-studio .el-empty').count(), 0, 'mobile no-task state should not show the legacy empty illustration')
      const primary = generationPage.getByRole('button', { name: '新建学习方向' })
      await primary.scrollIntoViewIfNeeded()
      const rect = await primary.boundingBox()
      assert.ok(rect && rect.height >= 44 && rect.x >= -1 && rect.x + rect.width <= viewport.width + 1, 'mobile preparation action should remain reachable without horizontal clipping: ' + JSON.stringify({ viewport, rect }))
      assert.ok(rect.y >= -1 && rect.y + rect.height <= viewport.height + 1, 'mobile preparation action should be reachable by natural scrolling: ' + JSON.stringify({ viewport, rect, document: metrics.document }))
      await capture(generationPage, `mobile-empty-${viewport.width}x${viewport.height}`)
    }
    const shortViewport = { width: 1280, height: 640 }
    await generationPage.setViewportSize(shortViewport)
    await generationPage.evaluate(() => {
      document.querySelector('.content-area')?.scrollTo(0, 0)
      document.querySelector('.generate-page')?.scrollTo(0, 0)
    })
    await waitForLayout(generationPage)
    await assertGenerationPreparationPanel(generationPage, 'short-window-1280x640')
    const shortAction = generationPage.getByRole('button', { name: '新建学习方向' })
    await shortAction.scrollIntoViewIfNeeded()
    const shortRect = await shortAction.boundingBox()
    assert.ok(shortRect && shortRect.height >= 44 && shortRect.y >= -1 && shortRect.y + shortRect.height <= shortViewport.height + 1,
      'short-window preparation action should remain reachable by natural scrolling: ' + JSON.stringify({ shortViewport, rect: shortRect }))
    await capture(generationPage, 'generation-empty-1280x640-short')
    assert.equal(state.writes.length, 0, 'mobile empty-state inspection must not write to the fixture API')
    await assertNoExternalOrUnexpected('generation-empty-mobile')
  } finally { await generationPage.close() }
}

async function testLearningPreparationStates(browser, base) {
  const loadingPage = await openLearningPreparationPage(browser, base, 'no-task', baseViewport, { delayJobsMs: 500 })
  try {
    const loading = loadingPage.locator('.library-empty.preparation-panel')
    await loading.waitFor({ state: 'visible' })
    await loadingPage.waitForFunction(() => document.querySelector('.library-empty.preparation-panel')?.getAttribute('aria-busy') === 'true')
    await assertLearningPreparationState(loadingPage, 'learning-initial-loading', { busy: true })
    await capture(loadingPage, 'resources-preparation-loading')
    await loadingPage.waitForFunction(() => document.querySelector('.library-empty.preparation-panel')?.getAttribute('aria-busy') === 'false', null, { timeout: 8000 })
    await assertLearningPreparationState(loadingPage, 'learning-loading-settled')
    evidence.scenarios.push({ name: 'learning-initial-loading', busyObserved: true, settled: true })
    assert.equal(state.writes.length, 0, 'learning initial loading should remain read-only')
    await assertNoExternalOrUnexpected('learning-initial-loading')
  } finally { await loadingPage.close() }

  const noProfilePage = await openLearningPreparationPage(browser, base, 'no-profile', { width: 390, height: 844 })
  let noProfileHeading = ''
  try {
    const metrics = await assertLearningPreparationState(noProfilePage, 'learning-no-profile')
    noProfileHeading = metrics.heading
    assert.equal(state.profiles.length, 0, 'no-profile learning fixture must contain no profiles')
    assert.ok(/画像|方向/.test(metrics.text), 'no-profile preparation should explain the missing learning profile')
    const create = noProfilePage.getByRole('button', { name: '新建学习方向' })
    assert.ok(await create.isVisible(), 'no-profile preparation should preserve the existing create-direction entry')
    await capture(noProfilePage, 'resources-preparation-no-profile')
    await assertLearningPrimaryVisualAndFocus(noProfilePage, 'learning-preparation-primary-cta')
    await assertLearningPreparationActionsReachable(noProfilePage, 'learning-no-profile-mobile')
    await capture(noProfilePage, 'resources-preparation-no-profile-action-reachable')
    evidence.scenarios.push({ name: 'learning-no-profile', profiles: state.profiles.length })
    assert.equal(state.writes.length, 0, 'no-profile state inspection must not create real business records')
    await assertNoExternalOrUnexpected('learning-no-profile')
  } finally { await noProfilePage.close() }

  const noTaskPage = await openLearningPreparationPage(browser, base, 'no-task', { width: 390, height: 844 })
  let noTaskHeading = ''
  try {
    const metrics = await assertLearningPreparationState(noTaskPage, 'learning-no-task')
    noTaskHeading = metrics.heading
    assert.ok(state.profiles.length > 0, 'no-task learning fixture should retain an existing profile')
    assert.equal(state.jobsByLearner['learner-1'].length, 0, 'no-task learning fixture should contain no generation task')
    assert.ok(/任务|资源|生成|学习/.test(metrics.text), 'no-task preparation should explain that resources or a task are missing')
    assert.ok(await noTaskPage.getByRole('button', { name: '新建学习方向' }).isVisible(), 'no-task preparation should preserve the existing create-direction entry')
    assert.notEqual(noTaskHeading, noProfileHeading, 'no-profile and no-task states should give distinct guidance')
    await capture(noTaskPage, 'resources-preparation-no-task-390x844')
    await assertLearningPreparationActionsReachable(noTaskPage, 'learning-no-task-mobile')
    await capture(noTaskPage, 'resources-preparation-no-task-actions-reachable')
    evidence.scenarios.push({ name: 'learning-no-task', jobs: state.jobsByLearner['learner-1'].length })
    assert.equal(state.writes.length, 0, 'no-task state inspection must remain read-only')
    await assertNoExternalOrUnexpected('learning-no-task')
  } finally { await noTaskPage.close() }

  const waitingPage = await openLearningPreparationPage(browser, base, 'queued')
  try {
    const metrics = await assertLearningPreparationState(waitingPage, 'learning-task-waiting-no-resources')
    assert.equal(state.jobsByLearner['learner-1'][0]?.job_status, 'queued', 'waiting learning fixture should retain the queued task state')
    assert.equal(state.resourcesByRun['run-main'].length, 0, 'waiting learning fixture must not fabricate published resources')
    assert.ok(/排队|等待|生成|准备/.test(metrics.text), 'waiting state should communicate that real task output is still pending')
    assert.notEqual(metrics.heading, noTaskHeading, 'waiting-for-output guidance should differ from the no-task state')
    await capture(waitingPage, 'resources-preparation-task-waiting')
    evidence.scenarios.push({ name: 'learning-task-waiting-no-resources', status: state.jobsByLearner['learner-1'][0]?.job_status, resources: state.resourcesByRun['run-main'].length })
    assert.equal(state.writes.length, 0, 'waiting-state inspection must remain read-only')
    await assertNoExternalOrUnexpected('learning-task-waiting-no-resources')
  } finally { await waitingPage.close() }

  const desktopCollapsedPage = await openLearningPreparationPage(browser, base, 'no-task', { width: 1331, height: 871 })
  try {
    await setResourcesSidebar(desktopCollapsedPage, true)
    const metrics = await assertLearningPreparationState(desktopCollapsedPage, 'learning-no-task-1331x871-collapsed')
    assert.equal(state.jobsByLearner['learner-1'].length, 0, 'collapsed desktop learning fixture should remain in the no-task state')
    assert.ok(metrics.panel.bottom >= metrics.contentRect.bottom - 32, 'collapsed desktop preparation should still use the available lower workspace')
    await capture(desktopCollapsedPage, 'resources-preparation-no-task-1331x871-collapsed')
    assert.equal(state.writes.length, 0, 'collapsed desktop preparation inspection must remain read-only')
    await assertNoExternalOrUnexpected('learning-no-task-1331x871-collapsed')
  } finally { await desktopCollapsedPage.close() }
}

async function testDesktopFitMatrix(browser, base) {
  const viewports = [
    { width: 1393, height: 871 },
    { width: 1331, height: 871 },
    { width: 1440, height: 900 },
    { width: 1280, height: 640 },
  ]
  const page = await newPage(browser, base, 'long', viewports[0])
  await page.waitForFunction(() => (document.querySelector('.process-scroll')?.scrollHeight || 0) > (document.querySelector('.process-scroll')?.clientHeight || Infinity))
  await page.waitForFunction(() => (document.querySelector('.resource-stage')?.scrollHeight || 0) > (document.querySelector('.resource-stage')?.clientHeight || Infinity))
  await assertResourcePhases(page, 'long-desktop', {
    longMetadata: true, captureName: 'desktop-resource-delivery-long-metadata', expectedPhase: '已发布', expectAllPublished: true,
  })
  const graph = page.locator('.execution-graph')
  assert.equal(await graph.locator('.execution-graph-header, .execution-graph-modes').count(), 0, 'the chain should reserve its canvas for execution records')
  assert.equal(await graph.locator('.execution-graph-node').count(), 90, 'the long fixture should retain all ninety unique unknown node records')
  assert.equal(await graph.locator('.execution-graph-node[data-inspectable="false"]').count(), 90, 'unknown long-fixture nodes should remain visible without becoming interactive')
  assert.equal(await graph.locator('button.execution-graph-node').count(), 0, 'unknown long-fixture records must not add keyboard actions')
  const longGraphScroll = await page.locator('.process-scroll').evaluate((node) => ({ scrollHeight: node.scrollHeight, clientHeight: node.clientHeight }))
  assert.ok(longGraphScroll.scrollHeight > longGraphScroll.clientHeight, 'all ninety unknown nodes should remain reachable through the process panel scroll region')
  evidence.interactionChecks.push({ scenario: 'workflow-long-unknown-nodes', count: 90, actualCalls: true, scrollRegion: '.process-scroll', inspectable: 0 })
  for (const viewport of viewports) {
    await page.setViewportSize(viewport)
    await waitForLayout(page, true)
    for (const collapsed of [false, true]) {
      await setSidebar(page, collapsed)
      const label = viewport.width + 'x' + viewport.height + (collapsed ? '-collapsed' : '-expanded')
      const metrics = await geometry(page, label, true)
      assert.ok(Math.abs(metrics.headings.process.top - metrics.headings.resources.top) <= 1, label + ': panel headings differ vertically')
      if (viewport.width === 1393 && !collapsed) await capture(page, 'desktop-long-expanded')
      if (viewport.width === 1393 && collapsed) await capture(page, 'desktop-long-collapsed')
    }
  }
  await page.setViewportSize({ width: 1393, height: 871 })
  await setSidebar(page, true)
  await assertInternalScroll(page, '1393x871-long-collapsed')
  await assertContrast(page, '1393x871-long-collapsed')
  await capture(page, 'desktop-long-scrolled')
  await page.setViewportSize({ width: 390, height: 844 })
  await waitForLayout(page, false)
  await assertResourcePhases(page, 'long-mobile', {
    longMetadata: true, captureName: 'mobile-resource-delivery-long-metadata', expectedPhase: '已发布', expectAllPublished: true,
  })
  await assertNoExternalOrUnexpected('desktop-fit-matrix')
  await page.close()
}

async function testNaturalFallback(browser, base) {
  const viewports = [
    { width: 1024, height: 768 },
    { width: 768, height: 1024 },
    { width: 390, height: 844 },
    { width: 375, height: 667 },
    { width: 844, height: 390 },
  ]
  const page = await newPage(browser, base, 'long', viewports[0])
  for (const viewport of viewports) {
    await page.setViewportSize(viewport)
    await waitForLayout(page, false)
    await page.evaluate(() => {
      window.scrollTo(0, 0)
      const area = document.querySelector('.content-area')
      if (area) area.scrollTop = 0
      const root = document.querySelector('.generate-page')
      if (root) root.scrollTop = 0
    })
    const label = viewport.width + 'x' + viewport.height + '-natural'
    const metrics = await geometry(page, label)
    assert.ok(metrics.document.width <= viewport.width + 1, label + ': no horizontal overflow')
    assert.ok(metrics.externalOverflow.length === 0, label + ': visible content extends beyond the viewport: ' + JSON.stringify(metrics.externalOverflow))
    if (viewport.width === 390) await capture(page, 'mobile-top')
    await page.evaluate(() => {
      const area = document.querySelector('.content-area')
      if (area) area.scrollTop = area.scrollHeight
      window.scrollTo(0, document.documentElement.scrollHeight)
      const resource = document.querySelector('.resource-stage')
      if (resource) resource.scrollTop = resource.scrollHeight
    })
    const pageScroll = await page.evaluate(() => document.documentElement.scrollTop + (document.querySelector('.content-area')?.scrollTop || 0))
    const markdownEnd = await page.getByText('这是滚动到正文末尾后应当完整可读的标记。', { exact: true }).count()
    assert.equal(markdownEnd, 1, label + ': long markdown tail must remain in the document')
    const endIsReachable = await page.getByText('这是滚动到正文末尾后应当完整可读的标记。', { exact: true }).evaluate((node) => {
      const rect = node.getBoundingClientRect()
      return rect.top >= -1 && rect.bottom <= innerHeight + 1
    })
    assert.equal(endIsReachable, true, label + ': scrolling should expose the full long-markdown tail')
    assert.ok(pageScroll > 0, label + ': natural fallback should allow page-area scrolling')
    const learningButton = page.locator('.learning-mode-action')
    if (await learningButton.count()) {
      const buttonHeight = await learningButton.evaluate((node) => node.getBoundingClientRect().height)
      assert.ok(buttonHeight >= 44, label + ': main learning action should remain at least 44px high')
    }
    if (viewport.width === 390) await capture(page, 'mobile-long-natural')
  }
  await assertNoExternalOrUnexpected('natural-fallback-matrix')
  await page.close()
}

function commandRequestGate(status = 0) {
  let release
  const promise = new Promise(resolve => { release = resolve })
  return { promise, release, status, started: false }
}

async function commandUiSnapshot(page) {
  return page.evaluate(() => ({
    run: localStorage.getItem('current_generation_run_id'),
    status: localStorage.getItem('current_generation_status'),
    summary: document.querySelector('.summary-code')?.textContent.trim(),
    content: document.querySelector('.resource-stage')?.textContent,
    notices: [...document.querySelectorAll('.el-message')].map(node => node.textContent.trim()),
    appendBusy: document.querySelector('.status-action-append')?.classList.contains('is-loading'),
  }))
}

async function settleCommandResponse(page, response) {
  await response.finished()
  // Let XHR promise callbacks and Vue rendering run without a fixed delay.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
}

async function chooseCommandContext(page, name, optionName) {
  // This matrix repeatedly selects an already focused field. Focus appearance
  // is covered by the original layout matrix; here exercise the actual options.
  await page.getByRole('combobox', { name }).click()
  await page.getByRole('option', { name: optionName }).click()
}

async function testContinuationContextRaces(browser, base) {
  const page = await newPage(browser, base, 'command-race')
  const gate = commandRequestGate()
  state.continuationGate = gate
  await appendTextTypes(page, false, ['案例分析'])
  await waitForFixture(() => gate.started, 'accepted continuation held before response')
  assert.equal(findJob(gate.runId)?.job_status, 'queued', 'server task is accepted before switching the page')
  await page.keyboard.press('Escape')
  await page.getByRole('heading', { name: '追加学习资源' }).waitFor({ state: 'hidden' })
  await chooseCommandContext(page, '资源批次', /run-othe/i)
  await page.locator('.resource-stage').getByText('切换后应继续保留这份内容。', { exact: true }).waitFor()
  const before = await commandUiSnapshot(page)
  const requestsBefore = state.requests.length
  const delivered = page.waitForResponse(response => response.url().endsWith('/continuations'))
  gate.release()
  await settleCommandResponse(page, await delivered)
  const after = await commandUiSnapshot(page)
  await capture(page, 'command-late-post-switch')
  assert.equal(after.run, 'run-other', 'late continuation must preserve B persistent selection')
  assert.equal(after.summary, 'RUN-OTHE', 'late continuation must preserve the selected B run')
  assert.equal(after.content, before.content, 'late continuation must preserve B resources')
  assert.deepEqual(after.notices, [], 'late continuation must not notify in B')
  assert.equal(after.appendBusy, false, 'old context no longer owns the append button')
  assert.equal(state.writes.length, 1, 'switching does not re-submit accepted generation')
  assert.equal(state.requests.slice(requestsBefore).filter(item => item.path === '/api/generate/jobs'
    || item.path.startsWith(`/api/runs/${gate.runId}/`)).length, 0,
  'stale command does not refresh jobs or start a child subscription')
  assert.ok(findJob(gate.runId), 'ignoring a response retains the accepted task')
  evidence.interactionChecks.push({ scenario: 'command-late-post-switch', before, after, acceptedRun: gate.runId })
  await chooseCommandContext(page, '学习画像', /周明远/)
  await page.waitForFunction(() => document.querySelector('.summary-code')?.textContent.trim() === '-')
  await chooseCommandContext(page, '学习画像', /林知行/)
  await page.waitForFunction(() => document.querySelector('.summary-code')?.textContent.trim() === 'CONTINUE')
  assert.equal(await page.evaluate(() => localStorage.getItem('current_generation_run_id')), gate.runId,
    'returning to the learner discovers the accepted task through the ordinary list')
  assert.equal(state.writes.length, 1, 'rediscovery cannot re-submit the command')
  await assertNoExternalOrUnexpected('command-late-post-switch')
  await page.close()

  for (const mode of ['failed-post', 'ABA']) {
    const racePage = await newPage(browser, base, 'command-race')
    const postGate = commandRequestGate(mode === 'failed-post' ? 503 : 0)
    state.continuationGate = postGate
    await appendTextTypes(racePage, false, ['案例分析'])
    await waitForFixture(() => postGate.started, `${mode} continuation held`)
    await racePage.keyboard.press('Escape')
    await racePage.getByRole('heading', { name: '追加学习资源' }).waitFor({ state: 'hidden' })
    await chooseCommandContext(racePage, '资源批次', /run-othe/i)
    await racePage.locator('.resource-stage').getByText('切换后应继续保留这份内容。', { exact: true }).waitFor()
    if (mode === 'ABA') {
      await chooseCommandContext(racePage, '资源批次', /run-main/i)
      await racePage.locator('.resource-stage').getByText('从验收来源中完成一个可复核步骤。', { exact: true }).waitFor()
    }
    await openAppendDialog(racePage, '文本学习资源')
    const beforeResponse = await commandUiSnapshot(racePage)
    const response = racePage.waitForResponse(item => item.url().endsWith('/continuations'))
    postGate.release()
    await settleCommandResponse(racePage, await response)
    const afterResponse = await commandUiSnapshot(racePage)
    assert.deepEqual(afterResponse, beforeResponse, `${mode}: late completion leaves the current UI intact`)
    assert.equal(await racePage.getByRole('heading', { name: '追加学习资源' }).isVisible(), true,
      'an old completion cannot close a new append dialog')
    assert.equal(state.writes.length, 1)
    assert.equal(state.requests.some(item => item.path.startsWith(`/api/runs/${postGate.runId}/`)), false)
    evidence.interactionChecks.push({ scenario: `command-${mode}`, before: beforeResponse, after: afterResponse })
    await assertNoExternalOrUnexpected(`command-${mode}`)
    await racePage.close()
  }

  for (const status of [200, 503]) {
    const listPage = await newPage(browser, base, 'command-race')
    const listGate = commandRequestGate(status)
    state.jobsGetGate = listGate
    await appendTextTypes(listPage, false, ['案例分析'])
    await waitForFixture(() => listGate.started, 'command refresh held after continuation response')
    await listPage.keyboard.press('Escape')
    await listPage.getByRole('heading', { name: '追加学习资源' }).waitFor({ state: 'hidden' })
    await chooseCommandContext(listPage, '资源批次', /run-othe/i)
    await listPage.locator('.resource-stage').getByText('切换后应继续保留这份内容。', { exact: true }).waitFor()
    await listPage.locator('.connection-state.is-terminal').waitFor()
    const beforeList = await commandUiSnapshot(listPage)
    const subscriptionReads = () => state.requests.filter(item => item.path === '/api/runs/run-other/events'
      || (item.path === '/api/runs/run-other/timeline' && item.query.limit === '500')).length
    const subscriptionReadsBefore = subscriptionReads()
    const response = listPage.waitForResponse(item => new URL(item.url()).pathname === '/api/generate/jobs')
    listGate.release()
    await settleCommandResponse(listPage, await response)
    const afterList = await commandUiSnapshot(listPage)
    assert.deepEqual(afterList, beforeList, `list ${status}: old refresh cannot write selection/resources/errors/notice`)
    assert.equal(subscriptionReads(), subscriptionReadsBefore,
      'old command cannot restart even the newly selected run subscription')
    assert.equal(state.requests.some(item => item.path.startsWith('/api/runs/continue-1/')), false)
    assert.equal(state.writes.length, 1)
    evidence.interactionChecks.push({ scenario: `command-stale-list-${status}`, before: beforeList, after: afterList })
    await assertNoExternalOrUnexpected(`command-stale-list-${status}`)
    await listPage.close()
  }

  const failedListPage = await newPage(browser, base, 'command-race')
  const failedListGate = commandRequestGate(503)
  state.jobsGetGate = failedListGate
  await appendTextTypes(failedListPage, false, ['案例分析'])
  await waitForFixture(() => failedListGate.started, 'current command refresh held')
  const failedResponse = failedListPage.waitForResponse(item => new URL(item.url()).pathname === '/api/generate/jobs')
  failedListGate.release()
  await settleCommandResponse(failedListPage, await failedResponse)
  assert.equal(await failedListPage.getByRole('heading', { name: '追加学习资源' }).isVisible(), true)
  assert.equal(await failedListPage.getByRole('button', { name: '开始追加' }).evaluate(node => node.classList.contains('is-loading')), false)
  const failedSnapshot = await commandUiSnapshot(failedListPage)
  assert.deepEqual(failedSnapshot.notices, ['任务列表加载失败'], 'current list failure is explicit, never a command success')
  assert.equal(state.requests.some(item => item.path.startsWith('/api/runs/continue-1/')), false)
  assert.equal(state.writes.length, 1)
  assert.ok(findJob('continue-1'), 'a list failure does not remove the accepted server task')
  evidence.interactionChecks.push({ scenario: 'command-current-list-failure', after: failedSnapshot })
  await assertNoExternalOrUnexpected('command-current-list-failure')
  await failedListPage.close()

  const ownerPage = await newPage(browser, base, 'command-race')
  const oldListGate = commandRequestGate(), currentListGate = commandRequestGate()
  try {
    oldListGate.flushHeaders = currentListGate.flushHeaders = true
    state.jobsGetGate = oldListGate
    const oldResponse = ownerPage.waitForResponse(item => new URL(item.url()).pathname === '/api/generate/jobs')
    await appendTextTypes(ownerPage, false, ['案例分析'])
    await waitForFixture(() => oldListGate.started, 'old command list is pending')
    await oldResponse
    await ownerPage.keyboard.press('Escape')
    await ownerPage.getByRole('heading', { name: '追加学习资源' }).waitFor({ state: 'hidden' })
    await chooseCommandContext(ownerPage, '资源批次', /run-othe/i)
    await ownerPage.locator('.resource-stage').getByText('切换后应继续保留这份内容。', { exact: true }).waitFor()
    state.jobsGetGate = currentListGate
    const currentResponse = ownerPage.waitForResponse(item => new URL(item.url()).pathname === '/api/generate/jobs')
    await appendTextTypes(ownerPage, false, ['案例分析'])
    await waitForFixture(() => currentListGate.started, 'new command list is pending')
    assert.equal(state.writes.length, 2)
    oldListGate.release()
    await settleCommandResponse(ownerPage, await oldResponse)
    assert.equal(await ownerPage.getByRole('button', { name: '开始追加' }).evaluate(node => node.classList.contains('is-loading')), true,
      'old list finally must not clear the new command busy state')
    assert.equal((await ownerPage.locator('.production-status').innerText()).trim(), '正在加载任务',
      'old list finally must not clear a newer list request loading state')
    assert.deepEqual((await commandUiSnapshot(ownerPage)).notices, [])
    currentListGate.release()
    await settleCommandResponse(ownerPage, await currentResponse)
    await ownerPage.getByRole('heading', { name: '追加学习资源' }).waitFor({ state: 'hidden' })
    await waitForFixture(() => state.requests.some(item => item.path === '/api/runs/continue-2/events'), 'new owner subscription')
    const current = await commandUiSnapshot(ownerPage)
    assert.equal(current.run, 'continue-2')
    assert.equal(current.appendBusy, false)
    assert.deepEqual(current.notices, ['已追加：案例分析'])
    assert.equal(state.requests.some(item => item.path.startsWith('/api/runs/continue-1/')), false)
    assert.equal(state.writes.length, 2)
    evidence.interactionChecks.push({ scenario: 'command-list-loading-owner', after: current })
    await assertNoExternalOrUnexpected('command-list-loading-owner')
  } finally {
    oldListGate.release()
    currentListGate.release()
    await ownerPage.close()
  }
}

async function testSwitchesRefreshAndErrors(browser, base) {
  const page = await newPage(browser, base, 'multi', baseViewport, { delayJobsMs: 350 })
  await chooseOption(page, '资源批次', /run-queu/i)
  assert.ok((await page.locator('.generate-page').innerText()).includes('排队中'), 'batch selector should switch to queued run')
  await page.locator('.resources-panel > .resource-toolbar .task-actions').getByRole('button', { name: '刷新状态', exact: true }).click()
  await waitForFixture(() => state.requests.some((item) => item.path === '/api/generate/jobs/run-queued'), 'selected run status refresh')
  const statusRequests = state.requests.filter((item) => item.path === '/api/generate/jobs/run-queued')
  assert.ok(statusRequests.length >= 1, 'refresh should request the selected job status')
  await chooseOption(page, '学习画像', /周明远/)
  await page.waitForFunction(() => document.querySelector('.generate-page')?.textContent.includes('数据工程'))
  await waitForFixture(() => state.requests.some((item) => item.path === '/api/runs/run-alt/timeline'), 'profile switch default-run timeline')
  assert.equal((await page.locator('.summary-code').innerText()).trim(), 'RUN-ALT', 'profile switch should select the new profile default run')
  evidence.interactionChecks.push({ scenario: 'multi', selectedProfile: 'learner-2', selectedRun: 'run-queued', statusRequests: statusRequests.length })
  await assertNoExternalOrUnexpected('switch-and-refresh')
  await page.close()

  const deletePage = await newPage(browser, base, 'multi')
  await inspectElementSelect({
    page: deletePage, suite: 'generation', evidenceDir: reportDir, id: 'generation-profile-delete-clearance',
    select: deletePage.locator('.task-selector .task-select').first(),
    protectEndControlSelector: '.profile-delete', getWriteCount: () => state.writes.length,
  })
  await deletePage.getByRole('combobox', { name: '学习画像' }).click()
  await deletePage.locator('.profile-select-dropdown').locator('.profile-delete').first().click()
  const deleteDialog = deletePage.getByRole('dialog').filter({ hasText: '删除学习画像' })
  await deleteDialog.waitFor({ state: 'visible' })
  assert.ok((await deleteDialog.innerText()).includes('此操作无法撤销'), 'profile delete dialog should explain the confirmation')
  await deleteDialog.getByRole('button', { name: '取消', exact: true }).click()
  await deleteDialog.waitFor({ state: 'hidden' })
  assert.equal(state.writes.length, 0, 'cancelling profile deletion must not write to the fixture API')
  evidence.interactionChecks.push({ scenario: 'profile-delete-cancel', cancelled: true })
  await assertNoExternalOrUnexpected('profile-delete-confirm')
  await deletePage.close()

  const errorPage = await newPage(browser, base, 'running', baseViewport, { failStatus: 1 })
  await errorPage.locator('.resources-panel > .resource-toolbar .task-actions').getByRole('button', { name: '刷新状态', exact: true }).click()
  await errorPage.getByText('任务状态获取失败').waitFor({ state: 'visible' })
  assert.ok((await errorPage.locator('.generate-page').innerText()).includes('生成中'), 'a status failure should keep the current task readable')
  evidence.interactionChecks.push({ scenario: 'running-status-error', statusFailure: true })
  await assertNoExternalOrUnexpected('status-error-feedback')
  await errorPage.close()

  const resourcePage = await newPage(browser, base, 'completed', baseViewport, { delayResourcesMs: 450, failResources: 1 })
  await resourcePage.locator('.resources-panel > .resource-toolbar .task-actions').getByRole('button', { name: '刷新资源', exact: true }).click()
  assert.ok(await resourcePage.locator('.resource-stage .el-loading-mask').count(), 'resource refresh should expose a loading state')
  await resourcePage.getByText('资源列表加载失败').waitFor({ state: 'visible' })
  evidence.interactionChecks.push({ scenario: 'resource-load-error', loadingAndError: true })
  await assertNoExternalOrUnexpected('resource-error-feedback')
  await resourcePage.close()
}

async function testResourceSwitchAndLearningRoutes(browser, base) {
  const page = await newPage(browser, base, 'long', baseViewport)
  assert.ok(await page.locator('.app-shell').evaluate((node) => node.classList.contains('is-generation')),
    'generation route should provide the shared compact-topbar reference')
  const generationTopbar = await compactTopbarMetrics(page)
  await page.locator('.resource-content h1').waitFor({ state: 'visible' })
  const longResourceType = '多阶段知识迁移与证据核验实操指南资源类型'
  const resourceSelect = page.locator('.resource-select')
  await assertWrappedFieldFocus(page, 'generation-resource-select', resourceSelect.locator('input').first(), resourceSelect.locator('.el-select__wrapper'), 'focus-generation-resource-select')
  await resourceSelect.click()
  const fullLongOption = page.getByRole('option', { name: new RegExp(longResourceType) })
  await fullLongOption.waitFor({ state: 'visible' })
  assert.ok((await fullLongOption.innerText()).includes(longResourceType), 'resource option should retain the full accessible long type')
  await page.keyboard.press('Escape')
  await inspectElementSelect({
    page, suite: 'generation', evidenceDir: reportDir, id: 'generation-resource-long-desktop',
    select: resourceSelect, longText: longResourceType, getWriteCount: () => state.writes.length,
  })
  const longDocumentTitle = page.locator('.resource-content h1')
  assert.ok((await longDocumentTitle.innerText()).includes(longResourceType + ' · 节点A、节点B'), 'resource body title should retain the complete long resource identity')
  await geometry(page, '1393x871-long-kind-tools', true)
  await capture(page, 'desktop-long-kind-tools')
  await page.setViewportSize({ width: 390, height: 844 })
  await waitForLayout(page, false)
  await page.evaluate(() => {
    document.documentElement.scrollTop = 0
    document.querySelector('.content-area')?.scrollTo(0, 0)
    document.querySelector('.generate-page')?.scrollTo(0, 0)
    document.querySelector('.resource-stage')?.scrollTo(0, 0)
  })
  await geometry(page, '390x844-long-kind-tools', false)
  await inspectElementSelect({
    page, suite: 'generation', evidenceDir: reportDir, id: 'generation-resource-long-mobile',
    select: resourceSelect, longText: longResourceType, getWriteCount: () => state.writes.length,
  })
  await capture(page, 'mobile-long-kind-tools')
  const popupPromise = page.waitForEvent('popup')
  await page.locator('.resource-toolbar .download-button').click()
  const downloadPopup = await popupPromise
  await downloadPopup.waitForLoadState('domcontentloaded')
  assert.equal(new URL(downloadPopup.url()).pathname, '/api/resources/file/resource-guide', 'reader download should open only the fixture file route')
  assert.ok((await downloadPopup.locator('body').innerText()).includes('Isolated fixture download for resource-guide'), 'fixture download response should remain readable')
  assert.ok(state.requests.some((item) => item.method === 'GET' && item.path === '/api/resources/file/resource-guide'), 'download action should make a read-only fixture request')
  evidence.interactionChecks.push({ scenario: 'reader-download', url: downloadPopup.url(), method: 'GET' })
  await downloadPopup.close()
  await page.setViewportSize(baseViewport)
  await waitForLayout(page, true)
  await page.locator('.resource-stage').evaluate((node) => { node.scrollTop = Math.min(400, node.scrollHeight) })
  await chooseFilterableOptionWithKeyboard(page, resourceSelect, '复习清单', '复习清单', 'generation-resource-select')
  await page.waitForFunction(() => document.querySelector('.resource-stage')?.scrollTop === 0)
  await page.waitForFunction(() => document.querySelector('.resource-content h1')?.textContent.includes('复习清单'))
  const readerTitle = page.locator('.resource-content h1')
  assert.ok((await readerTitle.innerText()).includes('复习清单'), 'resource selector should switch the visible resource')
  await capture(page, 'desktop-resource-switched')
  const switchedDownloadPopupPromise = page.waitForEvent('popup')
  await page.locator('.resource-toolbar .download-button').click()
  const switchedDownloadPopup = await switchedDownloadPopupPromise
  await switchedDownloadPopup.waitForLoadState('domcontentloaded')
  assert.equal(new URL(switchedDownloadPopup.url()).pathname, '/api/resources/file/resource-checklist', 'download should follow the newly selected resource')
  assert.ok((await switchedDownloadPopup.locator('body').innerText()).includes('Isolated fixture download for resource-checklist'), 'switched resource download should return its matching fixture')
  assert.ok(state.requests.some((item) => item.method === 'GET' && item.path === '/api/resources/file/resource-checklist'), 'switched resource download should use the local fixture endpoint')
  evidence.interactionChecks.push({ scenario: 'reader-download-after-switch', url: switchedDownloadPopup.url(), method: 'GET', resourceId: 'resource-checklist' })
  await switchedDownloadPopup.close()
  await page.getByRole('button', { name: '学习模式', exact: true }).click()
  await assertRouteFixtureReady(page, '/resources')
  assert.equal(new URL(page.url()).searchParams.get('learnerId'), 'learner-1')
  assert.equal(new URL(page.url()).searchParams.get('runId'), 'batch-learner-1')
  evidence.interactionChecks.push({ scenario: 'completed', route: page.url(), action: 'learning-mode' })
  const libraryReader = page.locator('.resources-page .reader-card')
  await libraryReader.locator('.reader-header').waitFor({ state: 'visible' })
  await libraryReader.locator('.resource-content h1').waitFor({ state: 'visible' })
  const initialLibraryTitle = (await libraryReader.locator('.resource-content h1').innerText()).trim()
  const resourcesProfileSelect = page.locator('.resources-page .learning-toolbar .el-select').nth(0)
  const resourcesBatchSelect = page.locator('.resources-page .learning-toolbar .el-select').nth(1)
  await assertWrappedFieldFocus(page, 'resources-toolbar-profile', resourcesProfileSelect.locator('input'), resourcesProfileSelect.locator('.el-select__wrapper'))
  await chooseFilterableOptionWithKeyboard(page, resourcesProfileSelect, 'AI 应用开发', 'AI 应用开发', 'resources-toolbar-profile')
  await assertWrappedFieldFocus(page, 'resources-toolbar-batch', resourcesBatchSelect.locator('input'), resourcesBatchSelect.locator('.el-select__wrapper'))
  await chooseFilterableOptionWithKeyboard(page, resourcesBatchSelect, '资源批次 01', '资源批次 01', 'resources-toolbar-batch')
  await page.waitForFunction((expectedTitle) => document.querySelector('.resources-page .resource-content h1')?.textContent.trim() === expectedTitle, initialLibraryTitle)
  assert.equal((await libraryReader.locator('.resource-content h1').innerText()).trim(), initialLibraryTitle,
    'selecting the existing profile and batch should preserve the currently selected resource')
  await setResourcesSidebar(page, false)
  await assertResourcesGeometry(page, 'resources-1393x871-expanded')
  await assertResourcesCompactTopbar(page, 'resources-1393x871-compact-topbar', generationTopbar)
  assert.equal(await page.locator('.app-shell').evaluate((node) => node.classList.contains('is-sidebar-collapsed')), false,
    'Resources view desktop baseline should have the sidebar expanded')
  await assertResourcesControls(page, 'resources-1393x871-expanded', [
    '.resources-page .learning-toolbar .courseware-button',
    '.resources-page .learning-toolbar .refresh-button',
    '.resources-page .learning-toolbar .focus-button',
    '.resources-page .resource-feedback-button',
    '.resources-page .tutor-trigger',
  ])
  assert.equal(await libraryReader.locator('.reader-header .resource-kicker').count(), 1, 'default learning route should retain the reader header fallback')
  assert.equal(await libraryReader.locator('.reader-header .reader-actions .el-tag').count(), 1, 'default learning route should retain the difficulty label')
  assert.ok(await libraryReader.locator('.reader-header .download-button').isVisible(), 'default learning route should retain reader download')
  const defaultDocumentTitle = libraryReader.locator('.resource-content h1')
  await defaultDocumentTitle.waitFor({ state: 'visible' })
  assert.ok((await defaultDocumentTitle.innerText()).includes('讲义'), 'default learning route should load its selected reader resource')
  await capture(page, 'desktop-default-learning-reader')
  await assertContrast(page, 'resources-ordinary-reader')
  const defaultDownloadPopupPromise = page.waitForEvent('popup')
  await libraryReader.locator('.reader-header .download-button').click()
  const defaultDownloadPopup = await defaultDownloadPopupPromise
  await defaultDownloadPopup.waitForLoadState('domcontentloaded')
  assert.equal(new URL(defaultDownloadPopup.url()).pathname, '/api/resources/file/resource-lecture', 'default reader should keep the original download callback and selected resource')
  assert.ok((await defaultDownloadPopup.locator('body').innerText()).includes('Isolated fixture download for resource-lecture'), 'default reader download should return its local fixture response')
  assert.ok(state.requests.some((item) => item.method === 'GET' && item.path === '/api/resources/file/resource-lecture'), 'default reader download should use the local fixture endpoint')
  await defaultDownloadPopup.close()
  assert.ok(await libraryReader.locator('.reader-header .tutor-trigger').isVisible(), 'default ResourceViewer header-end-actions slot should still render its caller button')
  await libraryReader.locator('.reader-header .tutor-trigger').click()
  await page.locator('.tutor-panel').waitFor({ state: 'visible' })
  await page.getByText('从卡住的地方开始', { exact: true }).waitFor({ state: 'visible' })
  const tutorCreate = state.writes.filter((item) => item.method === 'POST' && item.path === '/api/tutor/sessions')
  assert.equal(tutorCreate.length, 1, 'default header Tutor action should create one isolated fixture session')
  assert.equal(tutorCreate[0].body.context_type, 'resource_help')
  assert.equal(tutorCreate[0].body.resource_id, 'resource-lecture')
  assert.equal(tutorCreate[0].body.learner_id, 'learner-1')
  evidence.interactionChecks.push({ scenario: 'default-reader-header-slots', tutorSession: tutorCreate[0], download: '/api/resources/file/resource-lecture' })
  await page.locator('.tutor-panel .tutor-close').click()
  await page.locator('.tutor-panel').waitFor({ state: 'hidden' })

  const selectedShelfItem = page.locator('.resources-page .resource-item').filter({ hasText: '复习清单' })
  await selectedShelfItem.click()
  await page.waitForFunction(() => new URL(location.href).searchParams.get('resourceId') === 'resource-checklist')
  await page.waitForFunction(() => document.querySelector('.resources-page .resource-content h1')?.textContent.includes('复习清单'))
  assert.ok(await selectedShelfItem.evaluate((node) => node.classList.contains('is-active')),
    'selected resource shelf item should receive its active state')
  await assertSelectedResourceVisualState(page, 'resources-selected-shelf-card-state',
    '.resources-page .resource-item.is-active', '.resources-page .resource-item:not(.is-active)')
  assert.ok((await libraryReader.locator('.resource-content h1').innerText()).includes('复习清单'),
    'resource shelf selection should update the visible reader body')
  await assertResourcesCardContrast(page, 'resources-selected-shelf-card-click')
  await page.mouse.move(12, 12)
  await assertResourcesCardContrast(page, 'resources-selected-shelf-card-rest')
  await selectedShelfItem.hover()
  await assertResourcesCardContrast(page, 'resources-selected-shelf-card-hover')
  await capture(page, 'desktop-resources-selected-checklist')
  const shelfDownloadPromise = page.waitForEvent('popup')
  await libraryReader.locator('.reader-header .download-button').click()
  const shelfDownload = await shelfDownloadPromise
  await shelfDownload.waitForLoadState('domcontentloaded')
  assert.equal(new URL(shelfDownload.url()).pathname, '/api/resources/file/resource-checklist',
    'resource shelf selection should bind the reader download to the selected resource')
  assert.ok((await shelfDownload.locator('body').innerText()).includes('Isolated fixture download for resource-checklist'),
    'selected resource download should resolve through its matching local fixture')
  evidence.interactionChecks.push({ scenario: 'resources-shelf-selection-download', resourceId: 'resource-checklist', url: shelfDownload.url(), method: 'GET' })
  await shelfDownload.close()

  const resourceListRequestsBeforeRefresh = state.requests.filter((item) => item.path === '/api/resource-library/learner-1' && item.method === 'GET').length
  await page.locator('.resources-page .refresh-button').click()
  await waitForFixture(
    () => state.requests.filter((item) => item.path === '/api/resource-library/learner-1' && item.method === 'GET').length === resourceListRequestsBeforeRefresh + 1,
    'Resources view refresh GET',
  )
  await page.waitForFunction(() => document.querySelector('.resources-page .resource-content h1')?.textContent.includes('复习清单'))
  assert.equal(new URL(page.url()).searchParams.get('resourceId'), 'resource-checklist',
    'resource refresh should retain the selected resource route')
  assert.equal(state.requests.filter((item) => item.path === '/api/resource-library/learner-1' && item.method !== 'GET').length, 0,
    'resource refresh should remain read-only')
  evidence.interactionChecks.push({ scenario: 'resources-refresh', endpoint: '/api/resource-library/learner-1', method: 'GET' })

  const firstShelfItem = page.locator('.resources-page .resource-item').first()
  const firstShelfStyleBefore = await firstShelfItem.evaluate((node) => {
    const style = getComputedStyle(node)
    return { outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth, boxShadow: style.boxShadow, borderColor: style.borderTopColor }
  })
  await page.locator('.resources-page .focus-button').focus()
  await page.keyboard.press('Tab')
  const keyboardFocus = await page.evaluate(() => {
    const node = document.activeElement
    if (!node) return null
    const style = getComputedStyle(node)
    return {
      selector: node.className,
      resourceButton: node.matches('.resources-page .resource-item'),
      focusVisible: node.matches(':focus-visible'),
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      boxShadow: style.boxShadow,
      borderColor: style.borderTopColor,
    }
  })
  assert.equal(keyboardFocus?.resourceButton, true, 'Tab from the toolbar should reach the resource shelf button')
  assert.equal(keyboardFocus.focusVisible, true, 'resource shelf button should expose keyboard focus-visible state')
  assert.ok((keyboardFocus.outlineStyle !== 'none' && keyboardFocus.outlineWidth !== '0px')
    || keyboardFocus.boxShadow !== firstShelfStyleBefore.boxShadow
    || keyboardFocus.borderColor !== firstShelfStyleBefore.borderColor,
  'keyboard focus should have a visible indicator on the resource shelf button')
  evidence.interactionChecks.push({ scenario: 'resources-keyboard-focus', ...keyboardFocus, before: firstShelfStyleBefore })

  const longShelfItem = page.locator('.resources-page .resource-item').filter({ hasText: '多阶段知识迁移与证据核验实操指南资源类型' })
  await longShelfItem.click()
  await page.waitForFunction(() => new URL(location.href).searchParams.get('resourceId') === 'resource-guide')
  await page.waitForFunction((expectedTitle) => document.querySelector('.resources-page .resource-content h1')?.textContent.includes(expectedTitle), longResourceType)
  assert.ok(await longShelfItem.evaluate((node) => node.classList.contains('is-active')),
    'long document selection should remain visible in the resource shelf')

  await page.setViewportSize({ width: 1331, height: 871 })
  await setResourcesSidebar(page, true)
  await page.waitForTimeout(100)
  await assertResourcesGeometry(page, 'resources-1331x871-collapsed')
  assert.equal(await page.locator('.app-shell').evaluate((node) => node.classList.contains('is-sidebar-collapsed')), true,
    'Resources view should preserve its layout with the sidebar collapsed')
  await assertResourcesControls(page, 'resources-1331x871-collapsed', [
    '.resources-page .learning-toolbar .courseware-button',
    '.resources-page .learning-toolbar .refresh-button',
    '.resources-page .learning-toolbar .focus-button',
    '.resources-page .resource-feedback-button',
    '.resources-page .tutor-trigger',
  ])
  await capture(page, 'desktop-resources-sidebar-collapsed')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => {
    document.querySelector('.content-area')?.scrollTo(0, 0)
    document.querySelector('.resources-page')?.scrollTo(0, 0)
  })
  await page.waitForTimeout(100)
  const resourcesMobile = await assertResourcesGeometry(page, 'resources-390x844')
  for (const viewport of [{ width: 390, height: 844 }, { width: 375, height: 667 }]) {
    await page.setViewportSize(viewport)
    for (const collapsed of [false, true]) {
      await page.evaluate(() => {
        document.querySelector('.content-area')?.scrollTo(0, 0)
        document.querySelector('.resources-page')?.scrollTo(0, 0)
      })
      await setResourcesSidebar(page, collapsed)
      const label = `resources-mobile-nav-${viewport.width}x${viewport.height}-${collapsed ? 'collapsed' : 'expanded'}`
      await assertResourcesMobileSidebarGeometry(page, label, collapsed)
      await capture(page, label)
    }
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await setResourcesSidebar(page, true)
  await page.evaluate(() => {
    document.querySelector('.content-area')?.scrollTo(0, 0)
    document.querySelector('.resources-page')?.scrollTo(0, 0)
  })
  await page.waitForTimeout(50)
  await assertResourcesControls(page, 'resources-390x844-toolbar', [
    '.resources-page .learning-toolbar .courseware-button',
    '.resources-page .learning-toolbar .refresh-button',
    '.resources-page .learning-toolbar .focus-button',
  ])
  const shelfScroll = await page.locator('.resources-page .resource-shelf').evaluate((node) => {
    const before = node.scrollLeft
    const maxScroll = node.scrollWidth - node.clientWidth
    const overflowX = getComputedStyle(node).overflowX
    node.scrollTo({ left: maxScroll, behavior: 'instant' })
    const lastResource = [...node.querySelectorAll('.resource-item')].at(-1)
    const shelfRect = node.getBoundingClientRect()
    const lastRect = lastResource?.getBoundingClientRect()
    return {
      before,
      after: node.scrollLeft,
      maxScroll,
      overflowX,
      lastResourceVisible: Boolean(lastRect && lastRect.right <= shelfRect.right + 1 && lastRect.left >= shelfRect.left - 1),
    }
  })
  assert.ok(['auto', 'scroll'].includes(shelfScroll.overflowX) && shelfScroll.maxScroll > 0 && shelfScroll.after > shelfScroll.before,
    'mobile resource shelf should remain horizontally scrollable: ' + JSON.stringify(shelfScroll))
  assert.equal(shelfScroll.lastResourceVisible, true, 'horizontal shelf scrolling should expose the final resource card')
  evidence.scrollChecks.push({ label: 'resources-mobile-horizontal-shelf', ...shelfScroll })
  await page.locator('.resources-page .reading-stage .resource-content h1').scrollIntoViewIfNeeded()
  await page.locator('.resources-page .reading-stage .resource-content h1').waitFor({ state: 'visible' })
  await assertContrast(page, 'resources-mobile-reader')
  await capture(page, 'mobile-resources-reader')
  evidence.layoutChecks.push({ label: 'resources-mobile-reader-visible', viewport: resourcesMobile.viewport, title: await page.locator('.resources-page .reading-stage .resource-content h1').innerText() })

  await page.setViewportSize(baseViewport)
  await page.evaluate(() => {
    document.querySelector('.content-area')?.scrollTo(0, 0)
    document.querySelector('.resources-page')?.scrollTo(0, 0)
  })
  await setResourcesSidebar(page, false)
  await page.waitForTimeout(100)
  await page.locator('.resources-page .focus-button').click()
  await page.waitForFunction(() => new URL(location.href).searchParams.get('focus') === '1')
  await page.locator('.resources-layout.is-focus-mode .focus-resource-switcher').waitFor({ state: 'visible' })
  await assertResourcesGeometry(page, 'resources-focus-1393x871')
  await assertResourcesControls(page, 'resources-focus-exit', ['.resources-page .focus-exit'])
  await assertContrast(page, 'resources-focus-mode')
  await page.evaluate(() => {
    document.querySelector('.content-area')?.scrollTo(0, 0)
    document.querySelector('.resources-page')?.scrollTo(0, 0)
    document.querySelector('.resources-page .resource-content')?.scrollTo(0, 0)
  })
  await capture(page, 'desktop-resources-focus')

  const focusSwitcher = page.locator('.resources-page .focus-resource-switcher')
  const lectureSwitch = focusSwitcher.getByRole('button', { name: /讲义/ })
  assert.equal(await lectureSwitch.getAttribute('aria-pressed'), 'false', 'focus switcher should identify the currently unselected document')
  await lectureSwitch.click()
  await page.waitForFunction(() => new URL(location.href).searchParams.get('resourceId') === 'resource-lecture')
  await page.waitForFunction(() => document.querySelector('.resources-page .resource-content h1')?.textContent.includes('讲义'))
  assert.equal(await lectureSwitch.getAttribute('aria-pressed'), 'true', 'focus switcher should mark the selected document')
  await assertSelectedResourceVisualState(page, 'resources-focus-switcher-state',
    '.resources-page .focus-resource-switcher button.is-active', '.resources-page .focus-resource-switcher button:not(.is-active)')
  evidence.interactionChecks.push({ scenario: 'resources-focus-switcher', resourceId: 'resource-lecture' })
  await capture(page, 'desktop-resources-focus-switched')
  await page.locator('.resources-page .focus-exit').click()
  await page.waitForFunction(() => new URL(location.href).searchParams.get('focus') !== '1')
  assert.equal(new URL(page.url()).searchParams.get('resourceId'), 'resource-lecture', 'leaving focus mode should preserve the selected resource')
  // The existing App branch remount reloads the library asynchronously.
  await page.waitForFunction(() => document.querySelector('.app-shell .learning-workspace .resource-content h1')?.textContent.includes('讲义'))
  await assertResourcesGeometry(page, 'resources-focus-exited')
  evidence.interactionChecks.push({ scenario: 'resources-focus-enter-exit', selectedResourceId: 'resource-lecture' })
  await assertNoExternalOrUnexpected('learning-mode-route')
  assert.deepEqual(state.writes.map((item) => ({ method: item.method, path: item.path })), [
    { method: 'POST', path: '/api/tutor/sessions' },
  ], 'Resources view UI checks should not produce business writes beyond the isolated Tutor session')
  await page.close()

  const historyPage = await newPage(browser, base, 'completed')
  await assertNoLocalHistoryAction(historyPage, 'learning-history-route')
  await historyPage.locator('.topbar .topbar-action').filter({ hasText: '学习历史' }).click()
  await assertRouteFixtureReady(historyPage, '/learning/history')
  evidence.interactionChecks.push({ scenario: 'completed', route: historyPage.url(), action: 'learning-history' })
  await assertNoExternalOrUnexpected('learning-history-route')
  await historyPage.close()
}

async function testClaimAndAppend(browser, base) {
  const claimPage = await newPage(browser, base, 'claim-pending')
  await assertResourcePhases(claimPage, 'claim-pending-resource-delivery', {
    captureName: 'desktop-resource-delivery-claim-pending',
  })
  await openResourceDelivery(claimPage)
  const assertPendingReviewActions = async (resource, label) => {
    const metrics = await resource.locator('.execution-actions').evaluate((actions) => {
      const buttons = [...actions.querySelectorAll('button')]
      return {
        actionsWidth: actions.getBoundingClientRect().width,
        buttons: buttons.map((button) => {
          const rect = button.getBoundingClientRect()
          return {
            label: button.innerText.trim(),
            ariaLabel: button.getAttribute('aria-label') || '',
            className: button.className,
            x: rect.x,
            width: rect.width,
            height: rect.height,
            scrollWidth: button.scrollWidth,
          }
        }),
      }
    })
    const reports = metrics.buttons.filter((button) => button.ariaLabel === '查看审核报告')
    assert.equal(reports.length, 1, label + ': pending publication should expose exactly one review-report action')
    assert.equal(reports[0].label, '审核报告', label + ': review report should use the compact visible label')
    assert.ok(reports[0].className.includes('execution-primary'), label + ': the review report should be the primary action')
    assert.deepEqual(metrics.buttons.filter((button) => button.className.includes('execution-primary')).map((button) => button.ariaLabel),
      ['查看审核报告'], label + ': the pending report should be the sole primary action')

    const retry = metrics.buttons.find((button) => button.ariaLabel === '重新生成此资源')
    assert.ok(retry, label + ': the existing resource retry action should remain available')
    assert.equal(retry.label, '重新生成', label + ': retry should use the compact visible label')
    assert.ok(retry.className.includes('execution-secondary'), label + ': pending retry should be a secondary action')
    const secondary = metrics.buttons.filter((button) => button.className.includes('execution-secondary'))
    assert.deepEqual(secondary.map((button) => button.ariaLabel), ['重新生成此资源', '查看过程详情'],
      label + ': retry and process details should share the secondary action row')
    assert.deepEqual(secondary.map((button) => button.label), ['重新生成', '过程详情'],
      label + ': pending secondary actions should use compact visible labels')
    const touchTargets = await resource.evaluate(() => matchMedia('(pointer: coarse), (max-width: 720px)').matches)
    assert.ok(metrics.buttons.every((button) => touchTargets
      ? button.height >= 44
      : button.height >= 32 && button.height <= 36),
    label + ': pending actions should use the responsive 34px desktop / 44px touch target')
    assert.ok(metrics.buttons.every((button) => button.width < metrics.actionsWidth * 0.75),
      label + ': pending actions should keep compact fit-content widths')
    assert.ok(metrics.buttons.every((button) => button.scrollWidth <= button.width + 1),
      label + ': pending action labels should remain visible without clipping')
  }
  await assertContrast(claimPage, 'desktop-resource-delivery-claim-pending')
  assert.match(await claimPage.locator('.resource-progress-tree .delivery-count').innerText(), /2\s*\/\s*3/,
    'a pending publication decision should retain the true two-of-three published summary')
  const publicationStates = await claimPage.locator('.resource-progress-tree .execution-card').evaluateAll((cards) => cards.map((card) => ({
    resource: card.querySelector('.execution-title strong')?.textContent.trim(),
    status: [...card.querySelectorAll('.execution-status-field')].find((field) => field.querySelector('small')?.textContent.trim() === '发布状态')
      ?.querySelector('strong')?.textContent.trim(),
  })))
  assert.deepEqual(publicationStates, [
    { resource: '实操指南', status: '尚未发布' },
    { resource: '复习清单', status: '已发布' },
    { resource: '讲义', status: '已发布' },
  ], 'one pending review should remain unpublished while the other two resources stay published')
  const pendingResource = claimPage.locator('.resource-progress-tree .execution-card').filter({ hasText: '实操指南' }).first()
  assert.ok((await pendingResource.locator('.execution-notice.claim-pending').innerText()).includes('待你决定发布'),
    'a pending publication decision should remain explicit on its resource delivery item')
  await assertPendingReviewActions(pendingResource, 'desktop pending publication')
  await captureResourceDeliveryOverview(claimPage, 'desktop-resource-delivery-overview')
  await claimPage.setViewportSize({ width: 390, height: 844 })
  await waitForLayout(claimPage, false)
  assert.ok((await pendingResource.locator('.execution-notice.claim-pending').innerText()).includes('待你决定发布'),
    'mobile delivery should also expose the pending publication decision')
  await assertPendingReviewActions(pendingResource, 'mobile pending publication')
  await assertContrast(claimPage, 'mobile-resource-delivery-claim-pending')
  await captureResourceDeliveryOverview(claimPage, 'mobile-resource-delivery-overview')
  await captureResourceDelivery(claimPage, pendingResource, 'mobile-resource-delivery-claim-pending')
  await claimPage.setViewportSize(baseViewport)
  await waitForLayout(claimPage, true)
  await claimPage.getByRole('button', { name: '查看审核报告' }).first().click()
  await claimPage.getByRole('heading', { name: '资源 Claim 审核报告' }).waitFor()
  assert.ok((await claimPage.locator('.claim-report-dialog').innerText()).includes('验收事实陈述'), 'claim dialog should retain its report content')
  const publicationClaims = claimPage.locator('.claim-report-dialog .claim-detail')
  assert.ok(await publicationClaims.count() > 0, 'the publication report fixture must contain Claims')
  assert.ok(await publicationClaims.evaluateAll((nodes) => nodes.every((node) => !node.open)), 'the original publication report must keep all Claim details folded by default')
  await capture(claimPage, 'desktop-claim-report')
  await claimPage.getByRole('button', { name: '确认发布' }).click()
  await waitForFixture(() => state.writes.some((item) => item.path.includes('claim-publication-decision')), 'claim decision')
  assert.equal(state.writes.filter((item) => item.path.includes('claim-publication-decision')).length, 1, 'claim decision should submit once')
  assert.deepEqual(state.lastClaimDecision, { resource_id: 'resource-guide', body: { publish: true } })
  await claimPage.locator('.claim-report-dialog').waitFor({ state: 'hidden' })
  await claimPage.waitForFunction(() => {
    const card = [...document.querySelectorAll('.resource-progress-tree .execution-card')]
      .find(item => item.querySelector('.execution-title strong')?.textContent.trim() === '实操指南')
    const publication = [...(card?.querySelectorAll('.execution-status-field') || [])]
      .find(field => field.querySelector('small')?.textContent.trim() === '发布状态')
    return card?.querySelector('.execution-phase')?.textContent.includes('已发布')
      && publication?.querySelector('strong')?.textContent.trim() === '已发布'
      && !card.querySelector('.execution-notice.claim-pending')
  }, null, { timeout: 9000 })
  assert.match(await claimPage.locator('.resource-progress-tree .delivery-count').innerText(), /3\s*\/\s*3/,
    'publishing the pending Claim resource should update the visible published count')
  assert.ok(await pendingResource.getByRole('button', { name: '查看已发布资源', exact: true }).isEnabled(),
    'the confirmed resource should expose the normal published-resource action')
  assert.equal(await pendingResource.getByRole('button', { name: '重新生成此资源', exact: true }).count(), 0,
    'a stale human_review execution must not expose retry after the exact resource was published')
  assert.equal(await pendingResource.locator('.execution-notice.claim-pending').count(), 0,
    'the explicitly published resource must clear its stale Claim decision notice')
  await pendingResource.getByRole('button', { name: '查看审核报告', exact: true }).click()
  await claimPage.getByRole('heading', { name: '资源 Claim 审核报告' }).waitFor()
  assert.equal(await claimPage.locator('.claim-report-actions').count(), 0,
    'reopening the report after a user decision must not offer publication decisions again')
  assert.equal(await claimPage.getByRole('button', { name: '确认发布', exact: true }).count(), 0)
  assert.equal(await claimPage.getByRole('button', { name: '暂不发布', exact: true }).count(), 0)
  await claimPage.keyboard.press('Escape')
  await claimPage.locator('.claim-report-dialog').waitFor({ state: 'hidden' })
  evidence.interactionChecks.push({ scenario: 'claim-report', decision: state.lastClaimDecision })
  await assertNoExternalOrUnexpected('claim-report')
  await claimPage.close()

  const retainPage = await newPage(browser, base, 'claim-pending')
  await openResourceDelivery(retainPage)
  await retainPage.getByRole('button', { name: '查看审核报告' }).first().click()
  await retainPage.getByRole('heading', { name: '资源 Claim 审核报告' }).waitFor()
  await retainPage.getByRole('button', { name: '暂不发布' }).click()
  await waitForFixture(() => state.writes.some((item) => item.path.includes('claim-publication-decision')), 'claim retain decision')
  assert.deepEqual(state.lastClaimDecision, { resource_id: 'resource-guide', body: { publish: false } })
  evidence.interactionChecks.push({ scenario: 'claim-report-retain', decision: state.lastClaimDecision })
  await assertNoExternalOrUnexpected('claim-report-retain')
  await retainPage.close()

  const splitPage = await newPage(browser, base, 'completed')
  await inspectDropdownMenu({
    page: splitPage, suite: 'generation', evidenceDir: reportDir, id: 'generation-append-dropdown',
    trigger: splitPage.locator('.status-action-append').first(), getWriteCount: () => state.writes.length,
  })
  await appendTextTypes(splitPage, true, ['复习清单', '案例分析'], 'desktop-append-dialog')
  await waitForFixture(() => state.writes.filter((item) => item.path.endsWith('/continuations')).length === 2, 'Claim-enabled append split')
  const splitWrites = state.writes.filter((item) => item.path.endsWith('/continuations'))
  assert.equal(splitWrites.length, 2, 'Claim-enabled append should split each resource type into its own request')
  assert.ok(splitWrites.every((item) => item.body.resource_types.length === 1), 'Claim-enabled append should submit one resource type per request')
  assert.deepEqual(new Set(splitWrites.map((item) => item.body.resource_types[0])), new Set(['复习清单', '案例分析']),
    'Claim-enabled append should preserve both selected resource types; independent parallel request arrival order is not significant')
  assert.ok(splitWrites.every((item) => item.body.include_claim_check === true && item.body.source_run_id === 'run-main'))
  evidence.interactionChecks.push({ scenario: 'append-claim-enabled', writes: splitWrites })
  await assertNoExternalOrUnexpected('append-claim-enabled')
  await splitPage.close()

  const mergedPage = await newPage(browser, base, 'completed')
  await appendTextTypes(mergedPage, false, ['复习清单', '案例分析'])
  await waitForFixture(() => state.writes.filter((item) => item.path.endsWith('/continuations')).length === 1, 'Claim-disabled append merge')
  const mergedWrites = state.writes.filter((item) => item.path.endsWith('/continuations'))
  assert.equal(mergedWrites.length, 1, 'Claim-disabled append should submit one combined continuation')
  assert.deepEqual(mergedWrites[0].body.resource_types, ['复习清单', '案例分析'])
  assert.equal(mergedWrites[0].body.include_claim_check, false)
  evidence.interactionChecks.push({ scenario: 'append-claim-disabled', writes: mergedWrites })
  await assertNoExternalOrUnexpected('append-claim-disabled')
  await mergedPage.close()
}

async function testFollowupRunNavigation(browser, base) {
  const page = await newPage(browser, base, 'followup-navigation')
  assert.deepEqual(state.jobsByLearner['learner-1'].map((job) => job.run_id), ['run-main', 'followup-run'],
    'follow-up navigation fixture should expose the child through the learner task list')
  await waitForFixture(() => state.requests.some((item) => item.path === '/api/runs/run-main/timeline'), 'parent Run lifecycle event')
  assert.equal((await page.locator('.summary-code').innerText()).trim(), 'RUN-MAIN', 'follow-up navigation should begin on its parent Run')
  assert.equal(await page.locator('.workflow-activity').count(), 0, 'the removed Run activity log should not render')
  assert.equal(await page.getByText('运行记录', { exact: true }).count(), 0, 'the removed Run activity label should not remain visible')
  const followups = page.locator('.workflow-followups')
  await followups.waitFor({ state: 'visible' })
  assert.equal(await followups.getByRole('button', { name: /^查看后续生成/ }).count(), 1,
    'the separate follow-up area should retain its child Run action')
  await followups.getByRole('button', { name: /^查看后续生成/ }).click()
  await waitForFixture(() => state.requests.some((item) => item.path === '/api/runs/followup-run/timeline'), 'child Run timeline after follow-up navigation')
  await page.waitForFunction(() => document.querySelector('.summary-code')?.textContent.trim() === 'FOLLOWUP')
  await page.locator('.execution-graph-node[data-step-id="step-1"]').waitFor({ state: 'visible' })
  assert.equal(await page.locator('.execution-graph-node[data-step-id^="step-"]').count(), 2,
    'following the child should show its own two-step timeline')
  assert.equal(await page.locator('.workflow-followups').count(), 0, 'the child should not inherit its parent follow-up links')
  assert.ok(state.requests.some((item) => item.method === 'GET' && item.path === '/api/generate/jobs'),
    'follow-up selection should resolve the child from the task list')
  assert.deepEqual(state.writes, [], 'opening a child Run should remain read only')
  evidence.interactionChecks.push({
    scenario: 'followup-run-navigation', parentRun: 'run-main', childRun: 'followup-run',
    childTimelineLoaded: true, writes: state.writes.length,
  })
  await assertNoExternalOrUnexpected('followup-run-navigation')
  await page.close()
}

async function testWorkflowAuditVisualization(browser, base) {
  const page = await newPage(browser, base, 'audit-visualization')
  await waitForFixture(() => state.requests.some((item) => item.path === '/api/runs/run-main/timeline'), 'audit visualization timeline')
  const dialog = page.locator('.workflow-detail-dialog')
  const graph = page.locator('.execution-graph')
  await assertResourcePhases(page, 'audit-visualization-desktop', {
    captureName: 'desktop-resource-delivery-expanded',
    expectedPhase: '已发布', expectAllPublished: true,
  })
  assert.equal(await graph.count(), 1, 'the compact workflow view should render one execution graph')
  assert.equal(await graph.locator('.execution-graph-header, .execution-graph-modes, .execution-graph-count').count(), 0, 'redundant title, counter and view modes should be removed')
  assert.equal(await graph.locator('.execution-graph-node').count(), 6, 'the chain should show every actual call, including both reviews')
  assert.deepEqual(await graph.locator('.execution-graph-node').evaluateAll((nodes) => nodes.map((node) => node.dataset.stepId)), [
    'audit-unknown-node', 'audit-review-v2', 'audit-generate-v2', 'audit-revision', 'audit-review-v1', 'audit-diagnose-unbound',
  ], 'the complete chain should show the newest recorded execution first')
  assert.equal(await page.locator('.resource-progress-tree').count(), 1, 'the workflow should have a single resource delivery section')
  assert.equal(await page.locator('.workflow-activity').count(), 0, 'the separate lifecycle log should be removed')
  assert.equal(await page.getByText('运行记录', { exact: true }).count(), 0, 'the removed lifecycle log label should not remain')
  const compactText = await graph.innerText()
  assert.ok(!compactText.includes('检查资源 resource-guide-v1 的事实陈述与证据引用。'), 'compact overview should not duplicate long execution summaries')
  assert.ok(!compactText.includes('保留期限与冻结来源不符'), 'compact overview should keep decision reasons inside on-demand details')
  await graph.scrollIntoViewIfNeeded()
  await capture(page, 'desktop-workflow-redesign')

  const waitForAuditReads = async (targetDialog, before, label) => {
    await waitForFixture(() => (
      state.requests.filter((item) => item.method === 'GET' && item.path === '/api/runs/run-main/timeline').length > before.timeline
      && state.requests.filter((item) => item.method === 'GET' && item.path === '/api/runs/run-main/claims').length > before.claims
    ), label)
    await targetDialog.getByText('正在加载执行详情…', { exact: true }).waitFor({ state: 'hidden' })
  }
  const auditReadCounts = () => ({
    timeline: state.requests.filter((item) => item.method === 'GET' && item.path === '/api/runs/run-main/timeline').length,
    claims: state.requests.filter((item) => item.method === 'GET' && item.path === '/api/runs/run-main/claims').length,
  })
  const openStepDetails = async (node, label) => {
    const before = auditReadCounts()
    await node.click()
    await dialog.locator('.audit-dialog-heading h2').waitFor()
    await waitForAuditReads(dialog, before, label)
  }

  const beforeUninspectableClicks = auditReadCounts()
  const uninspectableNodes = graph.locator('.execution-graph-node[data-inspectable="false"]')
  for (const nodeKey of ['prepare_revision', 'unknown_future_node']) {
    const node = graph.locator(`.execution-graph-node[data-node-key="${nodeKey}"]`)
    assert.equal(await node.count(), 1, `${nodeKey} should remain visible as a recorded workflow stage`)
    assert.equal(await node.evaluate((element) => element.tagName), 'DIV', `${nodeKey} must not be rendered as an interactive button`)
    assert.equal(await node.getAttribute('tabindex'), null, `${nodeKey} must not enter the keyboard tab order`)
    assert.equal(await node.getAttribute('role'), null, `${nodeKey} must not expose button semantics`)
    await node.click()
  }
  assert.equal(await uninspectableNodes.count(), 2, 'the helper and explicit unknown node should both be non-interactive')
  assert.deepEqual(auditReadCounts(), beforeUninspectableClicks, 'clicking helper and unknown nodes must not request audit details')
  assert.equal(await dialog.isVisible(), false, 'clicking helper and unknown nodes must not open the audit dialog')

  const diagnose = graph.locator('.execution-graph-node[data-node-key="diagnose"]')
  await openStepDetails(diagnose, 'unbound diagnosis details')
  assert.equal(await dialog.locator('.unlinked-note').count(), 0, 'normal unbound diagnosis must not be displayed as a warning')
  assert.equal(await dialog.locator('.resource-picker').count(), 0, 'unbound diagnosis must not offer a picker for unrelated resources')
  assert.equal(await dialog.locator('.audit-signal-row').count(), 0, 'unbound diagnosis must not show a resource review summary')
  assert.equal(await dialog.getByRole('tab').count(), 0, 'a single diagnosis result must not render unrelated or disabled audit navigation')
  assert.ok(!(await dialog.innerText()).includes('审核通过'), 'unbound diagnosis must not inherit another resource approval')
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'hidden' })

  const firstReview = graph.locator('.execution-graph-node[data-step-id="audit-review-v1"]')
  await firstReview.waitFor({ state: 'visible' })
  assert.equal(await firstReview.count(), 1, 'execution graph should show the failed first-version review as a real recorded step')
  await openStepDetails(firstReview, 'v1 workflow audit details')
  assert.equal(await dialog.locator('[role="tablist"], [role="tab"], [role="tabpanel"]').count(), 0, 'review details should remain one page without module navigation')
  assert.equal(await dialog.locator('.review-card').count(), 1, 'the selected v1 review should be the primary content')
  const v1ResourcePicker = dialog.locator('select[aria-label="审核资源"]')
  assert.equal(await v1ResourcePicker.isVisible(), false, 'a single linked resource should stay inside folded context')
  const v1ReviewText = await dialog.locator('.audit-main').innerText()
  assert.ok(v1ReviewText.includes('保存期限陈述与冻结来源冲突'), 'selected v1 review should show its persisted issue')
  assert.ok(v1ReviewText.includes('按冻结来源修订期限，并补充记录字段'), 'selected v1 review should show its revision instruction')
  const executionSummary = dialog.locator('.audit-execution-summary')
  const identifiers = dialog.locator('.audit-context .audit-identifiers')
  assert.equal(await executionSummary.evaluate((node) => node.open), false, 'complete execution input/output/reason should start folded')
  assert.equal(await identifiers.evaluate((node) => node.open), false, 'technical IDs should start folded')
  await capture(page, 'desktop-audit-overview')
  await dialog.locator('.audit-context > summary').click()
  assert.equal(await v1ResourcePicker.inputValue(), 'resource-guide-v1', 'a v1 review step should remain attached to its explicitly linked v1 resource')
  assert.equal(await executionSummary.locator('dd').first().isVisible(), false, 'technical execution summaries should remain folded inside expanded context')
  const v1Options = await v1ResourcePicker.locator('option').evaluateAll((options) => options.map((item) => ({ value: item.value, label: item.innerText.trim() })))
  assert.deepEqual(v1Options.map((item) => item.value), ['resource-guide-v1'], 'a v1 review step must not switch to the latest v2 resource')
  assert.ok(v1Options.every((item) => !item.label.includes(item.value)), 'resource picker labels should use human-readable type and version instead of UUIDs')
  await executionSummary.locator(':scope > summary').click()
  const expandedSummary = await executionSummary.innerText()
  assert.ok(expandedSummary.includes('检查资源 resource-guide-v1 的事实陈述与证据引用。'), 'expanded execution details should retain the full persisted input')
  assert.ok(expandedSummary.includes('审核发现来源范围不一致，要求定向返工。'), 'expanded execution details should retain the full persisted output')
  assert.ok(expandedSummary.includes('保留期限与冻结来源不符，且未说明记录字段。'), 'expanded execution details should retain the persisted decision reason')
  await executionSummary.locator(':scope > summary').click()
  await identifiers.locator(':scope > summary').click()
  const identifierText = await identifiers.innerText()
  assert.ok(identifierText.includes('Step ID：audit-review-v1'), 'expanded technical identifiers should expose the exact step ID on demand')
  assert.ok(identifierText.includes('Resource ID：resource-guide-v1'), 'expanded technical identifiers should expose the linked resource ID on demand')
  assert.ok(identifierText.includes('Review ID：review-guide-v1'), 'expanded technical identifiers should expose the linked review ID on demand')
  assert.ok(identifierText.includes('来源引用：evidence-frozen-contradiction'), 'expanded technical identifiers should expose the exact evidence reference on demand')
  await identifiers.locator(':scope > summary').click()
  await dialog.locator('.audit-context > summary').click()
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'hidden' })

  const secondReview = graph.locator('.execution-graph-node[data-step-id="audit-review-v2"]')
  await secondReview.waitFor({ state: 'visible' })
  assert.equal(await secondReview.count(), 1, 'execution graph should show the successful rework review as a separate recorded step')
  await openStepDetails(secondReview, 'v2 workflow audit details')
  assert.equal(await dialog.locator('[role="tablist"], [role="tab"], [role="tabpanel"]').count(), 0, 'the v2 review must use the same single-page interaction')
  assert.equal(await dialog.locator('.review-card').count(), 1, 'the v2 review should stay distinct from the v1 review')
  const v2ReviewText = await dialog.locator('.audit-main').innerText()
  assert.equal(await dialog.locator('.detail-execution-status strong').innerText(), '执行成功', 'the workflow node can succeed independently of the reviewer verdict')
  assert.ok(v2ReviewText.includes('审核通过'), 'selected v2 review should show its successful decision')
  assert.ok(!v2ReviewText.includes('保存期限陈述与冻结来源冲突'), 'v1 review issues must not leak into the selected v2 review')
  const v2RevisionDetails = dialog.locator('.review-revisions')
  assert.equal(await v2RevisionDetails.count(), 1, 'review details should retain an in-page version comparison disclosure')
  assert.equal(await v2RevisionDetails.evaluate((node) => node.open), false, 'version comparison should remain folded by default')
  const v2ExecutionSummary = dialog.locator('.audit-execution-summary')
  const v2Context = dialog.locator('.audit-context')
  const v2Identifiers = v2Context.locator('.audit-identifiers')
  assert.equal(await v2ExecutionSummary.evaluate((node) => node.open), false, 'the v2 execution summary should also start folded')
  assert.equal(await v2Identifiers.evaluate((node) => node.open), false, 'the v2 technical identifiers should start folded')
  assert.equal(await v2Context.evaluate((node) => node.open), false, 'the v2 technical context should start folded')
  await v2Context.locator(':scope > summary').click()
  await v2ExecutionSummary.locator(':scope > summary').click()
  assert.ok((await v2ExecutionSummary.innerText()).includes('保存期限与记录字段均有直接冻结来源支持。'), 'expanded v2 execution details should show its persisted decision reason')
  await v2ExecutionSummary.locator(':scope > summary').click()
  await v2Identifiers.locator(':scope > summary').click()
  assert.ok((await v2Identifiers.innerText()).includes('Review ID：review-guide-v2'), 'expanded v2 technical identifiers should expose the explicitly linked review ID')
  await v2Identifiers.locator(':scope > summary').click()
  await v2Context.locator(':scope > summary').click()
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'hidden' })

  await openResourceDelivery(page)
  const guideCard = page.locator('.execution-card').filter({ hasText: '实操指南' }).first()
  assert.ok(await guideCard.innerText().then((value) => value.includes('已发布')), 'publication status should remain visible on the resource card before expanding metadata')
  assert.equal(await guideCard.getByRole('button', { name: '查看已发布资源', exact: true }).count(), 1, 'the published-resource action should remain available')
  assert.equal(await guideCard.getByRole('button', { name: '查看审核报告', exact: true }).count(), 1, 'the Claim review report action should remain available')
  assert.equal(await guideCard.getByRole('button', { name: '查看过程详情', exact: true }).count(), 1, 'the resource workflow detail action should remain available')
  const beforeResourceDetails = auditReadCounts()
  await guideCard.getByRole('button', { name: '查看过程详情', exact: true }).click()
  await dialog.locator('.audit-dialog-heading h2').waitFor()
  await waitForAuditReads(dialog, beforeResourceDetails, 'resource workflow audit details')
  assert.equal(await dialog.locator('select[aria-label="审核资源"]').inputValue(), 'resource-guide',
    'resource-card details should load the selected resource from the current Run')

  assert.equal(await dialog.locator('[role="tablist"], [role="tab"], [role="tabpanel"]').count(), 0, 'the resource review should remain one page')
  const auditResourceSelect = dialog.locator('select[aria-label="审核资源"]')
  assert.equal(await auditResourceSelect.inputValue(), 'resource-guide', 'resource details must select the explicitly linked current Run resource')
  assert.equal(await auditResourceSelect.isVisible(), true, 'a multi-resource review should show its selector with the main review content')
  assert.equal(await auditResourceSelect.evaluate((node) => Boolean(node.closest('.audit-context'))), false,
    'a multi-resource selector should precede the review body instead of being hidden in technical context')
  assert.ok(await dialog.locator('.review-card').count() > 0, 'resource entry should remain a read-only ordinary review subject')
  assert.equal(await dialog.locator('.claim-verification, .claim-evidence-list, .extraction-module').count(), 0,
    'Claim statements and evidence should appear only on the explicit claim_judge detail')
  const reviewRevisions = dialog.locator('.review-revisions')
  assert.equal(await reviewRevisions.count(), 1, 'resource review should retain version comparison in the same page')
  assert.equal(await reviewRevisions.evaluate((node) => node.open), false, 'version comparison should start collapsed')
  await capture(page, 'desktop-audit-overview')
  await reviewRevisions.locator(':scope > summary').click()
  const compareSelect = reviewRevisions.getByRole('combobox', { name: '对比版本' })
  const versionOptions = compareSelect.locator('option')
  const versionOptionValues = await versionOptions.evaluateAll((options) => options.map((item) => item.value))
  assert.deepEqual(versionOptionValues.sort(), ['resource-guide', 'resource-guide-v1'],
    'version comparison should offer only the current resource and its explicit parent')
  assert.ok(!versionOptionValues.includes('resource-guide-other'), 'same-type resources from another spec must not be offered as versions')
  await compareSelect.selectOption('resource-guide')
  const versionText = await reviewRevisions.innerText()
  assert.ok(versionText.includes('每次提交后只需记录操作者。'), 'diff should include the old version text')
  assert.ok(versionText.includes('每次提交后记录操作者、提交时间与结果状态。'), 'diff should include the revised version text')
  assert.ok(versionText.includes('审核记录永久保存。') && versionText.includes('审核记录保留九十天，超过期限后按归档规则清理。'),
    'version comparison should retain both versions’ complete changed facts')
  assert.ok(versionText.includes('按冻结来源修订期限，并补充记录字段'), 'version comparison should retain the parent review instructions')
  assert.ok(versionText.includes('审核通过'), 'version comparison should retain the revised version review status')
  await dialog.locator('.el-dialog__body').evaluate((node) => { node.scrollTop = 0 })
  await capture(page, 'desktop-existing-version')
  await reviewRevisions.locator(':scope > summary').click()
  await capture(page, 'desktop-audit-visualization')

  let releaseDelayedTimeline
  let delayedTimelineFetched = false
  let delayedTimelineDelivered = false
  const delayedTimelineGate = new Promise((resolve) => { releaseDelayedTimeline = resolve })
  await page.route('**/api/runs/run-main/timeline*', async (route) => {
    const response = await route.fetch()
    delayedTimelineFetched = true
    await delayedTimelineGate
    await route.fulfill({ response })
    delayedTimelineDelivered = true
  })
  await dialog.getByRole('button', { name: '刷新数据', exact: true }).click()
  await waitForFixture(() => delayedTimelineFetched, 'delayed old-Run timeline response should be fetched before profile switch')
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'hidden' })
  await chooseOption(page, '学习画像', /周明远/)
  await page.waitForFunction(() => document.querySelector('.summary-code')?.textContent.trim() === 'RUN-ALT')
  await waitForFixture(() => state.requests.some((item) => item.path === '/api/runs/run-alt/timeline'), 'new learner Run timeline after audit close')
  assert.equal(await dialog.isVisible(), false, 'switching learner and Run should close the old audit details')
  releaseDelayedTimeline()
  await waitForFixture(() => delayedTimelineDelivered, 'delayed old-Run response should finish after switching')
  await page.waitForTimeout(50)
  assert.equal(await dialog.isVisible(), false, 'a late old-Run response must not reopen the audit dialog')
  assert.equal(await page.getByText('保存期限陈述与冻结来源冲突', { exact: true }).count(), 0,
    'a late old-Run response must not expose old review content in the newly selected Run')
  await page.unroute('**/api/runs/run-main/timeline*')
  assert.deepEqual(state.writes, [], 'audit details and refresh must remain read only')
  evidence.interactionChecks.push({
    scenario: 'workflow-audit-visualization',
    runId: 'run-main',
    resourceIds: state.timelineDetails.resource_versions.map((item) => item.resource_id),
    evidenceIds: state.timelineDetails.evidence.map((item) => item.evidence_id),
    refreshReads: state.requests.filter((item) => item.path === '/api/runs/run-main/timeline' || item.path === '/api/runs/run-main/claims').length,
    versionOptions: versionOptionValues,
    claimEvidenceSeparate: true,
    versionComparisonCollapsedByDefault: true,
    requestOwnership: { delayedRun: 'run-main', selectedLearner: 'learner-2', selectedRun: 'run-alt', staleContentVisible: false },
    writes: state.writes.length,
  })
  await assertNoExternalOrUnexpected('workflow-audit-visualization')
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'hidden' })
  await page.close()

  const mobilePage = await newPage(browser, base, 'audit-visualization', { width: 390, height: 844 }, { reducedMotion: true })
  const mobileBefore = {
    timeline: state.requests.filter((item) => item.method === 'GET' && item.path === '/api/runs/run-main/timeline').length,
    claims: state.requests.filter((item) => item.method === 'GET' && item.path === '/api/runs/run-main/claims').length,
  }
  await assertResourcePhases(mobilePage, 'audit-visualization-mobile', {
    captureName: 'mobile-resource-delivery-expanded', expectedPhase: '已发布', expectAllPublished: true,
  })
  const mobileGraph = mobilePage.locator('.execution-graph')
  assert.equal(await mobileGraph.locator('.execution-graph-node').count(), 6, 'mobile should also expose the whole actual execution chain')
  assert.equal(await mobilePage.locator('.resource-progress-tree .phase-name').count(), 1, 'mobile workflow should keep one delivery area')
  await mobileGraph.scrollIntoViewIfNeeded()
  await capture(mobilePage, 'mobile-workflow-redesign')
  await openResourceDelivery(mobilePage)
  await mobilePage.locator('.execution-card').filter({ hasText: '实操指南' }).first()
    .getByRole('button', { name: '查看过程详情', exact: true }).click()
  const mobileDialog = mobilePage.locator('.workflow-detail-dialog')
  await mobileDialog.getByRole('heading', { name: '资源审核详情', exact: true }).waitFor()
  await waitForAuditReads(mobileDialog, mobileBefore, 'mobile audit details should load current Run data')
  assert.equal(await mobileDialog.locator('[role="tablist"], [role="tab"], [role="tabpanel"]').count(), 0, 'mobile resource review must stay on one page')
  assert.ok(await mobileDialog.locator('.review-card').count() > 0, 'mobile resource entry should show the ordinary review subject')
  assert.equal(await mobileDialog.locator('.claim-verification, .claim-evidence-list, .extraction-module').count(), 0,
    'mobile resource review must not duplicate Claim statements or evidence')
  const mobileMetrics = await mobilePage.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    dialogWidth: document.querySelector('.workflow-detail-dialog')?.getBoundingClientRect().width || 0,
    dialogClientWidth: document.querySelector('.workflow-detail-dialog')?.clientWidth || 0,
    dialogScrollWidth: document.querySelector('.workflow-detail-dialog')?.scrollWidth || 0,
  }))
  assert.ok(mobileMetrics.documentWidth <= mobileMetrics.viewportWidth + 1, 'mobile audit dialog must not cause horizontal page overflow')
  assert.ok(mobileMetrics.dialogScrollWidth <= mobileMetrics.dialogClientWidth + 1, 'mobile audit dialog content must not overflow horizontally')
  await capture(mobilePage, 'mobile-audit-visualization')
  await assertContrast(mobilePage, 'mobile-audit-visualization')
  await mobilePage.keyboard.press('Escape')
  await mobileDialog.waitFor({ state: 'hidden' })
  assert.deepEqual(state.writes, [], 'mobile audit details must not issue business writes')
  evidence.layoutChecks.push({ label: 'workflow-audit-visualization-mobile', ...mobileMetrics })
  evidence.interactionChecks.push({ scenario: 'workflow-audit-visualization-mobile', keyboardClose: true, writes: 0 })
  await assertNoExternalOrUnexpected('workflow-audit-visualization-mobile')
  await mobilePage.close()
}

async function testAuditContentWorkspace(browser, base) {
  const makeTimeline = () => {
    const timeline = auditVisualizationTimeline('run-main')
    timeline.steps.push({
      ...timeline.steps.find((step) => step.step_id === 'audit-review-v2'),
      step_id: 'audit-claim-judge', step_sequence: 7, node_name: 'claim_judge', agent_name: 'claim_judge',
      action: '事实核验', output_summary: '完成三条陈述的独立判定。',
      evidence_refs: ['evidence-frozen-supported', 'evidence-frozen-contradiction'],
    })
    return timeline
  }
  for (const mobile of [false, true]) {
    const label = mobile ? 'mobile-audit-content' : 'desktop-audit-content'
    const page = await newPage(browser, base, 'audit-visualization', mobile ? { width: 390, height: 844 } : { width: 1393, height: 620 }, { timeline: makeTimeline(), reducedMotion: true })
    const dialog = page.locator('.workflow-detail-dialog')
    const readCount = () => state.requests.filter((item) => item.path === '/api/runs/run-main/claims').length
    const before = readCount()
    await page.locator('.execution-graph-node[data-step-id="audit-claim-judge"]').click()
    await dialog.getByRole('heading', { name: '事实核验 · 执行详情', exact: true }).waitFor()
    await waitForFixture(() => readCount() > before, label + ' Claim load')
    await dialog.getByText('正在加载执行详情…', { exact: true }).waitFor({ state: 'hidden' })
    assert.equal(await dialog.locator('[role="tablist"], [role="tab"], [role="tabpanel"]').count(), 0, 'fact verification should stay on one page without module navigation')
    assert.equal(await dialog.locator('.claim-verification').count(), 1, 'the selected claim_judge step should own the Claim result section')
    const claimList = dialog.getByTestId('claim-evidence-list')
    const claimDetails = claimList.locator('.claim-detail')
    assert.equal(await claimDetails.count(), 3, 'all supported, contradicted, and unsupported factual Claims should remain visible')
    const claimSummaries = await claimList.locator('.claim-detail > summary').allInnerTexts()
    for (const claim of ['每次提交后记录操作者、提交时间与结果状态。', '审核记录永久保存。', '提交时还会自动通知所有关注者。']) {
      assert.ok(claimSummaries.some((summary) => summary.includes(claim)), 'Claim summary should retain the statement: ' + claim)
    }
    assert.ok(claimSummaries[0].includes('获得证据支持'), 'the supported Claim should retain its supported verdict')
    assert.ok(claimSummaries[1].includes('与证据矛盾'), 'the contradicted Claim should retain its contradiction verdict')
    assert.ok(claimSummaries[2].includes('当前证据未支持'), 'the Claim without evidence should retain its unsupported verdict')
    await claimDetails.nth(1).locator('.evidence-excerpt').waitFor({ state: 'visible' })
    assert.deepEqual(await claimDetails.evaluateAll((nodes) => nodes.map((node) => node.open)), [false, true, false], 'the first factual problem should be visible immediately')
    const claimEvidenceTexts = []
    const supportedDetail = claimDetails.nth(0)
    await supportedDetail.locator(':scope > summary').click()
    const supportedText = await supportedDetail.innerText()
    claimEvidenceTexts.push(supportedText)
    assert.ok(supportedText.includes('资源版本 v2'), 'supported Claim provenance should retain its generated resource version')
    assert.ok(supportedText.includes('冻结来源原文：每次提交后记录操作者、提交时间与结果状态。'), 'supported Claim should map to its own frozen evidence ID')
    assertRenderedEvidenceLocator(supportedText, state.timelineDetails.evidence.find(item => item.evidence_id === 'evidence-frozen-supported'), 'supported Claim source')
    const supportedIdentity = supportedDetail.locator('.source-identity')
    await supportedIdentity.locator(':scope > summary').click()
    assert.ok((await supportedIdentity.innerText()).includes('Evidence ID：evidence-frozen-supported'), 'supported Claim should expose its exact frozen Evidence ID')
    await supportedIdentity.locator(':scope > summary').click()
    await supportedDetail.locator(':scope > summary').click()

    const contradictedDetail = claimDetails.nth(1)
    const contradictedText = await contradictedDetail.innerText()
    claimEvidenceTexts.push(contradictedText)
    assert.ok(contradictedText.includes('资源版本 v2'), 'contradicted Claim provenance should retain its generated resource version')
    assert.ok(contradictedText.includes('冻结来源明确规定保存九十天'), 'the initial problem must show its judgement reason')
    assert.ok(contradictedText.includes('冻结来源原文：审核记录保留九十天'), 'the initial problem must show the exact frozen excerpt')
    assert.ok(contradictedText.includes('冻结来源原文：审核记录保留九十天，超过期限后按归档规则清理。'), 'contradicted Claim should map to its own frozen evidence ID')
    assert.ok(contradictedText.includes('生成原句：审核记录永久保存。'), 'the contradicted Claim should preserve the generated sentence separately from its evidence')
    assertRenderedEvidenceLocator(contradictedText, state.timelineDetails.evidence.find(item => item.evidence_id === 'evidence-frozen-contradiction'), 'contradicted Claim source')
    const contradictedIdentity = contradictedDetail.locator('.source-identity')
    await contradictedIdentity.locator(':scope > summary').click()
    assert.ok((await contradictedIdentity.innerText()).includes('Evidence ID：evidence-frozen-contradiction'), 'contradicted Claim should expose its exact frozen Evidence ID')
    await contradictedIdentity.locator(':scope > summary').click()

    const unsupportedDetail = claimDetails.nth(2)
    await unsupportedDetail.locator(':scope > summary').click()
    const unsupportedText = await unsupportedDetail.innerText()
    claimEvidenceTexts.push(unsupportedText)
    assert.ok(unsupportedText.includes('资源版本 v2'), 'unsupported Claim provenance should retain its generated resource version')
    assert.ok(unsupportedText.includes('未关联冻结证据。当前证据未支持，不等于现实中的陈述一定错误。'),
      'a Claim without evidence IDs should show the explicit frozen-evidence empty state')
    await unsupportedDetail.locator(':scope > summary').click()
    assert.deepEqual(await claimDetails.evaluateAll((nodes) => nodes.map((node) => node.open)), [false, true, false], 'expanding provenance must restore the default focused-issue disclosure state')
    assert.equal(await claimList.locator('.evidence-excerpt').count(), 2, 'only evidence-backed Claims should show frozen excerpts')
    const initialEvidenceText = claimEvidenceTexts.join('\n')
    assert.ok(initialEvidenceText.includes('文档版本 3.2') && initialEvidenceText.includes('2.4 提交记录') && initialEvidenceText.includes('1.2 记录保存期限'),
      'Claim evidence should retain the frozen document version and section locators')
    assert.equal(await claimDetails.nth(2).locator('.evidence-excerpt').count(), 0, 'a Claim without evidence IDs must not match a similar frozen source')
    assert.ok(!initialEvidenceText.includes('历史记录缺少版本或审核关联字段'), 'complete provenance should not be rendered as unavailable')

    const refresh = async () => {
      const reads = readCount()
      await dialog.getByRole('button', { name: '刷新数据', exact: true }).click()
      await waitForFixture(() => readCount() > reads, label + ' refresh')
      await dialog.getByText('正在加载执行详情…', { exact: true }).waitFor({ state: 'hidden' })
      assert.equal(await dialog.locator('[role="tablist"], [role="tab"], [role="tabpanel"]').count(), 0, 'refresh should retain the single-page detail model')
      assert.equal(await dialog.locator('.claim-verification').count(), 1, 'refresh should keep the selected claim_judge result visible')
    }

    const context = dialog.locator('.audit-context')
    assert.equal(await context.evaluate((node) => node.open), false, 'auxiliary execution context must start folded on both desktop and mobile')
    await dialog.locator('.el-dialog__body').evaluate((node) => { node.scrollTop = 0 })
    const dimensions = await dialog.evaluate((node) => {
      const main = node.querySelector('.audit-main').getBoundingClientRect()
      const workspace = node.querySelector('.audit-workspace').getBoundingClientRect()
      const body = node.querySelector('.el-dialog__body').getBoundingClientRect()
      const firstContent = node.querySelector('.claim-statement').getBoundingClientRect()
      const scrollers = [...node.querySelectorAll('*')].filter((item) => ['auto', 'scroll'].includes(getComputedStyle(item).overflowY) && item.scrollHeight > item.clientHeight + 1).map((item) => item.className)
      return { mainShare: main.width / workspace.width, firstContentOffset: firstContent.top - body.top, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth, scrollers }
    })
    evidence.layoutChecks.push({ label, ...dimensions })
    await capture(page, label)
    assert.ok(mobile || dimensions.mainShare >= 0.7, 'desktop must dedicate at least 70% of workspace width to audit content: ' + JSON.stringify(dimensions))
    assert.ok(dimensions.firstContentOffset >= 0 && dimensions.firstContentOffset < (mobile ? 300 : 220), 'the first factual statement should be visible near the start of the unscrolled body: ' + JSON.stringify(dimensions))
    assert.ok(dimensions.scrollWidth <= dimensions.clientWidth + 1, 'the audit workspace must have no horizontal overflow')
    assert.ok(dimensions.scrollers.every((item) => item.includes('el-dialog__body')), 'the dialog body must be the only vertical scroll owner')
    await assertContrast(page, label)

    const originalClaims = state.claims
    state.claims = {
      run_id: 'run-main', audit_status: 'incomplete', claims: [], judgements: [],
      resource_metrics: { 'resource-guide': {
        metric_status: 'incomplete', claim_hallucination_rate: null, claim_total: 1,
        factual_claim_total: 1, supported_claim_total: 0, contradicted_claim_total: 0,
        not_in_evidence_claim_total: 0, non_factual_claim_total: 0, incomplete_claim_total: 1,
      } },
    }
    await refresh()
    let refreshedText = await dialog.innerText()
    assert.ok(refreshedText.includes('事实判定未完成'), 'incomplete Claim data should show its explicit summary')
    assert.ok(!refreshedText.includes('核验通过'), 'incomplete Claim data must never display a pass message')
    state.claims = {
      run_id: 'run-main', audit_status: 'not_applicable', claims: [], judgements: [],
      resource_metrics: { 'resource-guide': {
        metric_status: 'not_applicable', claim_hallucination_rate: null, claim_total: 0,
        factual_claim_total: 0, supported_claim_total: 0, contradicted_claim_total: 0,
        not_in_evidence_claim_total: 0, non_factual_claim_total: 0, incomplete_claim_total: 0,
      } },
    }
    await refresh()
    refreshedText = await dialog.innerText()
    assert.ok(refreshedText.includes('通用 Claim 审核不适用'), 'not-applicable Claim data should show its explicit summary')
    assert.ok(!refreshedText.includes('核验通过'), 'not-applicable Claim data must never display a pass message')
    state.claims = originalClaims
    await refresh()

    await claimDetails.nth(1).locator(':scope > summary').click()
    assert.equal(await claimDetails.nth(1).evaluate((node) => node.open), false, 'the initially focused Claim must still be collapsible by the user')
    const filter = claimList.getByRole('combobox', { name: '事实判定筛选' })
    await filter.selectOption('not_in_evidence')
    assert.equal(await claimDetails.count(), 1, 'verdict filtering should show only the selected category')
    assert.ok((await claimDetails.first().innerText()).includes('未关联冻结证据'), 'filtering must retain the explicit missing-evidence explanation')
    await filter.selectOption('all')
    assert.equal(await claimDetails.count(), 3, 'clearing the filter must restore every Claim')
    await inspectNativeSelect({
      page, suite: 'generation', evidenceDir: reportDir, id: `${label}-claim-verdict-native-filter`,
      select: filter, getWriteCount: () => state.writes.length,
    })

    if (mobile) {
      await context.locator(':scope > summary').focus()
      await page.keyboard.press('Enter')
      assert.equal(await context.evaluate((node) => node.open), true, 'mobile context must be expandable with the keyboard')
      assert.equal(await dialog.locator('select[aria-label="审核资源"]').inputValue(), 'resource-guide', 'expanded mobile metadata must retain the explicit resource association')
      const contextText = await context.innerText()
      assert.ok(contextText.includes('节点执行') && contextText.includes('完整执行摘要'), 'technical context should retain execution state and its folded full summary')
      assert.ok(!contextText.includes('普通审核') && !contextText.includes('每次提交后记录操作者、提交时间与结果状态。'),
        'Claim details should not mix ordinary review content or Claim statements into technical context')
      await page.keyboard.press('Enter')
      assert.equal(await context.evaluate((node) => node.open), false, 'mobile context must also be collapsible with the keyboard')
      state.claims.claims[1].claim_text = '审核记录永久保存。'.repeat(30)
      state.claims.judgements[1].reason = '冻结来源规定九十天后按归档规则清理。'.repeat(40)
      state.timelineDetails.evidence[1].excerpt = '冻结来源原文：记录保留九十天。'.repeat(50)
    } else {
      state.claims.claims[0].claim_type = 'non_factual'
      state.claims.judgements[0].verdict = 'non_factual'
      Object.assign(state.claims.resource_metrics['resource-guide'], { factual_claim_total: 2, non_factual_claim_total: 1, supported_claim_total: 0, claim_hallucination_rate: 1 })
    }
    await refresh()
    assert.deepEqual(await claimDetails.evaluateAll((nodes) => nodes.map((node) => node.open)), [false, true, false], mobile ? 'long fact content must retain its focused problem' : 'non-factual content must not take focus away from the factual problem')
    if (mobile) {
      const longMetrics = await dialog.evaluate((node) => ({ scroll: node.scrollWidth, client: node.clientWidth, bodyScroll: node.querySelector('.el-dialog__body').scrollHeight, bodyClient: node.querySelector('.el-dialog__body').clientHeight }))
      assert.ok(longMetrics.scroll <= longMetrics.client + 1, 'long statements, reasons and excerpts must wrap on mobile')
      assert.ok(longMetrics.bodyScroll > longMetrics.bodyClient, 'long evidence must remain accessible through the dialog scroll')
      await dialog.locator('.el-dialog__body').evaluate((node) => { node.scrollTop = node.scrollHeight })
      assert.ok(await claimDetails.nth(2).locator(':scope > summary').isVisible(), 'the final Claim must remain reachable after long evidence')
      await capture(page, 'mobile-audit-long-content')
      evidence.layoutChecks.push({ label: 'mobile-audit-long-content', ...longMetrics })
    } else {
      const supported = auditVisualizationClaims('run-main')
      supported.claims = supported.claims.slice(0, 2)
      supported.judgements = supported.judgements.slice(0, 2)
      const corrected = '审核记录保留九十天，超过期限后按归档规则清理。'
      Object.assign(supported.claims[1], { claim_text: corrected, source_text: corrected, source_end: corrected.length })
      Object.assign(supported.judgements[1], { verdict: 'supported', reason: '与冻结来源原文一致。' })
      Object.assign(supported.resource_metrics['resource-guide'], { claim_total: 2, factual_claim_total: 2, supported_claim_total: 2, contradicted_claim_total: 0, not_in_evidence_claim_total: 0, claim_hallucination_rate: 0 })
      state.claims = supported
      await refresh()
      assert.deepEqual(await claimDetails.evaluateAll((nodes) => nodes.map((node) => node.open)), [true, false], 'an all-supported audit must show only the first Claim by default')
      await claimDetails.first().locator(':scope > summary').click()
      assert.equal(await claimDetails.first().evaluate((node) => node.open), false, 'the all-supported fallback must also support manual collapse')
      assert.equal(await dialog.locator('[role="tablist"], [role="tab"], [role="tabpanel"]').count(), 0, 'an all-supported result should remain in the same Claim page')
      await dialog.locator('.el-dialog__body').evaluate((node) => { node.scrollTop = 0 })
      assert.equal(await dialog.locator('.claim-verification').count(), 1, 'the Claim result remains the only review content for claim_judge')
      await capture(page, 'desktop-audit-approved')
    }
    evidence.interactionChecks.push({ scenario: label, singlePage: true, manualCollapse: true, filtering: true, refreshRolePreserved: true, contextKeyboard: mobile, supportedFallback: !mobile, nonFactualFocusExcluded: !mobile, writes: state.writes.length })
    await page.keyboard.press('Escape')
    await dialog.waitFor({ state: 'hidden' })
    assert.deepEqual(state.writes, [], 'viewing facts and changing presentation must remain read only')
    await assertNoExternalOrUnexpected(label)
    await page.close()
  }
}

async function testNodeDetailRoles(browser, base) {
  const roles = ['diagnose', 'retrieve', 'plan', 'generate', 'review', 'claim_judge']
  const passiveRoles = ['evidence_gate', 'claim_extract']
  const allRoles = [...roles, ...passiveRoles]
  const makeTimeline = () => {
    const timeline = auditVisualizationTimeline('run-main')
    const template = timeline.steps.find(item => item.step_id === 'audit-review-v2')
    const outputs = {
      diagnose: "推荐难度：初级; 盲区：['Embedding', '文档解析']",
      retrieve: '混合候选 12 条；有效证据 2 条；状态：available；来源：知识库',
      evidence_gate: '门禁通过',
      plan: '学习路径：Embedding 的定义与核心思想 -> 文本向量化：从词、句子到固定维度向量 -> 查询与文档编码 -> 语义相似度与向量距离计算',
      generate: '已生成文本表示：实操指南',
      review: '审核通过；覆盖情况以本次审核记录为准。',
      claim_extract: '已抽取三条陈述，后续独立核验。',
      claim_judge: '完成三条陈述的独立判定。',
    }
    timeline.steps = allRoles.map((key, index) => ({
      ...template, step_id: `role-${key}`, node_name: key, agent_name: key, step_sequence: index + 1,
      input_summary: key === 'plan' ? '目标节点：Embedding；诊断盲区：文档解析；证据数：2' : `本次${key}的持久化输入摘要。`,
      output_summary: outputs[key], decision_reason: key === 'plan' ? '先理解文本表示，再学习查询编码，最后用相似度计算验证检索效果。' : `本次${key}的持久化决策理由。`,
      evidence_refs: ['retrieve', 'claim_judge'].includes(key)
        ? ['evidence-frozen-supported', 'evidence-frozen-contradiction']
        : ['diagnose', 'plan', 'generate'].includes(key) ? ['evidence-frozen-supported'] : [],
      resource_ids: ['review', 'claim_judge', 'generate'].includes(key) ? ['resource-guide'] : [],
      review_ids: ['review', 'claim_judge'].includes(key) ? ['review-guide-v2'] : [],
      ...(key === 'retrieve' ? { retrieval_status: 'available', retrieval_query_count: 2, retrieval_candidate_count: 12, retrieval_dropped_candidate_count: 3, retrieval_partial_failure_count: 0 } : {}),
    }))
    return timeline
  }
  for (const mobile of [false, true]) {
    const prefix = mobile ? 'mobile-node' : 'desktop-node'
    const page = await newPage(browser, base, 'audit-visualization', mobile ? { width: 390, height: 844 } : { width: 1393, height: 720 }, { timeline: makeTimeline(), reducedMotion: true })
    const dialog = page.locator('.workflow-detail-dialog')
    const graph = page.locator('.execution-graph')
    const readCount = () => state.requests.filter(item => item.path === '/api/runs/run-main/claims').length
    const readDetail = async (key) => {
      const before = readCount()
      await graph.locator(`.execution-graph-node[data-step-id="role-${key}"]`).click()
      await dialog.waitFor({ state: 'visible' })
      await waitForFixture(() => readCount() > before, prefix + key + ' load')
      await dialog.getByText('正在加载执行详情…', { exact: true }).waitFor({ state: 'hidden' })
      await dialog.evaluate(async node => { await Promise.all(node.getAnimations({ subtree: true }).map(animation => animation.finished.catch(() => {}))) })
    }
    const refresh = async (label) => {
      const before = readCount()
      await dialog.getByRole('button', { name: '刷新数据', exact: true }).click()
      await waitForFixture(() => readCount() > before, prefix + label + ' refresh')
      await dialog.getByText('正在加载执行详情…', { exact: true }).waitFor({ state: 'hidden' })
      assert.equal(await dialog.locator('[role="tablist"], [role="tab"], [role="tabpanel"]').count(), 0, label + ': refresh must preserve the single-page detail model')
    }

    const initialReads = readCount()
    for (const key of passiveRoles) {
      const node = graph.locator(`.execution-graph-node[data-step-id="role-${key}"]`)
      assert.equal(await node.count(), 1, `${key} should remain visible as a recorded status node`)
      assert.equal(await node.getAttribute('data-inspectable'), 'false', `${key} should not expose a detail action`)
      assert.equal(await node.evaluate(element => element.tagName), 'DIV', `${key} must not be rendered as an interactive button`)
      assert.equal(await node.getAttribute('tabindex'), null, `${key} must not enter the keyboard tab order`)
      assert.ok((await node.innerText()).includes('完成'), `${key} should retain its persisted execution status`)
      await node.click()
      assert.equal(await dialog.isVisible(), false, `${key} click must not open detail`)
    }
    assert.equal(readCount(), initialReads, 'passive status nodes must not request Claim details')

    for (const key of roles) {
      await readDetail(key)
      assert.ok((await dialog.locator('.audit-dialog-heading h2').innerText()).endsWith('· 执行详情'), key + ': the header must name this node rather than a shared audit workspace')
      assert.equal(await dialog.locator('[role="tablist"], [role="tab"], [role="tabpanel"]').count(), 0, key + ': detail must have no tab navigation')
      assert.equal(await dialog.locator('.unlinked-note, .el-tabs__item.is-disabled').count(), 0, key + ': no unrelated warning or disabled placeholder')
      assert.equal(await dialog.locator('.audit-context').evaluate(node => node.open), false, key + ': technical context must start folded')

      if (key === 'diagnose') {
        const result = dialog.locator('.node-result[data-role="diagnose"]')
        assert.equal(await result.count(), 1)
        assert.ok((await result.innerText()).includes('初级'))
        assert.ok((await result.innerText()).includes('Embedding'))
      } else if (key === 'retrieve') {
        const result = dialog.locator('.retrieval-result')
        assert.equal(await result.count(), 1, 'retrieval should own one combined result and evidence body')
        assert.deepEqual(await result.locator('.retrieval-stats dd').allInnerTexts(), ['2', 'available', '2', '12', '3', '0'], 'use actual recorded evidence and retrieval fields, including zero')
        assert.equal(await result.locator('.node-evidence-card').count(), 2, 'retrieval should show only explicitly referenced frozen evidence')
        const retrievalText = await result.innerText()
        assert.ok(retrievalText.includes('冻结来源原文：每次提交后记录操作者、提交时间与结果状态。'))
        assert.ok(retrievalText.includes('冻结来源原文：审核记录保留九十天，超过期限后按归档规则清理。'))
        assertRenderedEvidenceLocator(retrievalText, state.timelineDetails.evidence.find(item => item.evidence_id === 'evidence-frozen-supported'), 'retrieval supported source')
        assertRenderedEvidenceLocator(retrievalText, state.timelineDetails.evidence.find(item => item.evidence_id === 'evidence-frozen-contradiction'), 'retrieval contradicted source')
      } else if (key === 'plan') {
        const result = dialog.locator('.node-result[data-role="plan"]')
        assert.equal(await result.count(), 1)
        assert.equal(await result.locator('.planning-path li').count(), 4, 'show only the four topics in the saved summary')
        assert.ok((await result.innerText()).includes('非完整学习计划'))
        assert.ok((await result.innerText()).includes('语义相似度与向量距离计算'), 'last saved topic must be readable')
        assert.equal(await dialog.locator('.node-evidence-card, .claim-detail').count(), 0, 'planning should not duplicate sources or judgements from other roles')
      } else if (key === 'generate') {
        const result = dialog.locator('.node-result[data-role="generate"]')
        assert.equal(await result.count(), 1)
        const generationVersion = state.timelineDetails.resource_versions.find(item => item.resource_id === 'resource-guide')
        const originalBody = generationVersion.content_text
        assert.equal(await result.locator('.generated-content').innerText(), originalBody,
          'generation must show the full explicitly linked version body')
        const literalMarkup = '<img data-ui-injected="literal" alt="should remain text"><script data-ui-injected="literal">window.__generationAuditLiteralMarkupExecuted = true</script>'
        generationVersion.content_text = literalMarkup
        await refresh('generate-literal-html')
        const literalContent = dialog.locator('.node-result[data-role="generate"] .generated-content')
        assert.equal(await literalContent.innerText(), literalMarkup, 'model-provided markup must remain complete literal text in the generated resource body')
        assert.equal(await literalContent.locator('img, script').count(), 0, 'literal resource markup must not create active DOM elements')
        assert.equal(await page.evaluate(() => window.__generationAuditLiteralMarkupExecuted), undefined, 'literal resource script text must not execute')
        generationVersion.content_text = originalBody
        await refresh('generate-body-restored')
        assert.equal(await dialog.locator('.node-result[data-role="generate"] .generated-content').innerText(), originalBody,
          'restoring the actual resource body must keep full markdown output visible')
        assert.equal(await dialog.locator('.node-evidence-card, .claim-detail').count(), 0, 'generation should not duplicate source excerpts or judgements')
      } else if (key === 'review') {
        assert.ok(await dialog.locator('.review-card').count() > 0, 'review should show only its ordinary review record as the main result')
        assert.equal(await dialog.locator('.claim-verification, .claim-detail, .node-evidence-card').count(), 0,
          'ordinary review must not duplicate Claim evidence or retrieval excerpts')
        const revisions = dialog.locator('.review-revisions')
        assert.equal(await revisions.count(), 1, 'version comparison should remain within the review page')
        assert.equal(await revisions.evaluate(node => node.open), false, 'version comparison must start collapsed')
        const selector = dialog.locator('select[aria-label="审核资源"]')
        assert.equal(await selector.isVisible(), false, 'a single linked resource should stay in folded context')
        await dialog.locator('.audit-context > summary').click()
        assert.equal(await selector.inputValue(), 'resource-guide', 'review resource identity must remain explicit')
        await dialog.locator('.audit-context > summary').click()
      } else if (key === 'claim_judge') {
        const result = dialog.locator('.claim-verification')
        assert.equal(await result.count(), 1, 'claim_judge should own the factual verification result')
        assert.equal(await dialog.getByTestId('claim-evidence-list').locator('.claim-detail').count(), 3)
        assert.ok(await dialog.locator('.claim-detail[open] .evidence-excerpt').isVisible(), 'judgement must expose a problematic Claim and its frozen evidence')
        assert.equal(await dialog.locator('.extraction-module').count(), 0, 'claim_judge must not render a separate extraction view')
      }

      if (!['retrieve', 'claim_judge'].includes(key)) {
        assert.equal(await dialog.locator('.node-evidence-card, .evidence-excerpt').count(), 0, key + ': source excerpts must not be duplicated in this role')
      }
      const layout = await dialog.evaluate(node => ({
        scroll: node.scrollWidth, client: node.clientWidth,
        mainShare: node.querySelector('.audit-main').getBoundingClientRect().width / node.querySelector('.audit-workspace').getBoundingClientRect().width,
        scrollers: [...node.querySelectorAll('*')].filter(item => ['auto', 'scroll'].includes(getComputedStyle(item).overflowY) && item.scrollHeight > item.clientHeight + 1).map(item => item.className),
        refreshHeight: node.querySelector('.audit-refresh').getBoundingClientRect().height,
      }))
      assert.ok(layout.scroll <= layout.client + 1, key + ': no horizontal overflow ' + JSON.stringify(layout))
      assert.ok(layout.mainShare >= 0.7 && layout.refreshHeight >= 44, key + ': primary content and hit targets must retain adequate space')
      assert.ok(layout.scrollers.every(item => item.includes('el-dialog__body')), key + ': only the body may scroll vertically')
      evidence.layoutChecks.push({ label: `${prefix}-${key}`, ...layout })
      await capture(page, `${prefix}-${key}`)
      await assertContrast(page, `${prefix}-${key}`)

      if (key === 'plan') {
        const longRaw = '规划结果：未提供结构化路径。' + '完整摘要需要保留。'.repeat(45) + 'END-PLAN-SUMMARY'
        state.timelineDetails.steps.find(item => item.node_name === 'plan').output_summary = longRaw
        await refresh('plan-fallback')
        assert.equal(await dialog.locator('.node-result[data-role="plan"] .result-primary .node-output').innerText(), longRaw,
          'unknown planning summaries must remain complete and must not be reconstructed')
        await dialog.locator('.el-dialog__body').evaluate(node => { node.scrollTop = node.scrollHeight })
        await capture(page, `${prefix}-plan-fallback`)
      } else if (key === 'generate') {
        const generateStep = state.timelineDetails.steps.find(item => item.step_id === 'role-generate')
        generateStep.resource_ids = []
        generateStep.review_ids = []
        await refresh('generate-unbound')
        const unboundResult = dialog.locator('.node-result[data-role="generate"]')
        assert.ok((await unboundResult.innerText()).includes('本节点未关联可读取的生成版本，未使用其他资源替代。'),
          'generation without an explicit resource association must stay empty rather than borrowing another version')
        assert.equal(await unboundResult.locator('.generated-content').count(), 0, 'an unbound generation node must not display another resource body')
        generateStep.resource_ids = ['resource-guide']
        state.timelineDetails.resource_versions.find(item => item.resource_id === 'resource-guide').content_text = null
        await refresh('generate-missing')
        assert.ok((await dialog.locator('.node-result[data-role="generate"]').innerText()).includes('正文未记录'))
        assert.equal(await dialog.locator('.generated-content').count(), 0, 'missing content cannot be replaced with another resource body')
      } else if (key === 'retrieve') {
        state.timelineDetails.steps.find(item => item.node_name === 'retrieve').evidence_refs = ['evidence-missing-explicit']
        await refresh('retrieve-missing-source')
        const missingEvidence = dialog.locator('.retrieval-result .node-evidence-card')
        assert.equal(await missingEvidence.count(), 1)
        assert.ok((await missingEvidence.innerText()).includes('冻结依据缺失'), 'missing explicit evidence must stay visible')
        assert.equal(await missingEvidence.locator('.source-excerpt').count(), 0, 'missing explicit source cannot fall back to another excerpt')
      }
      await page.keyboard.press('Escape')
      await dialog.waitFor({ state: 'hidden' })
    }
    assert.deepEqual(state.writes, [], 'single-page node detail projection and refresh must remain read only')
    evidence.interactionChecks.push({ scenario: prefix + '-role-matrix', roles, passiveRoles, singlePage: true, strictSummaryFallback: true, explicitEvidenceOnly: true, writes: 0 })
    await assertNoExternalOrUnexpected(prefix + '-role-matrix')
    await page.close()
  }
}

async function testNodeClaimDisabled(browser, base) {
  const timeline = auditVisualizationTimeline('run-main')
  timeline.steps.push({ ...timeline.steps.find(item => item.step_id === 'audit-review-v2'), step_id: 'disabled-claim-judge', node_name: 'claim_judge', step_sequence: 7 })
  const page = await newPage(browser, base, 'audit-visualization', baseViewport, { timeline, claimEnabled: false, reducedMotion: true })
  const dialog = page.locator('.workflow-detail-dialog')
  const node = page.locator('.execution-graph-node[data-step-id="disabled-claim-judge"]')
  assert.equal(await node.getAttribute('data-inspectable'), 'true', 'claim_judge remains a detail role when this task disabled Claim checking')
  const readsBefore = state.requests.filter(item => item.path === '/api/runs/run-main/claims').length
  await node.click()
  await dialog.waitFor({ state: 'visible' })
  await waitForFixture(() => state.requests.filter(item => item.path === '/api/runs/run-main/claims').length > readsBefore, 'disabled Claim detail read')
  await dialog.getByText('正在加载执行详情…', { exact: true }).waitFor({ state: 'hidden' })
  assert.equal(await dialog.locator('.claim-verification').count(), 1, 'disabled claim_judge should remain an explicit neutral result')
  assert.equal(await dialog.locator('.claim-detail').count(), 0, 'disabled Claim checking must not fabricate or show Claim rows')
  assert.ok((await dialog.innerText()).includes('此节点没有启用事实核验，不能据此认为事实通过。'), 'disabled Claim remains an explicit neutral state, never a pass')
  assert.deepEqual(state.writes, [], 'viewing disabled Claim status must remain read only')
  evidence.interactionChecks.push({ scenario: 'node-claim-disabled', neutralStatus: true, noFabricatedClaims: true, writes: 0 })
  await assertNoExternalOrUnexpected('node-claim-disabled')
  await page.close()
}

async function testRetriesAndCourseware(browser, base) {
  const partialPage = await newPage(browser, base, 'partial')
  await assertResourcePhases(partialPage, 'partial-resource-delivery', {
    captureName: 'desktop-resource-delivery-failed-unpublished', expectFailedUnpublished: true, captureTitle: '讲义',
  })
  await partialPage.setViewportSize({ width: 390, height: 844 })
  await waitForLayout(partialPage, false)
  await assertResourcePhases(partialPage, 'partial-resource-delivery-mobile', {
    captureName: 'mobile-resource-delivery-failed-unpublished', expectFailedUnpublished: true, captureTitle: '讲义',
  })
  await partialPage.setViewportSize(baseViewport)
  await waitForLayout(partialPage, true)
  await openResourceDelivery(partialPage)
  await partialPage.getByRole('button', { name: '重新生成此资源' }).first().click()
  await partialPage.waitForFunction(() => document.querySelector('.el-message__content')?.textContent.includes('已在当前批次重新生成'))
  const itemRetry = state.writes.filter((item) => item.path.endsWith('/representations/text/retry'))
  assert.equal(itemRetry.length, 1)
  assert.equal(itemRetry[0].path, '/api/generate/jobs/run-main/resource-specs/spec-guide/representations/text/retry')
  assert.equal(state.writes.filter(item => item.path.endsWith('/continuations')).length, 0)
  await partialPage.waitForFunction(() => localStorage.getItem('current_generation_run_id')?.startsWith('resource-retry-'))
  await assertNoExternalOrUnexpected('single-resource-retry')
  await partialPage.close()

  const retryPendingPage = await newPage(browser, base, 'partial')
  await retryPendingPage.locator('.resources-panel > .resource-toolbar .task-actions').getByRole('button', { name: /重新生成失败资源/ }).click()
  await waitForFixture(() => state.writes.some((item) => item.path.endsWith('/continuations')), 'batch retry of pending resources')
  const pendingRetry = state.writes.filter((item) => item.path.endsWith('/continuations'))
  assert.equal(pendingRetry.length, 1)
  assert.equal(pendingRetry[0].body.replace_existing_types, true)
  assert.deepEqual(pendingRetry[0].body.resource_types, ['实操指南'])
  evidence.interactionChecks.push({ scenario: 'pending-resource-batch-retry', write: pendingRetry[0] })
  await assertNoExternalOrUnexpected('pending-resource-batch-retry')
  await retryPendingPage.close()

  const batchFailurePage = await newPage(browser, base, 'failed')
  await batchFailurePage.locator('.resources-panel > .resource-toolbar .task-actions').getByRole('button', { name: '重新生成', exact: true }).click()
  await batchFailurePage.waitForFunction(() => document.querySelector('.el-message__content')?.textContent.includes('已在原资源批次中重新发起'))
  const batchRetry = state.writes.filter((item) => item.path.endsWith('/continuations'))
  assert.equal(batchRetry.length, 1)
  assert.equal(batchRetry[0].body.source_run_id, 'run-main')
  assert.deepEqual(batchRetry[0].body.resource_types, ['讲义', '实操指南', '分阶测试题'])
  evidence.interactionChecks.push({ scenario: 'failed-batch-retry', write: batchRetry[0] })
  await assertNoExternalOrUnexpected('failed-batch-retry')
  await batchFailurePage.close()

  const coursewarePage = await newPage(browser, base, 'completed')
  await openAppendDialog(coursewarePage, 'HTML 互动课件')
  assert.ok(await coursewarePage.locator('.source-list .el-checkbox').count() >= 2, 'courseware dialog should offer published practical/checklist sources')
  const sourceNames = await coursewarePage.locator('.source-list .el-checkbox').allInnerTexts()
  assert.ok(sourceNames.every((text) => /实操指南|复习清单/.test(text)), 'courseware source selection must exclude non-eligible assets')
  const sourceDialog = coursewarePage.getByRole('dialog').filter({ hasText: '创建互动课件' })
  await sourceDialog.evaluate(async (dialog) => {
    await Promise.all(dialog.getAnimations({ subtree: true }).map((animation) => animation.finished.catch(() => {})))
  })
  const dialogMetrics = await sourceDialog.locator('.el-dialog').evaluate((dialog) => {
    const rect = dialog.getBoundingClientRect()
    const body = dialog.querySelector('.el-dialog__body')
    const footer = dialog.querySelector('.el-dialog__footer')
    const primary = footer?.querySelector('.el-button--primary')
    const bodyRect = body?.getBoundingClientRect()
    return {
      dialog: { top: rect.top, bottom: rect.bottom, height: rect.height, maxHeight: getComputedStyle(dialog).maxHeight },
      body: body && bodyRect ? { top: bodyRect.top, bottom: bodyRect.bottom, height: bodyRect.height, scrollHeight: body.scrollHeight, clientHeight: body.clientHeight, overflowY: getComputedStyle(body).overflowY } : null,
      footer: footer ? { top: footer.getBoundingClientRect().top, bottom: footer.getBoundingClientRect().bottom } : null,
      primaryHeight: primary?.getBoundingClientRect().height ?? 0,
      viewportHeight: innerHeight,
    }
  })
  evidence.layoutChecks.push({ label: 'courseware-source-dialog', ...dialogMetrics })
  await capture(coursewarePage, 'desktop-courseware-source-dialog')
  assert.ok(dialogMetrics.dialog.top >= -1 && dialogMetrics.dialog.bottom <= dialogMetrics.viewportHeight + 1, 'courseware source dialog must stay within viewport: ' + JSON.stringify(dialogMetrics))
  assert.notEqual(dialogMetrics.dialog.maxHeight, 'none', 'courseware source dialog must cap its height')
  assert.ok(dialogMetrics.body && dialogMetrics.body.overflowY === 'auto', 'courseware source dialog body should be internally scrollable')
  assert.ok(dialogMetrics.body.top >= dialogMetrics.dialog.top - 1 && dialogMetrics.body.bottom <= dialogMetrics.dialog.bottom + 1, 'courseware source body should stay inside its dialog')
  assert.ok(dialogMetrics.primaryHeight >= 44, 'courseware source dialog primary action should be at least 44px high')
  await assertContrast(coursewarePage, 'courseware-source-dialog')
  await coursewarePage.setViewportSize({ width: 390, height: 844 })
  await sourceDialog.evaluate(async (dialog) => {
    await Promise.all(dialog.getAnimations({ subtree: true }).map((animation) => animation.finished.catch(() => {})))
  })
  const mobileSourceMetrics = await sourceDialog.locator('.el-dialog').evaluate((dialog) => {
    const rect = (node) => {
      const value = node.getBoundingClientRect()
      return { left: value.left, right: value.right, top: value.top, bottom: value.bottom, width: value.width, height: value.height }
    }
    const body = dialog.querySelector('.el-dialog__body')
    const footer = dialog.querySelector('.el-dialog__footer')
    const primary = footer?.querySelector('.el-button--primary')
    const controls = [...dialog.querySelectorAll('.preference-grid .el-input, .preference-grid .el-input-number, .source-list .el-checkbox, .el-dialog__footer button')]
      .filter((node) => node.getClientRects().length)
      .map((node) => ({ text: node.innerText?.trim() || node.getAttribute('aria-label') || node.tagName, ...rect(node) }))
    return {
      viewport: { width: innerWidth, height: innerHeight },
      dialog: { ...rect(dialog), scrollWidth: dialog.scrollWidth, clientWidth: dialog.clientWidth },
      body: body && { ...rect(body), scrollHeight: body.scrollHeight, clientHeight: body.clientHeight, scrollWidth: body.scrollWidth, clientWidth: body.clientWidth },
      footer: footer && rect(footer),
      primaryHeight: primary?.getBoundingClientRect().height ?? 0,
      controls,
    }
  })
  evidence.layoutChecks.push({ label: 'courseware-source-dialog-mobile', ...mobileSourceMetrics })
  assert.ok(mobileSourceMetrics.dialog.left >= -1 && mobileSourceMetrics.dialog.right <= 391, 'mobile source dialog should fit viewport: ' + JSON.stringify(mobileSourceMetrics))
  assert.equal(mobileSourceMetrics.dialog.scrollWidth, mobileSourceMetrics.dialog.clientWidth, 'mobile source dialog should not overflow horizontally')
  assert.ok(mobileSourceMetrics.body && mobileSourceMetrics.body.scrollWidth <= mobileSourceMetrics.body.clientWidth + 1, 'mobile source dialog body should not overflow horizontally')
  assert.ok(mobileSourceMetrics.footer && mobileSourceMetrics.footer.bottom <= 845, 'mobile source dialog footer should remain reachable')
  assert.ok(mobileSourceMetrics.primaryHeight >= 44, 'mobile source dialog primary action should remain at least 44px high')
  for (const control of mobileSourceMetrics.controls) {
    assert.ok(control.left >= mobileSourceMetrics.dialog.left - 1 && control.right <= mobileSourceMetrics.dialog.right + 1, 'mobile source dialog control should stay inside dialog: ' + JSON.stringify(control))
  }
  await sourceDialog.locator('.el-dialog__body').evaluate((body) => { body.scrollTop = body.scrollHeight })
  const mobileFooterAfterScroll = await sourceDialog.locator('.el-dialog__footer').boundingBox()
  assert.ok(mobileFooterAfterScroll && mobileFooterAfterScroll.y + mobileFooterAfterScroll.height <= 845, 'mobile source dialog footer should remain visible after reading to the end')
  evidence.layoutChecks.push({ label: 'courseware-source-dialog-mobile-footer', bodyScrollTop: await sourceDialog.locator('.el-dialog__body').evaluate((body) => body.scrollTop), footer: mobileFooterAfterScroll })
  await capture(coursewarePage, 'mobile-courseware-source-dialog')
  await coursewarePage.setViewportSize({ width: 1393, height: 871 })
  await sourceDialog.evaluate(async (dialog) => {
    await Promise.all(dialog.getAnimations({ subtree: true }).map((animation) => animation.finished.catch(() => {})))
  })
  const learningGoalField = coursewarePage.locator('.preference-grid label').first()
  const learningGoalInput = learningGoalField.locator('input')
  await assertWrappedFieldFocus(coursewarePage, 'courseware-source-learning-goal', learningGoalInput, learningGoalField.locator('.el-input__wrapper'), 'focus-courseware-source-learning-goal', { keyboardFocus: false })
  await learningGoalInput.fill('理解每个学习步骤')
  const expectedDurationField = coursewarePage.locator('.preference-grid label').nth(1)
  await assertWrappedFieldFocus(coursewarePage, 'courseware-source-expected-duration', expectedDurationField.locator('.el-input-number input'), expectedDurationField.locator('.el-input-number .el-input__wrapper'), null, { keyboardFocus: false })
  await coursewarePage.getByRole('button', { name: /生成互动版/ }).click()
  await coursewarePage.waitForSelector('.courseware-generation-page .generation-grid', { state: 'visible' })
  const createWrite = state.writes.find((item) => item.path === '/api/resources/courseware/jobs/batch')
  assert.ok(createWrite, 'courseware append should create a batch job')
  assert.equal(createWrite.body.learner_id, 'learner-1')
  assert.deepEqual(createWrite.body.resource_ids, ['resource-guide', 'resource-checklist'])
  assert.equal(createWrite.body.learning_goal, '理解每个学习步骤')
  assert.equal(createWrite.body.expected_duration_minutes, 30)
  assert.equal(new URL(coursewarePage.url()).pathname, '/generate', 'embedded courseware should remain in the generation workspace')
  await geometry(coursewarePage, 'courseware-embedded', false)
  await capture(coursewarePage, 'desktop-courseware-embedded')
  evidence.interactionChecks.push({ scenario: 'courseware-create', write: createWrite, route: coursewarePage.url() })
  await assertNoExternalOrUnexpected('courseware-create')
  await coursewarePage.close()

  const longCoursewarePage = await newPage(browser, base, 'courseware-long')
  await longCoursewarePage.waitForSelector('.courseware-generation-page .generation-grid', { state: 'visible' })
  await longCoursewarePage.waitForFunction(() => {
    const process = document.querySelector('.generation-grid > .process-panel')
    const details = document.querySelector('.details-scroll')
    return process?.getAttribute('role') === 'region'
      && process.getAttribute('aria-label') === '课件生成过程'
      && process.getAttribute('tabindex') === '0'
      && details?.getAttribute('role') === 'region'
      && details.getAttribute('aria-label') === '课件过程详情'
      && details.getAttribute('tabindex') === '0'
      && details.scrollHeight > details.clientHeight
  })
  const coursewareDetails = longCoursewarePage.locator('.details-scroll')
  const coursewareGeometry = await longCoursewarePage.evaluate(() => {
    const rect = (node) => {
      const value = node.getBoundingClientRect()
      return { top: value.top, bottom: value.bottom, left: value.left, right: value.right, height: value.height, width: value.width }
    }
    const processPanel = document.querySelector('.generation-grid > .process-panel')
    const detailsPanel = document.querySelector('.details-panel')
    const details = document.querySelector('.details-scroll')
    const area = document.querySelector('.content-area')
    const processRegion = processPanel
    const stageLabels = [...document.querySelectorAll('.workflow-snake-copy strong, .workflow-snake-copy small')].map((node) => {
      const style = getComputedStyle(node)
      const bounds = node.getBoundingClientRect()
      const step = node.closest('.workflow-snake-step')?.getBoundingClientRect()
      return {
        text: node.textContent.trim(),
        tag: node.tagName.toLowerCase(),
        overflowX: style.overflowX,
        overflowY: style.overflowY,
        textOverflow: style.textOverflow,
        whiteSpace: style.whiteSpace,
        lineClamp: style.lineClamp || style.webkitLineClamp || 'none',
        maxHeight: style.maxHeight,
        scrollWidth: node.scrollWidth,
        clientWidth: node.clientWidth,
        scrollHeight: node.scrollHeight,
        clientHeight: node.clientHeight,
        top: bounds.top,
        bottom: bounds.bottom,
        stepTop: step?.top ?? null,
        stepBottom: step?.bottom ?? null,
      }
    })
    return {
      fit: document.querySelector('.generate-page')?.classList.contains('is-fit-layout') || false,
      processTitle: rect(processPanel.querySelector('.panel-title')),
      detailsTitle: rect(detailsPanel.querySelector('.panel-title')),
      processPanel: rect(processPanel),
      detailsPanel: rect(detailsPanel),
      processRegion: { ...rect(processRegion), scrollTop: processRegion.scrollTop, scrollHeight: processRegion.scrollHeight, clientHeight: processRegion.clientHeight, scrollWidth: processRegion.scrollWidth, clientWidth: processRegion.clientWidth },
      stageLabels,
      details: { ...rect(details), scrollTop: details.scrollTop, scrollHeight: details.scrollHeight, clientHeight: details.clientHeight, scrollWidth: details.scrollWidth, clientWidth: details.clientWidth },
      outer: { document: document.documentElement.scrollTop, content: area?.scrollTop ?? null, root: document.querySelector('.generate-page')?.scrollTop ?? null },
    }
  })
  evidence.layoutChecks.push({ label: 'courseware-long-initial', ...coursewareGeometry })
  await capture(longCoursewarePage, 'desktop-courseware-long-top')
  assert.ok(Math.abs(coursewareGeometry.processTitle.top - coursewareGeometry.detailsTitle.top) <= 1, 'courseware pane headings should align within 1px: ' + JSON.stringify({ processTitle: coursewareGeometry.processTitle, detailsTitle: coursewareGeometry.detailsTitle }))
  assert.ok(Math.abs(coursewareGeometry.processTitle.bottom - coursewareGeometry.detailsTitle.bottom) <= 1, 'courseware pane heading bottoms should align within 1px: ' + JSON.stringify({ processTitle: coursewareGeometry.processTitle, detailsTitle: coursewareGeometry.detailsTitle }))
  assert.equal(coursewareGeometry.processRegion.scrollWidth, coursewareGeometry.processRegion.clientWidth, 'courseware process region should not overflow horizontally')
  assert.ok(coursewareGeometry.stageLabels.length >= 24, 'courseware snake should render every stage label and description')
  for (const label of coursewareGeometry.stageLabels) {
    assert.ok(label.text, 'courseware stage labels and descriptions should contain readable text')
    assert.equal(label.whiteSpace, 'normal', 'courseware stage text should wrap instead of being forced onto one line: ' + JSON.stringify(label))
    assert.equal(label.textOverflow, 'clip', 'courseware stage text should not use ellipsis: ' + JSON.stringify(label))
    assert.ok(!['hidden', 'clip'].includes(label.overflowX) && !['hidden', 'clip'].includes(label.overflowY), 'courseware stage text should not be clipped by its own box: ' + JSON.stringify(label))
    assert.ok(['none', 'normal', '0', ''].includes(label.lineClamp), 'courseware stage text should not use line clamping: ' + JSON.stringify(label))
    assert.ok(label.maxHeight === 'none' || Number.parseFloat(label.maxHeight) >= label.scrollHeight - 1, 'courseware stage text should not have a restrictive max-height: ' + JSON.stringify(label))
    assert.ok(label.scrollWidth <= label.clientWidth + 1 && label.scrollHeight <= label.clientHeight + 1, 'courseware stage label must fit its rendered box without hidden overflow: ' + JSON.stringify(label))
    assert.ok(label.top >= label.stepTop - 1 && label.bottom <= label.stepBottom + 1, 'courseware stage text should remain inside its node card: ' + JSON.stringify(label))
  }
  const coursewareProcess = longCoursewarePage.locator('.generation-grid > .process-panel')
  await coursewareProcess.evaluate((node) => { node.scrollTop = 0; node.focus() })
  const coursewareProcessFocus = await coursewareProcess.evaluate((node) => ({
    active: document.activeElement === node,
    focusVisible: node.matches(':focus-visible'),
    outline: getComputedStyle(node).outlineStyle,
    outlineWidth: getComputedStyle(node).outlineWidth,
    scrollHeight: node.scrollHeight,
    clientHeight: node.clientHeight,
    scrollTop: node.scrollTop,
  }))
  assert.equal(coursewareProcessFocus.active, true, 'courseware process region should receive keyboard focus')
  assert.ok(coursewareProcessFocus.focusVisible || (coursewareProcessFocus.outline !== 'none' && coursewareProcessFocus.outlineWidth !== '0px'), 'courseware process region should show a focus indicator')
  const processScrollEvidence = { before: coursewareProcessFocus, afterProgram: coursewareProcessFocus.scrollTop, afterKeyboard: coursewareProcessFocus.scrollTop, afterWheel: coursewareProcessFocus.scrollTop, outerBefore: coursewareGeometry.outer, outerAfter: coursewareGeometry.outer, titleAfterWheel: coursewareGeometry.processTitle, footerActions: [] }
  if (coursewareProcessFocus.scrollHeight > coursewareProcessFocus.clientHeight) {
    await coursewareProcess.evaluate((node) => { node.scrollTop = Math.min(120, node.scrollHeight) })
    processScrollEvidence.afterProgram = await coursewareProcess.evaluate((node) => node.scrollTop)
    assert.ok(processScrollEvidence.afterProgram > 0, 'courseware process region should support programmatic scrolling when its content overflows')
    await coursewareProcess.evaluate((node) => { node.scrollTop = 0 })
    await longCoursewarePage.keyboard.press('PageDown')
    await longCoursewarePage.waitForTimeout(80)
    processScrollEvidence.afterKeyboard = await coursewareProcess.evaluate((node) => node.scrollTop)
    assert.ok(processScrollEvidence.afterKeyboard > 0, 'PageDown should scroll an overflowing courseware process region')
    await coursewareProcess.evaluate((node) => { node.scrollTop = 0 })
    const processBox = await coursewareProcess.boundingBox()
    await longCoursewarePage.mouse.move(processBox.x + processBox.width / 2, processBox.y + processBox.height / 2)
    await longCoursewarePage.mouse.wheel(0, 280)
    await longCoursewarePage.waitForTimeout(80)
    processScrollEvidence.afterWheel = await coursewareProcess.evaluate((node) => node.scrollTop)
    assert.ok(processScrollEvidence.afterWheel > 0, 'wheel should scroll an overflowing courseware process region')
    processScrollEvidence.outerAfter = await longCoursewarePage.evaluate(() => ({
      document: document.documentElement.scrollTop,
      content: document.querySelector('.content-area')?.scrollTop ?? null,
      root: document.querySelector('.generate-page')?.scrollTop ?? null,
    }))
    processScrollEvidence.titleAfterWheel = await longCoursewarePage.locator('.process-panel > .panel-title').boundingBox()
    assert.deepEqual(processScrollEvidence.outerAfter, processScrollEvidence.outerBefore, 'courseware process inner wheel should not move outer page')
    assert.ok(Math.abs(processScrollEvidence.titleAfterWheel.y - coursewareGeometry.processTitle.top) <= 1, 'courseware process title should stay fixed while its pane scrolls')
    await coursewareProcess.evaluate((node) => { node.scrollTop = node.scrollHeight })
  }
  const processActions = await longCoursewarePage.locator('.process-panel .process-actions button').evaluateAll((nodes) => nodes.map((node) => {
    const rect = node.getBoundingClientRect()
    const panel = node.closest('.process-panel').getBoundingClientRect()
    return { text: node.innerText.trim(), top: rect.top, bottom: rect.bottom, height: rect.height, visible: rect.width > 0 && rect.height > 0 && getComputedStyle(node).visibility !== 'hidden', insidePanel: rect.top >= panel.top - 1 && rect.bottom <= panel.bottom + 1 }
  }))
  assert.ok(processActions.length > 0, 'courseware process footer actions should remain available')
  for (const action of processActions) {
    assert.ok(action.visible && action.insidePanel, 'courseware process footer action should be reachable within its pane: ' + JSON.stringify(action))
    assert.ok(action.height >= 44, 'courseware process footer action should meet the 44px target: ' + JSON.stringify(action))
  }
  processScrollEvidence.footerActions = processActions
  evidence.scrollChecks.push({ label: 'courseware-process-pane', ...processScrollEvidence })
  await coursewareProcess.evaluate((node) => { node.scrollTop = 0 })
  assert.ok(coursewareGeometry.details.scrollHeight > coursewareGeometry.details.clientHeight, 'long courseware fixture should overflow the details region')
  assert.ok(coursewareGeometry.details.height >= 120, 'courseware details region should remain usable')
  assert.equal(coursewareGeometry.details.scrollWidth, coursewareGeometry.details.clientWidth, 'long courseware details should not overflow horizontally')
  await coursewareDetails.evaluate((node) => { node.scrollTop = 0; node.focus() })
  const coursewareFocus = await coursewareDetails.evaluate((node) => ({
    active: document.activeElement === node,
    focusVisible: node.matches(':focus-visible'),
    outline: getComputedStyle(node).outlineStyle,
    outlineWidth: getComputedStyle(node).outlineWidth,
  }))
  assert.equal(coursewareFocus.active, true, 'courseware details region should be keyboard focusable')
  assert.ok(coursewareFocus.focusVisible || (coursewareFocus.outline !== 'none' && coursewareFocus.outlineWidth !== '0px'), 'courseware details focus indicator should be visible')
  await longCoursewarePage.keyboard.press('PageDown')
  await longCoursewarePage.waitForTimeout(80)
  const coursewareAfterKeyboard = await coursewareDetails.evaluate((node) => node.scrollTop)
  assert.ok(coursewareAfterKeyboard > 0, 'PageDown should scroll courseware details internally')
  await coursewareDetails.evaluate((node) => { node.scrollTop = 0 })
  const detailsBox = await coursewareDetails.boundingBox()
  await longCoursewarePage.mouse.move(detailsBox.x + detailsBox.width / 2, detailsBox.y + detailsBox.height / 2)
  await longCoursewarePage.mouse.wheel(0, 360)
  await longCoursewarePage.waitForTimeout(80)
  const scrollAfterWheel = await coursewareDetails.evaluate((node) => node.scrollTop)
  const outerAfterWheel = await longCoursewarePage.evaluate(() => ({
    document: document.documentElement.scrollTop,
    content: document.querySelector('.content-area')?.scrollTop ?? null,
    root: document.querySelector('.generate-page')?.scrollTop ?? null,
  }))
  const titleAfterWheel = await longCoursewarePage.locator('.details-panel .panel-title').boundingBox()
  assert.ok(scrollAfterWheel > 0, 'wheel should scroll courseware details internally')
  assert.deepEqual(outerAfterWheel, coursewareGeometry.outer, 'courseware inner wheel should not move outer page')
  assert.ok(Math.abs(titleAfterWheel.y - coursewareGeometry.detailsTitle.top) <= 1, 'courseware detail title should stay fixed while details scroll')
  await coursewareDetails.evaluate((node) => { node.scrollTop = node.scrollHeight })
  await longCoursewarePage.waitForTimeout(80)
  const finalWarning = longCoursewarePage.getByText('长课件警告 16', { exact: true })
  const finalWarningRect = await finalWarning.boundingBox()
  const detailsRect = await coursewareDetails.boundingBox()
  assert.ok(finalWarningRect && finalWarningRect.y >= detailsRect.y - 1 && finalWarningRect.y + finalWarningRect.height <= detailsRect.y + detailsRect.height + 1, 'last courseware warning should be reachable inside details region')
  evidence.scrollChecks.push({ label: 'courseware-long', before: coursewareGeometry.details, afterKeyboard: coursewareAfterKeyboard, afterWheel: scrollAfterWheel, outerBefore: coursewareGeometry.outer, outerAfter: outerAfterWheel, coursewareFocus, finalWarningRect, detailsRect })
  await capture(longCoursewarePage, 'desktop-courseware-long')
  await assertContrast(longCoursewarePage, 'courseware-long')
  await longCoursewarePage.setViewportSize({ width: 390, height: 844 })
  await longCoursewarePage.waitForTimeout(120)
  const mobileCoursewareMetrics = await longCoursewarePage.evaluate(() => {
    const area = document.querySelector('.content-area')
    const root = document.querySelector('.generate-page')
    const labels = [...document.querySelectorAll('.workflow-snake-copy strong, .workflow-snake-copy small')].map((node) => {
      const style = getComputedStyle(node)
      return {
        text: node.textContent.trim(),
        whiteSpace: style.whiteSpace,
        textOverflow: style.textOverflow,
        overflowX: style.overflowX,
        overflowY: style.overflowY,
        lineClamp: style.lineClamp || style.webkitLineClamp || 'none',
        scrollWidth: node.scrollWidth,
        clientWidth: node.clientWidth,
        scrollHeight: node.scrollHeight,
        clientHeight: node.clientHeight,
      }
    })
    return {
      viewport: { width: innerWidth, height: innerHeight },
      document: { scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth },
      fit: root?.classList.contains('is-fit-layout') || false,
      area: area && { scrollTop: area.scrollTop, scrollHeight: area.scrollHeight, clientHeight: area.clientHeight, scrollWidth: area.scrollWidth, clientWidth: area.clientWidth },
      labels,
    }
  })
  evidence.layoutChecks.push({ label: 'courseware-long-mobile', ...mobileCoursewareMetrics })
  assert.ok(mobileCoursewareMetrics.document.scrollWidth <= mobileCoursewareMetrics.document.clientWidth + 1, 'mobile courseware page should not overflow horizontally: ' + JSON.stringify({ document: mobileCoursewareMetrics.document }))
  assert.ok(mobileCoursewareMetrics.area && mobileCoursewareMetrics.area.scrollWidth <= mobileCoursewareMetrics.area.clientWidth + 1, 'mobile courseware content should not overflow horizontally: ' + JSON.stringify(mobileCoursewareMetrics.area))
  assert.ok(mobileCoursewareMetrics.area.scrollHeight > mobileCoursewareMetrics.area.clientHeight, 'long courseware content should remain naturally scrollable on mobile')
  assert.equal(mobileCoursewareMetrics.labels.length, coursewareGeometry.stageLabels.length, 'mobile viewport should preserve every workflow stage label and description')
  for (const label of mobileCoursewareMetrics.labels) {
    assert.ok(label.text, 'mobile courseware stage labels should remain readable')
    assert.equal(label.whiteSpace, 'normal', 'mobile courseware stage text should wrap naturally')
    assert.equal(label.textOverflow, 'clip', 'mobile courseware stage text should not use ellipsis')
    assert.ok(!['hidden', 'clip'].includes(label.overflowX) && !['hidden', 'clip'].includes(label.overflowY), 'mobile courseware stage text should not be clipped')
    assert.ok(['none', 'normal', '0', ''].includes(label.lineClamp), 'mobile courseware stage text should not use line clamping')
    assert.ok(label.scrollWidth <= label.clientWidth + 1 && label.scrollHeight <= label.clientHeight + 1, 'mobile courseware stage text should fit its rendered box')
  }
  await capture(longCoursewarePage, 'mobile-courseware-long')
  await longCoursewarePage.locator('.content-area').evaluate((node) => { node.scrollTop = Math.min(240, node.scrollHeight) })
  const mobileCoursewareAfterScroll = await longCoursewarePage.locator('.content-area').evaluate((node) => node.scrollTop)
  assert.ok(mobileCoursewareAfterScroll > 0, 'mobile courseware page should permit natural vertical reading scroll')
  evidence.scrollChecks.push({ label: 'courseware-long-mobile-natural', before: mobileCoursewareMetrics.area.scrollTop, afterProgram: mobileCoursewareAfterScroll, area: mobileCoursewareMetrics.area })
  await assertNoExternalOrUnexpected('courseware-long')
  await longCoursewarePage.close()

  const existingCoursewarePage = await newPage(browser, base, 'courseware-existing')
  await existingCoursewarePage.waitForSelector('.courseware-generation-page .generation-grid', { state: 'visible' })
  assert.ok((await existingCoursewarePage.locator('.details-scroll').innerText()).includes('失败页面'), 'embedded courseware detail should be readable')
  const coursewareTaskActions = existingCoursewarePage.locator('.courseware-generation-page .details-panel > .panel-title .task-actions')
  assert.equal(await coursewareTaskActions.count(), 1, 'courseware task actions should occupy the details heading slot')
  assert.equal(await coursewareTaskActions.getAttribute('role'), 'group', 'courseware task actions should expose group semantics')
  assert.equal(await coursewareTaskActions.getAttribute('aria-label'), '课件任务操作', 'courseware task actions should be named')
  assert.ok(await coursewareTaskActions.getByRole('button', { name: '刷新状态', exact: true }).count(), 'courseware details heading should expose its refresh action')
  assert.ok(await coursewareTaskActions.getByRole('button', { name: '追加资源', exact: false }).count(), 'courseware details heading should retain append actions')
  const coursewareDetailPath = '/api/resources/courseware/jobs/cw-existing/detail'
  await existingCoursewarePage.waitForTimeout(120)
  let detailReadsBefore = state.requests.filter((item) => item.method === 'GET' && item.path === coursewareDetailPath).length
  await coursewareTaskActions.getByRole('button', { name: '刷新状态', exact: true }).click()
  await waitForFixture(() => state.requests.filter((item) => item.method === 'GET' && item.path === coursewareDetailPath).length > detailReadsBefore, 'courseware heading refresh read')
  const headingRefreshReads = state.requests.filter((item) => item.method === 'GET' && item.path === coursewareDetailPath).length - detailReadsBefore
  assert.ok(headingRefreshReads >= 1, 'courseware heading refresh should query the currently selected job')
  detailReadsBefore = state.requests.filter((item) => item.method === 'GET' && item.path === coursewareDetailPath).length
  await existingCoursewarePage.locator('.courseware-generation-page .process-actions').getByRole('button', { name: '刷新状态', exact: true }).click()
  await waitForFixture(() => state.requests.filter((item) => item.method === 'GET' && item.path === coursewareDetailPath).length > detailReadsBefore, 'courseware process refresh read')
  const processRefreshReads = state.requests.filter((item) => item.method === 'GET' && item.path === coursewareDetailPath).length - detailReadsBefore
  assert.ok(processRefreshReads >= 1, 'courseware process refresh should query the same currently selected job')
  evidence.interactionChecks.push({ scenario: 'courseware-refresh-entry-points', path: coursewareDetailPath, headingRefreshReads, processRefreshReads })
  await existingCoursewarePage.getByRole('button', { name: '重试任务' }).click()
  await waitForFixture(() => state.writes.some((item) => item.path.endsWith('/cw-existing/retry')), 'courseware task retry')
  assert.ok(state.writes.some((item) => item.path.endsWith('/cw-existing/retry')), 'courseware task retry should remain available')
  evidence.interactionChecks.push({ scenario: 'courseware-task-retry', writes: state.writes })
  await assertNoExternalOrUnexpected('courseware-task-retry')
  await existingCoursewarePage.close()

  const sceneRetryPage = await newPage(browser, base, 'courseware-existing')
  await sceneRetryPage.waitForSelector('.courseware-generation-page .generation-grid', { state: 'visible' })
  await sceneRetryPage.getByRole('button', { name: '重试此页' }).click()
  await waitForFixture(() => state.writes.some((item) => item.path.endsWith('/scenes/scene-failed/retry')), 'courseware scene retry')
  assert.ok(state.writes.some((item) => item.path.endsWith('/scenes/scene-failed/retry')), 'courseware scene retry should remain available')
  evidence.interactionChecks.push({ scenario: 'courseware-scene-retry', writes: state.writes })
  await assertNoExternalOrUnexpected('courseware-scene-retry')
  await sceneRetryPage.close()
}

async function assertChainGeometry(page, label, stepCount) {
  await page.waitForFunction((count) => document.querySelectorAll('.execution-graph-edge').length === count - 1, stepCount)
  const metrics = await page.locator('.execution-graph').evaluate((graph) => {
    const rect = graph.getBoundingClientRect()
    const nodes = [...graph.querySelectorAll('.execution-graph-node')]
    const anchors = new Map(nodes.map((node) => {
      const anchor = node.querySelector('.execution-graph-anchor').getBoundingClientRect()
      return [node.dataset.stepId, { x: anchor.left + anchor.width / 2, y: anchor.top + anchor.height / 2 }]
    }))
    const edges = [...graph.querySelectorAll('.execution-graph-edge')].map((edge) => {
      const matrix = edge.getScreenCTM()
      const start = edge.getPointAtLength(0)
      const end = edge.getPointAtLength(edge.getTotalLength())
      const startPoint = new DOMPoint(start.x, start.y).matrixTransform(matrix)
      const endPoint = new DOMPoint(end.x, end.y).matrixTransform(matrix)
      const from = anchors.get(edge.dataset.fromStep)
      const to = anchors.get(edge.dataset.toStep)
      return {
        from: edge.dataset.fromStep, to: edge.dataset.toStep,
        upwards: Boolean(from && to && from.y > to.y),
        startError: from ? Math.hypot(startPoint.x - from.x, startPoint.y - from.y) : Infinity,
        endError: to ? Math.hypot(endPoint.x - to.x, endPoint.y - to.y) : Infinity,
        curve: /C|Q/.test(edge.getAttribute('d')),
      }
    })
    return {
      width: rect.width, clientWidth: graph.clientWidth, scrollWidth: graph.scrollWidth,
      viewportWidth: window.innerWidth, documentWidth: document.documentElement.scrollWidth,
      edges, ids: nodes.map((node) => node.dataset.stepId),
      textColumns: nodes.map((node) => node.querySelector('.execution-graph-node-content').getBoundingClientRect().left),
      keyTargets: nodes.filter((node) => node.tagName === 'BUTTON').map((node) => node.getBoundingClientRect().height),
    }
  })
  assert.equal(metrics.ids.length, stepCount, label + ': each execution should retain its own node')
  assert.equal(metrics.edges.length, stepCount - 1, label + ': adjacent records should have one connecting curve')
  assert.ok(metrics.edges.every((edge) => edge.curve && edge.startError < 3 && edge.endError < 3), label + ': measured curves should stay anchored to their own records: ' + JSON.stringify(metrics.edges))
  assert.ok(metrics.edges.every((edge) => edge.upwards), label + ': execution curves should point from older lower steps to newer upper steps')
  assert.ok(Math.max(...metrics.textColumns) - Math.min(...metrics.textColumns) <= 1,
    label + ': every stage should share one aligned text column')
  assert.ok(metrics.keyTargets.every((height) => height >= 44), label + ': key nodes should remain large enough to operate')
  assert.ok(metrics.scrollWidth <= metrics.clientWidth + 1 && metrics.documentWidth <= metrics.viewportWidth + 1, label + ': whole chain should not overflow horizontally')
  evidence.layoutChecks.push({ label, ...metrics })
}

async function testFullWorkflowChain(browser, base) {
  for (const viewport of [baseViewport, { width: 390, height: 844 }]) {
    const mobile = viewport.width === 390
    const page = await newPage(browser, base, 'completed', viewport, { timeline: fullChainTimeline('run-main') })
    const graph = page.locator('.execution-graph')
    await assertChainGeometry(page, mobile ? 'mobile-complete-chain' : 'desktop-complete-chain', 13)
    const ids = await graph.locator('.execution-graph-node').evaluateAll((nodes) => nodes.map((node) => node.dataset.stepId))
    assert.deepEqual(ids, Array.from({ length: 13 }, (_, index) => `chain-${13 - index}`), 'the graph should show the newest actual step first regardless of snapshot input order')
    assert.equal(await graph.locator('[data-node-key="review"]').count(), 2, 'failed review and successful re-review should remain separate')
    assert.equal(await graph.locator('[data-node-key="generate"]').count(), 2, 'both generated versions should remain in the chain')
    const generateCalls = await graph.locator('[data-node-key="generate"] .execution-graph-call-count').allTextContents()
    assert.deepEqual(generateCalls.map((text) => Number(text.match(/\d+/)?.[0])), [2, 1],
      'latest-first presentation must preserve actual chronological call numbers')
    assert.ok(await page.locator('.resource-progress-tree').isVisible(), 'full chain should keep current resource status visible')
    assert.ok(await page.locator('.resource-progress-tree').evaluate((node) => (
      Boolean(node.compareDocumentPosition(document.querySelector('.execution-graph')) & Node.DOCUMENT_POSITION_FOLLOWING)
    )), 'full chain should follow the resource status section')
    const step = graph.locator('[data-step-id="chain-1"]')
    await step.focus()
    const focus = await step.evaluate((node) => ({ visible: node.matches(':focus-visible'), style: getComputedStyle(node).outlineStyle }))
    assert.ok(focus.visible && focus.style !== 'none', 'key node keyboard focus should have a visible outline')
    await assertContrast(page, mobile ? 'mobile-chain-contrast' : 'desktop-chain-contrast')
    const graphAnimations = await graph.evaluate((node) => node.getAnimations({ subtree: true })
      .filter((item) => item.playState === 'running')
      .map((item) => ({ kind: item.constructor.name, duration: item.effect?.getComputedTiming().duration })))
    assert.equal(graphAnimations.filter((item) => item.kind !== 'CSSTransition').length, 0,
      'a completed chain must not run automatic animations; keyboard focus feedback may briefly transition')
    await step.blur()
    const chainFilename = mobile ? 'mobile-complete-chain.png' : 'desktop-complete-chain.png'
    const chainPath = path.join(reportDir, chainFilename)
    // Export the actual rendered canvas outside the scroll viewport so the
    // evidence image contains the complete chain instead of a clipped canvas.
    await graph.evaluate((node) => {
      const copy = node.cloneNode(true)
      const bounds = node.getBoundingClientRect()
      copy.id = 'chain-export-preview'
      Object.assign(copy.style, {
        position: 'absolute', left: '0', top: '0', zIndex: '100000',
        width: `${bounds.width}px`, boxSizing: 'border-box', font: getComputedStyle(node).font,
      })
      document.body.appendChild(copy)
    })
    try {
      await page.locator('#chain-export-preview').screenshot({ path: chainPath,
        style: 'html, body { overflow:visible !important; height:auto !important; max-height:none !important; } body > :not(#chain-export-preview) { visibility:hidden !important; }',
      })
    } finally {
      await page.locator('#chain-export-preview').evaluate((node) => node.remove())
    }
    evidence.screenshots.push({ filename: chainFilename, path: chainPath, viewport: page.viewportSize() })
    await page.locator('.process-scroll').evaluate((node) => { node.scrollTop = 0 })
    await capture(page, mobile ? 'mobile-chain-workspace' : 'desktop-chain-workspace')
    assert.equal(state.writes.length, 0, 'readonly chain inspection must not mutate business data')
    evidence.interactionChecks.push({ scenario: mobile ? 'mobile-complete-chain' : 'desktop-complete-chain', actualOrder: ids, keyboardFocus: true, writes: 0 })
    await assertNoExternalOrUnexpected('complete-chain')
    await page.close()
  }
  const runningPage = await newPage(browser, base, 'running', { width: 390, height: 844 }, {
    timeline: fullChainTimeline('run-main', true), reducedMotion: true,
  })
  const graph = runningPage.locator('.execution-graph')
  await assertChainGeometry(runningPage, 'mobile-running-chain', 11)
  assert.equal(await graph.locator('.execution-graph-node.status-running').count(), 1, 'only the recorded active step should show running status')
  const animations = await graph.evaluate((node) => node.getAnimations({ subtree: true }).filter((item) => item.playState === 'running').length)
  assert.equal(animations, 0, 'reduced-motion should stop running chain animation')
  evidence.motionChecks.push({ label: 'running-chain-reduced-motion', activeAnimations: animations })
  await assertNoExternalOrUnexpected('running-chain-reduced-motion')
  await runningPage.close()
}

async function testIncompleteChainOrder(browser, base) {
  const steps = [
    { step_id: 'no-number', step_sequence: null },
    { step_id: 'tie-first', step_sequence: 4 },
    { step_id: 'tie-second', step_sequence: 4 },
    { step_id: 'oldest', step_sequence: 1 },
  ].map((step) => ({ ...step, run_id: 'run-main', node_name: 'review', agent_name: 'review', status: 'success', action: '审核资源' }))
  const page = await newPage(browser, base, 'completed', baseViewport, {
    timeline: { steps, reviews: [], resource_versions: [], evidence: [] },
  })
  const nodes = page.locator('.execution-graph-node')
  await page.waitForFunction(() => document.querySelectorAll('.execution-graph-node').length === 4)
  assert.deepEqual(await nodes.evaluateAll((items) => items.map((item) => item.dataset.stepId)),
    ['tie-first', 'tie-second', 'oldest', 'no-number'],
    'equal sequences should retain stable input order and missing sequences must not masquerade as newest')
  const missing = page.locator('.execution-graph-node[data-step-id="no-number"] .execution-graph-sequence')
  assert.ok((await missing.innerText()).includes('未记录'), 'a missing sequence should have an explicit unknown label')
  assert.equal(state.writes.length, 0, 'incomplete-history rendering must remain read-only')
  evidence.interactionChecks.push({ scenario: 'chain-missing-and-tied-sequence', stableTies: true, missingLast: true, writes: 0 })
  await assertNoExternalOrUnexpected('chain-missing-and-tied-sequence')
  await page.close()
}

async function testWorkflowIconRoles(browser, base) {
  const roleKeys = [
    'diagnose', 'retrieve', 'evidence_gate', 'plan', 'generate', 'review', 'claim_extract', 'claim_judge',
    'prepare_revision', 'prepare_claim_revision', 'finalize_draft', 'claim_decide', 'finalize', 'finalize_evidence_insufficient',
  ]
  for (const viewport of [baseViewport, { width: 390, height: 844 }]) {
    // An unknown name colliding with Object.prototype must still use fallback.
    const steps = [...roleKeys, 'constructor'].map((key, index) => ({
      step_id: `icon-role-${index + 1}`, step_sequence: index + 1, run_id: 'run-main',
      node_name: key, agent_name: key, status: 'success', action: '图标展示验收',
    }))
    const page = await newPage(browser, base, 'completed', viewport, {
      timeline: { steps, reviews: [], resource_versions: [], evidence: [] },
    })
    await page.waitForFunction(() => document.querySelectorAll('.execution-graph-node').length === 15)
    const icons = await page.locator('.execution-graph-node').evaluateAll((nodes) => nodes.map((node) => ({
      role: node.dataset.nodeKey,
      interactive: node.tagName === 'BUTTON',
      emblemCount: node.querySelectorAll('svg.execution-graph-emblem').length,
      terminalCores: [...node.querySelectorAll('.execution-graph-terminal-core')].map((shape) => shape.tagName.toLowerCase()),
      hexagons: [...node.querySelectorAll('.execution-graph-hexagon')].map((shape) => shape.tagName.toLowerCase()),
      paths: [...node.querySelectorAll('.execution-graph-symbol path, .execution-graph-auxiliary-symbol path')]
        .map((path) => path.getAttribute('d')).join('|'),
    })))
    const known = icons.filter((icon) => roleKeys.includes(icon.role))
    assert.equal(known.length, 14, 'all known workflow roles should render an icon')
    assert.ok(known.every((icon) => icon.paths), 'known roles should not fall back to empty auxiliary symbols')
    assert.equal(new Set(known.map((icon) => icon.paths)).size, 14,
      'different workflow roles must not collapse to the same inner SVG symbol')
    assert.ok(icons.every((icon) => icon.emblemCount === 1), 'each known and unknown role should use one unified execution-graph-emblem SVG')
    const terminal = icons.filter((icon) => icon.role === 'finalize')
    assert.equal(terminal.length, 1, 'the finalization role should be uniquely identifiable by metadata key')
    assert.deepEqual(terminal[0].terminalCores, ['circle'], 'only finalize should use a circular terminal core')
    assert.deepEqual(terminal[0].hexagons, [], 'finalize should not also render the hexagonal role outline')
    for (const icon of icons.filter((entry) => entry.role !== 'finalize')) {
      assert.deepEqual(icon.terminalCores, [], icon.role + ': non-final roles should not render a circular terminal core')
      assert.deepEqual(icon.hexagons, ['path'], icon.role + ': all other known and unknown roles should render one hexagonal outline path')
    }
    assert.equal(icons.filter((icon) => icon.interactive).length, 6,
      'only the six approved business detail roles should remain actionable; auxiliary icons must stay passive')
    const unknown = icons.find((icon) => icon.role === 'constructor')
    assert.ok(unknown?.paths && !unknown.interactive, 'unknown roles should retain a neutral passive symbol')
    assert.ok(!known.some((icon) => icon.paths === unknown.paths), 'unknown fallback should not pretend to be a known business phase')
    const screenshotName = viewport.width === 390 ? 'mobile-role-icons' : 'desktop-role-icons'
    await geometry(page, screenshotName, viewport.width >= 1100)
    await capture(page, screenshotName)
    assert.equal(state.writes.length, 0, 'icon inspection must not write business data')
    evidence.interactionChecks.push({ scenario: 'workflow-role-icons', viewport, knownRoles: known.length, distinctSymbols: 14, terminalCircle: 'finalize', hexagonalRoles: 14, unifiedEmblems: icons.length, detailActions: 6, writes: 0 })
    await assertNoExternalOrUnexpected('workflow-role-icons')
    await page.close()
  }
}

async function testLiveChainScroll(browser, base) {
  const page = await newPage(browser, base, 'running', baseViewport, {
    timeline: fullChainTimeline('run-main', true), reducedMotion: true,
  })
  await waitForLayout(page, true)
  await page.waitForFunction(() => document.querySelectorAll('.execution-graph-node').length === 11)
  await waitForFixture(() => state.sseClients.size === 1, 'live chain SSE connection')
  const area = page.locator('.process-scroll')
  const graph = page.locator('.execution-graph')
  const send = (sequence, stepSequence, type = 'step_started') => {
    const event = {
      run_id: 'run-main', event_id: `evt-live-${sequence}`, sequence,
      event_type: type, step_id: `live-${stepSequence}`, step_sequence: stepSequence,
      node_name: 'review', summary: '实时资源审核',
      status: type === 'step_started' ? 'running' : 'success',
      payload: { duration_ms: type === 'step_started' ? null : 480 },
    }
    for (const response of state.sseClients) {
      response.write(`event: ${event.event_type}\ndata: ${JSON.stringify(event)}\n\n`)
    }
  }
  const readAnchor = () => area.evaluate((scroll) => {
    const bounds = scroll.getBoundingClientRect()
    const nodes = [...scroll.querySelectorAll('.execution-graph-node')]
    const visible = nodes.find((node) => node.getBoundingClientRect().bottom > bounds.top + 1)
    return {
      id: visible?.dataset.stepId,
      offset: visible ? visible.getBoundingClientRect().top - bounds.top : null,
      top: scroll.scrollTop,
      readerTop: document.querySelector('.resource-stage').scrollTop,
      pageTop: document.querySelector('.content-area').scrollTop,
    }
  })
  await area.evaluate((node) => { node.scrollTop = 0 })
  send(1, 12)
  await page.waitForFunction(() => document.querySelector('.execution-graph-node')?.dataset.stepId === 'live-12')
  assert.equal(await graph.locator('.execution-graph-node').count(), 12, 'a new SSE step should prepend one actual record')
  assert.equal(await area.evaluate((node) => node.scrollTop), 0, 'a user at the top should see the newest step without scrolling')
  send(1, 12)
  await page.waitForTimeout(80)
  assert.equal(await graph.locator('[data-step-id="live-12"]').count(), 1, 'replayed SSE events should not duplicate a visual node')
  const anchorTargetOffset = -16
  const historicalNode = graph.locator('.execution-graph-node').nth(3)
  const historicalId = await historicalNode.getAttribute('data-step-id')
  assert.ok(historicalId && historicalId !== 'live-12', 'history scroll setup should choose an existing historical node')
  await historicalNode.evaluate((node, targetOffset) => {
    const scroll = node.closest('.process-scroll')
    const currentOffset = node.getBoundingClientRect().top - scroll.getBoundingClientRect().top
    scroll.scrollTop += currentOffset - targetOffset
  }, anchorTargetOffset)
  const before = await readAnchor()
  assert.equal(before.id, historicalId, 'history scroll setup should anchor the selected historical graph node')
  assert.notEqual(before.id, 'live-12', 'history scroll setup must not leave the first live node as the reading anchor')
  assert.ok(before.top > 24 && before.id && before.offset <= 0,
    'history scroll check should place a real historical record at or just above the process viewport: ' + JSON.stringify(before))
  send(2, 13)
  await page.waitForFunction(() => document.querySelector('.execution-graph-node')?.dataset.stepId === 'live-13')
  await page.waitForTimeout(80)
  const after = await readAnchor()
  assert.equal(after.id, before.id, 'a new top record must not replace the historical step being read')
  assert.ok(Math.abs(after.offset - before.offset) <= 3, 'a new top record should preserve the visible historical offset: ' + JSON.stringify({ before, after }))
  assert.equal(after.readerTop, before.readerTop, 'live chain updates should not scroll the reader')
  assert.equal(after.pageTop, before.pageTop, 'live chain updates should not scroll the outer page')
  send(3, 13, 'step_succeeded')
  await graph.locator('[data-step-id="live-13"].status-success').waitFor()
  const afterStatus = await readAnchor()
  assert.equal(afterStatus.id, after.id, 'status-only updates should keep the historical node in view')
  assert.ok(Math.abs(afterStatus.top - after.top) <= 1 && Math.abs(afterStatus.offset - after.offset) <= 3,
    'status-only updates should not reset or shift scrolling')
  assert.equal(await graph.locator('.execution-graph-node').count(), 13, 'status changes should update the existing step')
  await assertChainGeometry(page, 'live-chain-upwards', 13)
  // Supply the existing second profile with its own completed run, then use
  // the real profile selector to verify remounting and Run scroll isolation.
  state.jobsByLearner['learner-2'] = [makeJob('learner-2', 'run-alt', 'completed', {
    batch_id: 'batch-learner-2',
    request_payload: { learner_id: 'learner-2', resource_types: ['复习清单'], include_review: true, include_claim_check: false },
  })]
  await chooseOption(page, '学习画像', /周明远/)
  await page.waitForFunction(() => document.querySelector('.summary-code')?.textContent.trim() === 'RUN-ALT')
  await page.waitForFunction(() => document.querySelectorAll('.execution-graph-node').length === 6)
  assert.equal(await area.evaluate((node) => node.scrollTop), 0, 'switching Run should start at the newest step of that Run')
  assert.equal(await graph.locator('[data-step-id^="chain-"], [data-step-id^="live-"]').count(), 0, 'the new Run should not retain old visual records')
  assert.equal(state.writes.length, 0, 'live visualization and profile switching must remain read-only')
  evidence.scrollChecks.push({ label: 'live-chain-history-anchor', anchorTargetOffset, before, after, afterStatus, runSwitchTop: 0 })
  evidence.interactionChecks.push({ scenario: 'live-chain-prepend-replay-status-run', records: 13, replayDeduplicated: true, writes: 0 })
  await assertNoExternalOrUnexpected('live-chain-scroll')
  await page.close()
}

async function testLiveResourceProgress(browser, base) {
  const page = await newPage(browser, base, 'resource-live', baseViewport, { reducedMotion: true, traceRunStatusXhr: true })
  await waitForFixture(() => state.sseClients.size === 1, 'resource progress SSE connection')
  const statusSection = page.locator('.resource-progress-tree')
  await statusSection.waitFor({ state: 'visible' })
  const initialCards = await statusSection.locator('.execution-card').evaluateAll((cards) => cards.map((card) => ({
    type: card.querySelector('.execution-title strong')?.textContent.trim() || '',
    phase: card.querySelector('.execution-phase')?.textContent.trim() || '',
    actionCount: card.querySelectorAll('.execution-actions button').length,
  })))
  assert.equal(initialCards.length, 3, 'an arriving execution should replace its matching request placeholder without duplication')
  assert.deepEqual(initialCards.map((card) => card.type), ['实操指南', '复习清单', '讲义'],
    'live execution cards should preserve requested resource identity and order')
  assert.ok(initialCards.some((card) => card.type === '实操指南' && card.phase === '生成中'),
    'the recorded resource attempt should show its actual generating state')
  assert.ok(initialCards.filter((card) => card.type !== '实操指南').every((card) => /等待生成/.test(card.phase) && card.actionCount === 0),
    'request placeholders should remain passive until their matching execution arrives')

  const emitResource = (sequence, eventType, occurredAt, fields = {}) => {
    const event = {
      run_id: 'run-main',
      event_id: 'evt-resource-' + sequence,
      sequence,
      event_sequence: sequence,
      event_type: eventType,
      occurred_at: occurredAt,
      payload: {
        resource_spec_id: 'spec-guide',
        resource_type: '实操指南',
        representation: 'text',
        resource_id: 'resource-guide',
        attempt: 2,
        ...fields,
      },
    }
    for (const response of state.sseClients) {
      response.write('event: ' + event.event_type + '\ndata: ' + JSON.stringify(event) + '\n\n')
    }
  }
  const card = statusSection.locator('.execution-card').filter({ hasText: '实操指南' }).first()
  emitResource(9, 'resource_generation_started', '2026-10-01T08:01:00Z', {
    resource_execution_state: 'generating',
  })
  await card.locator('.execution-phase').filter({ hasText: '生成中' }).waitFor()
  emitResource(10, 'resource_generated', '2026-10-01T08:02:00Z', {
    resource_execution_state: 'generated',
    validation_status: 'pending',
  })
  await card.locator('.execution-phase').filter({ hasText: '等待审核' }).waitFor()
  emitResource(11, 'resource_execution_updated', '2026-10-01T08:03:00Z', {
    resource_execution_state: 'generated',
    validation_status: 'validated',
  })
  await card.locator('.execution-status-field').filter({ hasText: '校验' }).getByText('已通过', { exact: true }).waitFor()

  // The publication event is newer than this same-attempt JobStatus item.
  // The refresh must not roll the visible SSE result back to generated/unpublished.
  state.statusResourceExecutions['run-main'] = [{
    ...state.executionsByRun['run-main'][0],
    resource_execution_state: 'generated',
    validation_status: 'validated',
    publication_status: 'unpublished',
    updated_at: '2026-10-01T08:03:00Z',
  }]
  const statusRequestsBefore = state.requests.filter(item => item.path === '/api/generate/jobs/run-main').length
  const publicationRefreshResponse = page.waitForResponse(response =>
    response.url().includes('/api/generate/jobs/run-main') && response.request().method() === 'GET' && response.status() === 200)
  emitResource(12, 'resource_published', '2026-10-01T08:04:00Z', {
    resource_execution_state: 'approved',
    publication_status: 'published',
    validation_status: 'validated',
  })
  await waitForFixture(() => state.requests.filter(item => item.path === '/api/generate/jobs/run-main').length > statusRequestsBefore,
    'resource publication should refresh the durable JobStatus')
  await publicationRefreshResponse
  await page.waitForFunction(() => {
    const card = [...document.querySelectorAll('.resource-progress-tree .execution-card')]
      .find(item => item.querySelector('.execution-title strong')?.textContent.trim() === '实操指南')
    const fields = [...(card?.querySelectorAll('.execution-status-field') || [])]
    const publication = fields.find(field => field.querySelector('small')?.textContent.trim() === '发布状态')
    const validation = fields.find(field => field.querySelector('small')?.textContent.trim() === '校验')
    return card?.querySelector('.execution-phase')?.textContent.includes('已发布')
      && publication?.querySelector('strong')?.textContent.trim() === '已发布'
      && validation?.querySelector('strong')?.textContent.trim() === '已通过'
  }, null, { timeout: 9000 })
  assert.equal(await statusSection.locator('.execution-card').count(), 3,
    'resource SSE and durable refresh must not reintroduce the replaced request placeholder')
  assert.equal(await card.locator('.execution-phase').innerText(), '已发布',
    'the later same-attempt publication event must survive an older durable status refresh')

  // Hold an older same-Run JobStatus response after capturing its running /
  // unpublished snapshot. A later terminal SSE event starts a newer request;
  // the delayed response must not overwrite that accepted terminal state.
  let releaseDelayedStatus
  const delayedStatusGate = {
    runId: 'run-main',
    started: false,
    snapshot: null,
    newerResponses: 0,
    promise: new Promise(resolve => { releaseDelayedStatus = resolve }),
  }
  delayedStatusGate.release = releaseDelayedStatus
  state.statusGetGate = delayedStatusGate
  const statusAction = page.locator('.resources-panel > .resource-toolbar .task-actions')
    .getByRole('button', { name: '刷新状态', exact: true })
  const requestsBeforeDelayed = state.requests.filter(item => item.path === '/api/generate/jobs/run-main').length
  const delayedStatusResponsePromise = page.waitForResponse(response =>
    response.url().includes('/api/generate/jobs/run-main') && response.request().method() === 'GET'
      && response.status() === 200 && response.headers()['x-fixture-status-snapshot'] === 'held')
  await statusAction.click()
  await waitForFixture(() => delayedStatusGate.started, 'the older JobStatus GET should be held in flight')
  const delayedStatusResponse = await delayedStatusResponsePromise
  assert.equal(delayedStatusGate.snapshot.job_status, 'running', 'the held response should capture the older running job state')
  assert.equal(delayedStatusGate.snapshot.resource_progress_summary.published, 0,
    'the held response should capture the older unpublished summary')
  assert.equal(delayedStatusGate.snapshot.resource_progress_summary.items[0].publication_status, 'unpublished',
    'the held response should capture the older same-attempt resource state')

  const completedJob = findJob('run-main')
  completedJob.job_status = 'completed'
  completedJob.status = 'completed'
  completedJob.finished_at = '2026-10-01T08:05:00Z'
  completedJob.resource_progress_summary = { total: 3, completed: 3, published: 3, failed: 0 }
  state.statusResourceExecutions['run-main'] = [
    ...state.executionsByRun['run-main'],
    execution('spec-checklist', 'resource-checklist', '复习清单', 'approved', { display_order: 2 }),
    execution('spec-lecture', 'resource-lecture', '讲义', 'approved', { display_order: 3 }),
  ].map(item => ({
    ...item,
    resource_execution_state: 'approved',
    publication_status: 'published',
    validation_status: item.resource_type === '实操指南' ? 'validated' : item.validation_status,
    updated_at: '2026-10-01T08:05:00Z',
  }))
  for (const item of state.resourcesByRun['run-main']) {
    item.publication_status = 'published'
    item.claim_publish_decision_pending = false
  }
  const statusXhrSendsBeforeTerminal = await page.evaluate(() => window.__t17RunStatusXhrTrace
    .filter(item => item.kind === 'send' && item.url === '/api/generate/jobs/run-main').length)
  const completedStatusResponse = page.waitForResponse(response =>
    response.url().includes('/api/generate/jobs/run-main') && response.request().method() === 'GET'
      && response.status() === 200 && response.headers()['x-fixture-status-snapshot'] === 'current')
  const terminalEvent = {
    run_id: 'run-main',
    event_id: 'evt-resource-13',
    sequence: 13,
    event_sequence: 13,
    event_type: 'run_completed',
    status: 'completed',
    occurred_at: '2026-10-01T08:05:00Z',
    payload: {},
  }
  const terminalSseClients = [...state.sseClients]
  assert.equal(terminalSseClients.length, 1,
    'the terminal event must be written to the active Run SSE connection, not only to a stale fixture response')
  evidence.interactionChecks.push({
    scenario: 'live-resource-terminal-sse',
    activeSseClientsBeforeTerminal: terminalSseClients.length,
  })
  for (const response of terminalSseClients) {
    response.write('event: run_completed\ndata: ' + JSON.stringify(terminalEvent) + '\n\n')
  }
  await completedStatusResponse
  const statusXhrSendsAfterTerminal = await page.evaluate(() => window.__t17RunStatusXhrTrace
    .filter(item => item.kind === 'send' && item.url === '/api/generate/jobs/run-main').length)
  assert.equal(statusXhrSendsAfterTerminal, statusXhrSendsBeforeTerminal + 1,
    'run_completed should issue one distinct JobStatus XHR while the older no-store GET remains held')
  evidence.interactionChecks.push({
    scenario: 'live-resource-terminal-refresh',
    statusXhrSendsBeforeTerminal,
    statusXhrSendsAfterTerminal,
    terminalRefreshXhrDelta: statusXhrSendsAfterTerminal - statusXhrSendsBeforeTerminal,
  })
  await waitForFixture(() => delayedStatusGate.newerResponses > 0
    && state.requests.filter(item => item.path === '/api/generate/jobs/run-main').length > requestsBeforeDelayed + 1,
  'the terminal SSE event should complete a newer same-Run JobStatus request')
  await page.waitForFunction(() => document.querySelector('.job-summary .production-status')?.textContent.includes('已完成')
    && document.querySelector('.resource-progress-tree .delivery-count')?.textContent.includes('3'), null, { timeout: 9000 })
  assert.equal(await card.locator('.execution-phase').innerText(), '已发布',
    'the terminal refresh should retain the published resource state')

  releaseDelayedStatus()
  await delayedStatusResponse.finished()
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  assert.ok((await page.locator('.job-summary .production-status').innerText()).includes('已完成'),
    'a delayed older JobStatus GET must not roll the accepted completed Run back to running')
  assert.equal(await card.locator('.execution-phase').innerText(), '已发布',
    'a delayed older JobStatus GET must not roll the resource card back to generated')
  assert.match(await statusSection.locator('.delivery-count').innerText(), /3\s*\/\s*3/,
    'a delayed older JobStatus GET must not roll the published count back')
  state.statusGetGate = null
  assert.equal(state.writes.length, 0, 'resource progress and durable refresh fixtures must remain read-only')
  await assertContrast(page, 'live-resource-progress')
  await assertNoExternalOrUnexpected('live-resource-progress')
  evidence.interactionChecks.push({
    scenario: 'live-resource-progress',
    transitions: ['生成中', '校验已通过', '已发布'],
    staleJobRefreshRejected: true,
    delayedSameRunStatusRejected: true,
    placeholdersReplaced: true,
    writes: 0,
  })
  await page.close()
}

async function testReducedMotionAndMobile(browser, base) {
  const page = await newPage(browser, base, 'completed', { width: 390, height: 844 }, { reducedMotion: true })
  const metrics = await geometry(page, '390x844-reduced-motion', false)
  assert.ok(metrics.document.width <= 391, 'mobile reduced-motion page should not overflow horizontally')
  const activeAnimations = await page.evaluate(() => document.getAnimations({ subtree: true })
    .filter((animation) => ['running', 'pending'].includes(animation.playState)
      && Number.isFinite(animation.effect?.getComputedTiming().endTime)
      && animation.effect.getComputedTiming().endTime > 0)
    .map((animation) => ({ name: animation.animationName || '', state: animation.playState, target: animation.effect?.target?.className || '' })))
  assert.deepEqual(activeAnimations, [], 'reduced-motion should not leave non-essential UI animations running')
  await assertContrast(page, '390x844-reduced-motion')
  await capture(page, 'mobile-completed-reduced-motion')
  evidence.motionChecks.push({ viewport: page.viewportSize(), reducedMotion: true, activeAnimations })
  await assertNoExternalOrUnexpected('mobile-reduced-motion')
  await page.close()
}

async function run() {
  mkdirSync(reportDir, { recursive: true })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const base = 'http://127.0.0.1:' + server.address().port
  let browser
  let failure = null
  try {
    browser = await chromium.launch(browserOptions('GENERATION_BROWSER_CHANNEL'))
    await testContinuationContextRaces(browser, base)
    await testFullWorkflowChain(browser, base)
    await testIncompleteChainOrder(browser, base)
    await testWorkflowIconRoles(browser, base)
    await testLiveChainScroll(browser, base)
    await testLiveResourceProgress(browser, base)
    await testFollowupRunNavigation(browser, base)
    await testWorkflowAuditVisualization(browser, base)
    await testNodeDetailRoles(browser, base)
    await testNodeClaimDisabled(browser, base)
    await testAuditContentWorkspace(browser, base)
    await testStateMatrix(browser, base)
    await testPreparationResponsiveStates(browser, base)
    await testLearningPreparationStates(browser, base)
    await testDesktopFitMatrix(browser, base)
    await testNaturalFallback(browser, base)
    await testSwitchesRefreshAndErrors(browser, base)
    await testResourceSwitchAndLearningRoutes(browser, base)
    await testClaimAndAppend(browser, base)
    await testRetriesAndCourseware(browser, base)
    await testReducedMotionAndMobile(browser, base)
    console.log('generation browser tests passed')
  } catch (error) {
    failure = error
    const failurePage = browser?.contexts().flatMap(context => context.pages()).at(-1)
    if (failurePage) {
      await capture(failurePage, 'failure-state').catch(() => {})
      const failureUi = await failurePage.evaluate(() => ({
        graph: document.querySelector('.execution-graph')?.textContent,
        alerts: [...document.querySelectorAll('.el-alert,.jobs-error')].map(item => item.textContent),
        body: document.querySelector('.generate-page')?.textContent?.slice(0, 6000),
      })).catch(() => null)
      writeFileSync(path.join(reportDir, 'failure-ui.json'), JSON.stringify(failureUi, null, 2))
    }
    console.error('generation browser tests failed:', error.stack || error)
  } finally {
    state.statusGetGate?.release?.()
    state.continuationGate?.release?.()
    state.jobsGetGate?.release?.()
    for (const response of state.sseClients) response.end()
    if (browser) await browser.close().catch(() => {})
    await new Promise((resolve) => server.close(resolve))
    const summary = {
      status: failure ? 'FAIL' : 'PASS',
      failure: failure ? String(failure.stack || failure) : null,
      screenshots: evidence.screenshots,
      counts: {
        scenarios: evidence.scenarios.length,
        layouts: evidence.layoutChecks.length,
        scroll: evidence.scrollChecks.length,
        interactions: evidence.interactionChecks.length,
        contrast: evidence.contrastChecks.length,
        motion: evidence.motionChecks.length,
        writes: fixtureAudit.writes.length,
        unexpectedApi: fixtureAudit.unexpectedApi.length,
        externalRequests: externalRequests.length,
        pageErrors: browserErrors.length,
      },
      evidence,
      requests: fixtureAudit.requests,
      writes: fixtureAudit.writes,
      unexpectedApi: fixtureAudit.unexpectedApi,
      externalRequests,
      browserErrors,
    }
    writeFileSync(path.join(reportDir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
    if (failure) process.exitCode = 1
  }
}

await run()
