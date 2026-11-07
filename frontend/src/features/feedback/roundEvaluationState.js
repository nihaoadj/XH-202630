/** @typedef {import('../../contracts/generated/contracts').RoundEvaluationSessionV1} Session */
/** @typedef {import('../../contracts/generated/contracts').RoundAttemptSubmitV1} Submission */

/** @param {unknown} value */
export function hasRoundAnswer(value) {
  return value !== null && value !== undefined && (Array.isArray(value) ? value.length > 0 : String(value).trim().length > 0)
}

/** @param {Session} value */
export function requireRoundSession(value) {
  if (!value || typeof value.session_id !== 'string' || !/^[a-f0-9]{64}$/.test(value.manifest_hash)
    || !Array.isArray(value.groups) || !value.groups.length || value.groups.length > 2) throw new Error('联合测评会话格式无效')
  const members = new Set()
  const nodes = new Set()
  const questions = new Set()
  for (const group of value.groups) {
    if (members.has(group.member_id) || nodes.has(group.node_id) || !Array.isArray(group.questions) || !group.questions.length) throw new Error('联合测评题组不完整')
    members.add(group.member_id); nodes.add(group.node_id)
    for (const question of group.questions) {
      if (!question.question_id || questions.has(question.question_id)) throw new Error('联合测评题号重复')
      questions.add(question.question_id)
    }
  }
  return value
}

/** @param {{session: Session, answers: Record<string, unknown>, learnerId:string, profileVersion:number, key:string, submittedAt:string, reflection?: import('../../contracts/generated/contracts').RoundLearningReflectionV1}} input @returns {Submission} */
export function buildRoundSubmission({ session, answers, learnerId, profileVersion, key, submittedAt, reflection }) {
  requireRoundSession(session)
  const questions = session.groups.flatMap(group => group.questions)
  if (questions.some(question => !hasRoundAnswer(answers[question.question_id]))) throw new Error('请完成本次全部节点的测评题')
  return {
    schema_version: '1.0', learner_id: learnerId, session_id: session.session_id, manifest_hash: session.manifest_hash,
    idempotency_key: key, expected_profile_version: profileVersion, submitted_at: submittedAt,
    duration_ms: Math.max(0, Number(reflection?.time_spent_seconds || 0)) * 1000,
    answers: questions.map(question => ({ question_id: question.question_id, answer: JSON.parse(JSON.stringify(answers[question.question_id])) })),
    ...(reflection ? { learning_reflection: JSON.parse(JSON.stringify(reflection)) } : {}),
  }
}

/** @param {string} accountId @param {string} learnerId @param {string} sessionId */
export function roundDraftKey(accountId, learnerId, sessionId) {
  return `learning-round-draft:${accountId}:${learnerId}:${sessionId}`
}

/** @param {Storage} storage @param {string} key @param {Session} session @returns {Submission | null} */
export function readRoundDraft(storage, key, session) {
  try {
    const value = JSON.parse(storage.getItem(key) || 'null')
    if (value?.session_id === session.session_id && value?.manifest_hash === session.manifest_hash) return value
  } catch { /* Browser storage may be unavailable; in-memory draft still works. */ }
  return null
}
