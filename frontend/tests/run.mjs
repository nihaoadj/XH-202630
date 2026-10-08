// Suite membership has one source of truth: tests/suites.json at the repo root.
import { readFileSync, readdirSync, mkdirSync, writeFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const testRoot = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(testRoot, '../..')
const catalog = JSON.parse(readFileSync(path.join(root, 'tests/suites.json'), 'utf8'))
const [group = 'unit', flag, output] = process.argv.slice(2)
if (!Object.hasOwn(catalog.frontend_groups, group) || (flag && (flag !== '--output' || !output))) {
  throw new Error('Usage: node frontend/tests/run.mjs unit|browser [--output path]')
}
function discover(dir, prefix = '') {
  return readdirSync(dir, { withFileTypes: true }).flatMap(item => {
    if (item.name === 'test-results') return []
    const relative = prefix + item.name
    if (item.isDirectory()) return discover(path.join(dir, item.name), relative + '/')
    return item.name.endsWith('.test.mjs') ? [relative] : []
  })
}
const registered = Object.values(catalog.frontend_groups).flat()
const files = discover(testRoot)
if (registered.length !== new Set(registered).size ||
    files.some(file => !registered.includes(file)) || registered.some(file => !files.includes(file))) {
  throw new Error('Test inventory drift: register each frontend test exactly once in tests/suites.json')
}
const report = { schema_version: '1.0', group, evidence_type: group === 'browser' ? 'browser_fixture' : 'deterministic', results: [] }
const env = { ...process.env, RUN_LIVE_LLM: '0', COURSEWARE_LIVE_EVAL: '0', TEST_BROWSER_REQUIRED: '1', COURSEWARE_BROWSER_REQUIRED: '1' }
for (const file of catalog.frontend_groups[group]) {
  console.log(`RUN ${file}`)
  const start = Date.now()
  const result = spawnSync(process.execPath, [path.join(testRoot, file)], { cwd: root, env, stdio: 'inherit' })
  report.results.push({ file, exit_code: result.status, signal: result.signal, status: result.status === 0 ? 'PASS' : 'FAIL', duration_ms: Date.now() - start })
}
report.status = report.results.every(item => item.status === 'PASS') ? 'PASS' : 'FAIL'
if (output) {
  mkdirSync(path.dirname(path.resolve(output)), { recursive: true })
  writeFileSync(output, JSON.stringify(report, null, 2) + '\n')
}
console.log(`${report.status}: ${report.results.length} ${group} test files`)
process.exitCode = report.status === 'PASS' ? 0 : 1
