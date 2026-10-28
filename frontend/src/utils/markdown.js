// Safe, lightweight Markdown presentation shared by documents and frozen excerpts.
// Escape source HTML first; only fixed markup is emitted. No links or remote media are loaded.
function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderInlineMarkdown(text) {
  return text
    .replace(/\\([\\`*_{}\[\]()#+.!-])/g, '$1')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
}

function normalizeMarkdown(text) {
  return String(text)
    .replace(/\r\n/g, '\n')
    // Some LLM responses escape Markdown block markers.  These escapes make
    // valid block syntax render as literal text, so only remove them at line
    // starts where they cannot represent prose.
    .replace(/^(\s*)\\(?=[>|])/gm, '$1')
    .replace(/^(\s*)\\(?=---+\s*$)/gm, '$1')
    .replace(/^(\s*\d+)\\\.(?=\s)/gm, '$1.')
    .replace(/^(\s*)\\([-*])(?=\s)/gm, '$1$2')
    .replace(/^(\s*)\\(?=#)/gm, '$1')
    .replace(/^(\s*)\\(?=\x60{3})/gm, '$1')
    .replace(/(?<=\|)\\(?=\n|$)/g, '')
    .replace(/^\s*\\?<!--\s*(?:section|step|code|checklist|quiz):[a-z][a-z0-9-]{1,63}\s*-->\s*$/gmi, '')
}

export function renderMarkdown(text) {
  const normalized = normalizeMarkdown(text)
  const lines = escapeHtml(normalized).split('\n')
  const blocks = []
  // Historical/generated tables also use two-dash separator cells.
  // Share the rule with paragraph termination so such tables cannot be swallowed.
  const tableSeparator = /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$/
  let index = 0
  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) { index += 1; continue }
    if (line.startsWith('```')) {
      const codeLines = []
      index += 1
      while (index < lines.length && !lines[index].startsWith('```')) { codeLines.push(lines[index]); index += 1 }
      if (index < lines.length) index += 1
      blocks.push(`<pre><code>${codeLines.join('\n')}</code></pre>`)
      continue
    }
    if (/^---+\s*$/.test(line)) { blocks.push('<hr />'); index += 1; continue }
    const heading = line.match(/^(#{1,6})\s+(.*)$/)
    if (heading) { blocks.push(`<h${heading[1].length}>${renderInlineMarkdown(heading[2])}</h${heading[1].length}>`); index += 1; continue }
    if (line.startsWith('&gt;')) {
      const quote = []
      while (index < lines.length && lines[index].startsWith('&gt;')) {
        quote.push(lines[index].replace(/^&gt;\s?/, ''))
        index += 1
      }
      blocks.push(`<blockquote><p>${renderInlineMarkdown(quote.join('<br />'))}</p></blockquote>`)
      continue
    }
    if (line.startsWith('|') && index + 1 < lines.length && tableSeparator.test(lines[index + 1])) {
      const cells = value => value.trim().replace(/^\||\|$/g, '').split('|').map(cell => renderInlineMarkdown(cell.trim()))
      const headers = cells(line)
      index += 2
      const rows = []
      while (index < lines.length && lines[index].startsWith('|')) { rows.push(cells(lines[index])); index += 1 }
      const headerHtml = headers.map(cell => `<th scope="col">${cell}</th>`).join('')
      const rowsHtml = rows.map(row => `<tr>${headers.map((_, cellIndex) => `<td>${row[cellIndex] || ''}</td>`).join('')}</tr>`).join('')
      blocks.push(`<div class="markdown-table-scroll" role="region" aria-label="表格，可横向滚动" tabindex="0"><table><thead><tr>${headerHtml}</tr></thead><tbody>${rowsHtml}</tbody></table></div>`)
      continue
    }
    const listMatch = line.match(/^([-*]|\d+\.)\s+(.*)$/)
    if (listMatch) {
      const ordered = /^\d+\.$/.test(listMatch[1])
      const matcher = ordered ? /^\d+\.\s+(.*)$/ : /^[-*]\s+(.*)$/
      const items = []
      while (index < lines.length) {
        const item = lines[index].match(matcher)
        if (item) {
          items.push(`<li>${renderInlineMarkdown(item[1])}</li>`)
          index += 1
          continue
        }
        // Markdown permits a blank line between items. Keep those items in
        // the same list so ordered numbering continues instead of restarting.
        if (!lines[index].trim() && lines[index + 1]?.match(matcher)) {
          index += 1
          continue
        }
        break
      }
      blocks.push(`<${ordered ? 'ol' : 'ul'}>${items.join('')}</${ordered ? 'ol' : 'ul'}>`)
      continue
    }
    const paragraph = []
    while (index < lines.length && lines[index].trim()) {
      if (
        lines[index].startsWith('```') ||
        /^(#{1,6})\s+/.test(lines[index]) ||
        /^([-*]|\d+\.)\s+/.test(lines[index]) ||
        lines[index].startsWith('&gt;') ||
        /^---+\s*$/.test(lines[index]) ||
        (lines[index].startsWith('|') && index + 1 < lines.length && tableSeparator.test(lines[index + 1]))
      ) break
      paragraph.push(lines[index])
      index += 1
    }
    blocks.push(`<p>${renderInlineMarkdown(paragraph.join('<br />'))}</p>`)
  }
  return blocks.join('')
}
