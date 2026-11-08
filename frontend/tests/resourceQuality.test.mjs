// T48 deterministic UI checks: metric presentation, transport guard, API path
// and the request-generation discipline of the quality loader.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { ref } from 'vue'

import { api } from '../src/api/client.js'
import { requireRunResourceQualityResponse } from '../src/contracts/guards.js'
import { evaluationApi } from '../src/features/reports/api.js'
import { runApi } from '../src/features/runs/queryApi.js'
import { useResourceQuality } from '../src/features/generation/useResourceQuality.js'
import {
  coverageTargetRows, hallucinationMetricText, isReferenceMetric,
  qualityMetricText, qualityTone, qualityValueText, reasonText, sourceLabel, statusLabel,
} from '../src/utils/qualityMetricsPresentation.js'

const testRoot = path.dirname(fileURLToPath(import.meta.url))
const fixture = JSON.parse(
  readFileSync(path.join(testRoot, 'fixtures/resource-quality-report.json'), 'utf8'),
)
const [measured, unrequested] = fixture.recent_resource_quality

const originalAdapter = api.defaults.adapter
function respond(data, status = 200) {
  api.defaults.adapter = async config => ({
    data: typeof data === 'string' ? data : JSON.stringify(data), status, statusText: String(status),
    config, headers: { 'content-type': 'application/json' },
  })
}

