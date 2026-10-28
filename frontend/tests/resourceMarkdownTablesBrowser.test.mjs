import assert from 'node:assert/strict'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const output = path.resolve(frontend, '../output/test-runs/tables-t31')
mkdirSync(output, { recursive: true })
const server = await createServer({ root: frontend, configFile: path.join(frontend, 'vite.config.js'),
  cacheDir: path.join(output, 'vite-cache'), optimizeDeps: { entries: ['tests/fixtures/resourceMarkdownTables.html'] },
  server: { host: '127.0.0.1', port: 0, strictPort: false, open: false, proxy: {} } })
let browser
const apiRequests = []
const errors = []
try {
  await server.listen()
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`
  browser = await chromium.launch(browserOptions('TEST_BROWSER_CHANNEL'))
  const page = await browser.newPage({ viewport: { width: 1100, height: 850 } })
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', async route => {
    const url = new URL(route.request().url())
    if (url.origin !== origin || /^\/(api|health)(\/|$)/.test(url.pathname)) {
      apiRequests.push(url.pathname)
      return route.abort()
    }
    return route.continue()
  })
  await page.goto(`${origin}/tests/fixtures/resourceMarkdownTables.html`)
  await page.locator('.resource-content table').first().waitFor({ timeout: 20000 })
  assert.equal(await page.locator('.resource-content table').count(), 2)
  const cells = await page.locator('.resource-content th, .resource-content td').evaluateAll(nodes => nodes.map(node => {
    const style = getComputedStyle(node)
    return { widths: ['Top', 'Right', 'Bottom', 'Left'].map(side => parseFloat(style[`border${side}Width`])),
      styles: ['Top', 'Right', 'Bottom', 'Left'].map(side => style[`border${side}Style`]) }
  }))
  assert.ok(cells.length > 0 && cells.every(cell => cell.widths.every(width => width >= 1) && cell.styles.every(style => style === 'solid')))
  await page.screenshot({ path: path.join(output, 'desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  const layout = await page.locator('.markdown-table-scroll').first().evaluate(node => ({
    innerWidth: node.clientWidth, contentWidth: node.scrollWidth, overflowX: getComputedStyle(node).overflowX,
    pageWidth: document.documentElement.scrollWidth, viewport: window.innerWidth,
  }))
  assert.equal(layout.overflowX, 'auto')
  assert.ok(layout.contentWidth > layout.innerWidth && layout.pageWidth <= layout.viewport + 1)
  await page.screenshot({ path: path.join(output, 'mobile.png'), fullPage: true })
  assert.deepEqual(errors, [])
  assert.deepEqual(apiRequests, [])
  writeFileSync(path.join(output, 'browser.json'), JSON.stringify({ status: 'passed', tables: 2, cells: cells.length, borders: 'all four solid >= 1px', layout, apiRequests, errors }, null, 2))
  console.log('PASS isolated table borders, short separators and mobile local scrolling; no API requests')
} finally {
  await browser?.close()
  await server.close()
}
