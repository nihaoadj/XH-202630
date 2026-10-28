import assert from 'node:assert/strict'
import { renderMarkdown as render } from '../src/utils/markdown.js'
const cases = [
  ['excerpt headings, inline and lists', '## 定位顺序\n\n**保留条件**与`chunk_id`。\n\n- 语料\n- 解析\n\n1. 召回\n2. 排序\n\n> 不把超时当无答案', html => {
    for (const tag of ['<h2>定位顺序</h2>', '<strong>保留条件</strong>', '<code>chunk_id</code>', '<ul>', '<ol>', '<blockquote>']) assert.ok(html.includes(tag))
  }],
  ['untrusted HTML and URLs remain inert', '<script>globalThis.pwned=1</script>\n\n<img src="https://invalid.test/a" onerror="alert(1)">\n\n[危险](javascript:alert(1))\n\n<iframe src="https://invalid.test"></iframe>', html => {
    assert.ok(!/<(?:script|img|iframe|a)\b/i.test(html))
    assert.ok(html.includes('&lt;script&gt;') && html.includes('&lt;img'))
  }],
  ['two-dash user table', '| 阶段 | 链路 | 作用 |\n| -- | ------ | -- |\n| 离线 | 解析→切片 | 索引 |\n| 在线 | 召回→回答 | 回答 |', html => {
    assert.equal((html.match(/<th scope="col">/g) || []).length, 3)
    assert.equal((html.match(/<td>/g) || []).length, 6)
  }],
  ['standard and colon separators', '| A | B |\n| :--- | ---: |\n| **加粗** | `API` |', html => {
    assert.ok(html.includes('<table>') && html.includes('<strong>加粗</strong>') && html.includes('<code>API</code>'))
  }],
  ['paragraph boundaries', '表格之前\n| A | B |\n| -- | -- |\n| 1 | 2 |\n\n表格之后', html => {
    assert.match(html, /^<p>表格之前<\/p><div/)
    assert.match(html, /<\/table><\/div><p>表格之后<\/p>$/)
  }],
  ['pipe prose is not a table', '| A | B |\n| 不构成 | 分隔行 |', html => assert.ok(!html.includes('<table>'))],
  ['fenced code stays code', '```markdown\n| A | B |\n| -- | -- |\n| 1 | 2 |\n```', html => {
    assert.ok(html.startsWith('<pre><code>') && !html.includes('<table>'))
  }],
  ['table text remains escaped', '| A | B |\n| -- | -- |\n| <img src=x onerror=alert(1)> | <script>alert(2)</script> |', html => {
    assert.ok(html.includes('&lt;img') && html.includes('&lt;script&gt;'))
    assert.ok(!html.includes('<img') && !html.includes('<script'))
  }],
]
for (const [name, markdown, check] of cases) { check(render(markdown)); console.log(`PASS ${name}`) }
console.log(`${cases.length} resource Markdown table checks passed`)