try {
  // --- measured metric: value + source + status, never a bare number --------
  assert.equal(qualityValueText(measured.coverage), '75.0%')
  assert.equal(qualityTone(measured.coverage), 'attention') // 80% < 90% threshold
  assert.equal(sourceLabel(measured.coverage), '普通审核')
  assert.equal(statusLabel(measured.coverage), '已测量')
  assert.match(qualityMetricText(measured.coverage), /^75\.0% · 普通审核 · 已测量/)
  assert.equal(coverageTargetRows(measured).length, 4)
  assert.equal(coverageTargetRows(measured).filter(row => row.covered).length, 3)

  // --- reference: 5% is labelled uncalibrated and never a pass tone ---------
  assert.equal(isReferenceMetric(measured.hallucination), true)
  assert.equal(qualityTone(measured.hallucination), 'attention')
  assert.equal(qualityValueText(measured.hallucination), '5.0%')
  assert.match(hallucinationMetricText(measured.hallucination), /^5% · 普通审核参考 · 未校准 · 待核验$/)

  // --- unmeasured: em dash, reason shown, never "0%" ------------------------
  assert.equal(qualityValueText(unrequested.hallucination), '—')
  assert.equal(qualityTone(unrequested.hallucination), 'muted')
  assert.equal(isReferenceMetric(unrequested.hallucination), false)
  assert.match(reasonText(unrequested.hallucination), /未开启 Claim 核验/)
  assert.doesNotMatch(qualityMetricText(unrequested.hallucination), /0\.0%/)
  assert.equal(qualityValueText(null), '—')
  assert.equal(qualityValueText({ status: 'failed', value: null }), '—')
  assert.equal(qualityValueText({ status: 'complete', value: null }), '—')
  assert.equal(qualityValueText({ status: 'complete', value: 1.4 }), '—')

  // A synthetic 5% real measurement must not be confused with the reference.
  const measuredFive = {
    status: 'complete', value: 0.05, source: 'claim_judge', assessment: 'not_met',
  }
  assert.equal(qualityValueText(measuredFive), '5.0%')
  assert.equal(isReferenceMetric(measuredFive), false)
  assert.equal(qualityTone(measuredFive), 'attention')

  // --- transport guard ------------------------------------------------------
  const valid = {
    run_id: 'run-quality',
    source_revision: 'rev-1',
    availability: 'available',
    items: fixture.recent_resource_quality,
    summary: fixture.resource_quality_summary,
    reason_codes: [],
  }
  assert.equal(requireRunResourceQualityResponse({ data: valid }).data.run_id, 'run-quality')
  assert.throws(() => requireRunResourceQualityResponse({ data: { run_id: 'x' } }))
  assert.throws(() => requireRunResourceQualityResponse({ data: { run_id: 'x', items: [{}] } }))
  assert.throws(() => requireRunResourceQualityResponse({
    data: { run_id: 'x', items: [{ resource_id: 'r', coverage: { value: 0.5 } }] },
  }))

  // --- API path -------------------------------------------------------------
  const calls = []
  api.defaults.adapter = async config => {
    calls.push(config)
    return {
      data: JSON.stringify(valid), status: 200, statusText: '200', config,
      headers: { 'content-type': 'application/json' },
    }
  }
  const response = await runApi.resourceQuality('run-quality')
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/runs/run-quality/resource-quality')
  assert.equal(response.data.items.length, 2)

  const evaluationFixture = JSON.parse(readFileSync(path.join(testRoot, 'fixtures/resource-quality-evaluation.json'), 'utf8'))
  respond({ sample_count: 2, metrics: {}, resource_quality_evaluations: [evaluationFixture] })
  assert.equal((await evaluationApi.summary()).data.resource_quality_evaluations[0].difficulty.value, 1)
  respond({ sample_count: 0, metrics: {} })
  assert.deepEqual((await evaluationApi.summary()).data.resource_quality_evaluations, [])
  respond({ sample_count: 2, metrics: {}, resource_quality_evaluations: [{ ...evaluationFixture, coverage: { status: 'complete', value: 2 } }] })
  await assert.rejects(() => evaluationApi.summary(), /数据格式/)
  respond(valid)

  // --- loader generation discipline ----------------------------------------
  {
    const selectedRunId = ref('run-quality')
    const selectedLearnerId = ref('learner-1')
    const resourceQuality = ref({ stale: true })
    let version = 0
    const loader = useResourceQuality({
      selectedRunId, selectedLearnerId, resourceQuality,
      isMounted: () => true,
      requestVersion: () => version,
      nextRequestVersion: () => ++version,
    })
    await loader.loadResourceQuality()
    assert.deepEqual(Object.keys(resourceQuality.value).sort(), [
      'resource-measured', 'resource-no-claim',
    ])
    // Switching learner clears immediately, before any late response.
    selectedLearnerId.value = 'learner-2'
    assert.deepEqual(resourceQuality.value, {})
  }

  {
    // A late response for an old run must not overwrite the new selection.
    const selectedRunId = ref('run-old')
    const selectedLearnerId = ref('learner-1')
    const resourceQuality = ref({})
    let version = 0
    let release
    api.defaults.adapter = config => new Promise(resolve => {
      release = () => resolve({
        data: JSON.stringify({ ...valid, run_id: 'run-old' }), status: 200,
        statusText: '200', config, headers: { 'content-type': 'application/json' },
      })
    })
    const loader = useResourceQuality({
      selectedRunId, selectedLearnerId, resourceQuality,
      isMounted: () => true,
      requestVersion: () => version,
      nextRequestVersion: () => ++version,
    })
    const pending = loader.loadResourceQuality('run-old')
    selectedRunId.value = 'run-new'
    release()
    await pending
    assert.deepEqual(resourceQuality.value, {})
  }

  {
    // 404 degrades to an empty map without fabricating a metric.
    const selectedRunId = ref('run-missing')
    const selectedLearnerId = ref('learner-1')
    const resourceQuality = ref({ prior: true })
    let version = 0
    respond({ detail: 'not found' }, 404)
    const originalError = console.error
    console.error = () => {}
    const loader = useResourceQuality({
      selectedRunId, selectedLearnerId, resourceQuality,
      isMounted: () => true,
      requestVersion: () => version,
      nextRequestVersion: () => ++version,
    })
    await loader.loadResourceQuality()
    console.error = originalError
    assert.deepEqual(resourceQuality.value, {})
  }

  {
    // Unmounted responses are discarded.
    const selectedRunId = ref('run-quality')
    const selectedLearnerId = ref('learner-1')
    const resourceQuality = ref({})
    let version = 0
    respond(valid)
    const loader = useResourceQuality({
      selectedRunId, selectedLearnerId, resourceQuality,
      isMounted: () => false,
      requestVersion: () => version,
      nextRequestVersion: () => ++version,
    })
    await loader.loadResourceQuality()
    assert.deepEqual(resourceQuality.value, {})
  }
} finally {
  api.defaults.adapter = originalAdapter
}

console.log('resourceQuality: PASS')
