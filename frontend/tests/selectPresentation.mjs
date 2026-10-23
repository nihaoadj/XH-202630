import assert from 'node:assert/strict'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const runs = new Map()

function safeName(value) {
  return String(value).normalize('NFKD').replace(/[^a-zA-Z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').toLowerCase()
}

async function saveEvidence(page, { suite, evidenceDir, id, state, record }) {
  const targetDir = path.join(evidenceDir, 'select-presentation')
  mkdirSync(targetDir, { recursive: true })
  const viewport = page.viewportSize()
  const filename = `${safeName(suite)}-${safeName(id)}-${viewport.width}x${viewport.height}-${safeName(state)}.png`
  const target = path.join(targetDir, filename)
  await page.screenshot({ path: target, fullPage: false, animations: 'disabled' })
  record.screenshots.push(path.relative(evidenceDir, target).replaceAll('\\', '/'))
}

function saveJson(evidenceDir, record) {
  if (!runs.has(evidenceDir)) runs.set(evidenceDir, [])
  const records = runs.get(evidenceDir)
  const index = records.findIndex((item) => item.id === record.id && item.viewport.width === record.viewport.width && item.viewport.height === record.viewport.height)
  if (index === -1) records.push(record)
  else records[index] = record
  writeFileSync(path.join(evidenceDir, 'select-presentation.json'), JSON.stringify({ status: records.some((item) => item.status === 'FAIL') ? 'FAIL' : 'PASS', controls: records }, null, 2) + '\n', 'utf8')
}

async function readScrollPositions(page) {
  return page.evaluate(() => ({
    x: window.scrollX,
    y: window.scrollY,
    elements: [...document.querySelectorAll('*')].flatMap((node, index) =>
      node.scrollHeight > node.clientHeight || node.scrollWidth > node.clientWidth
        ? [{ index, top: node.scrollTop, left: node.scrollLeft }]
        : []),
  }))
}

async function restoreScrollPositions(page, snapshot) {
  await page.evaluate((saved) => {
    const nodes = document.querySelectorAll('*')
    for (const item of saved.elements) {
      const node = nodes[item.index]
      if (!node) continue
      node.scrollTop = item.top
      node.scrollLeft = item.left
    }
    window.scrollTo(saved.x, saved.y)
  }, snapshot)
}

async function waitForClosedMenus(page) {
  await page.waitForFunction(() => [...document.querySelectorAll('.el-select__popper, .el-dropdown__popper')].every((node) => {
    const style = getComputedStyle(node)
    const rect = node.getBoundingClientRect()
    return style.display === 'none' || style.visibility === 'hidden' || rect.width === 0 || rect.height === 0
  }), undefined, { timeout: 2000 })
}

async function waitForPopupAnimation(popup) {
  await popup.evaluate(async (node) => {
    await new Promise(requestAnimationFrame)
    const animations = node.getAnimations({ subtree: true })
    await Promise.all(animations.map((animation) => animation.finished.catch(() => {})))
    await new Promise(requestAnimationFrame)
  })
}

async function visibleWrapperMetrics(page) {
  return page.locator('.el-select__wrapper').evaluateAll((nodes) => nodes.flatMap((node) => {
    const style = getComputedStyle(node)
    const rect = node.getBoundingClientRect()
    if (style.display === 'none' || style.visibility === 'hidden' || rect.width <= 0 || rect.height <= 0) return []
    const radius = Number.parseFloat(style.borderTopLeftRadius)
    return [{
      label: node.closest('.el-select')?.getAttribute('aria-label') || node.closest('.el-select')?.className || '',
      width: Number(rect.width.toFixed(2)), height: Number(rect.height.toFixed(2)),
      radius, fontSize: style.fontSize, boxShadow: style.boxShadow,
    }]
  }))
}

async function selectSnapshot(select) {
  return select.evaluate((root) => ({
    selectedText: root.querySelector('.el-select__selected-item')?.textContent?.trim() || '',
    placeholder: root.querySelector('.el-select__placeholder')?.textContent?.trim() || '',
    inputValues: [...root.querySelectorAll('input')].map((input) => input.value),
  }))
}

async function contrastFor(element) {
  return element.evaluate((node) => {
    const parse = (value) => {
      const match = value.match(/rgba?\(([^)]+)\)/)
      if (!match) return null
      const parts = match[1].split(',').map((part) => Number.parseFloat(part.trim()))
      return [parts[0], parts[1], parts[2], parts.length > 3 ? parts[3] : 1]
    }
    const composite = (foreground, background) => foreground.slice(0, 3).map((channel, index) => channel * foreground[3] + background[index] * (1 - foreground[3]))
    let backgrounds = [[255, 255, 255]]
    const chain = []
    for (let current = node; current; current = current.parentElement) chain.push(current)
    for (const current of chain.reverse()) {
      const style = getComputedStyle(current)
      const color = parse(style.backgroundColor)
      if (color) backgrounds = backgrounds.map((background) => composite(color, background))
      const gradientStops = [...style.backgroundImage.matchAll(/rgba?\([^)]+\)/g)].map((match) => parse(match[0])).filter(Boolean)
      if (gradientStops.length) backgrounds = gradientStops.flatMap((stop) => backgrounds.map((background) => composite(stop, background)))
    }
    const foreground = parse(getComputedStyle(node).color)
    if (!foreground) return { ratio: 0, color: getComputedStyle(node).color, backgrounds }
    const luminance = (rgb) => rgb.map((channel) => {
      const value = channel / 255
      return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
    }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0)
    const foregroundLum = luminance(foreground.slice(0, 3))
    const ratios = backgrounds.map((background) => {
      const backgroundLum = luminance(background)
      return (Math.max(foregroundLum, backgroundLum) + 0.05) / (Math.min(foregroundLum, backgroundLum) + 0.05)
    })
    return {
      ratio: Number(Math.min(...ratios).toFixed(2)),
      color: getComputedStyle(node).color,
      conservativeBackgrounds: backgrounds.map((background) => background.map((value) => Number(value.toFixed(1)))),
    }
  })
}

async function assertVisibleSurface(page, viewport) {
  const metrics = await visibleWrapperMetrics(page)
  assert.ok(metrics.length, 'page should expose at least one visible Element Plus select wrapper')
  const expectedFontSize = viewport.width <= 600 ? '16px' : '13px'
  for (const item of metrics) {
    assert.ok(Math.abs(item.radius - 10) < 0.1, `select wrapper should use 10px radius: ${JSON.stringify(item)}`)
    assert.ok(item.height >= 44, `select wrapper should be at least 44px high: ${JSON.stringify(item)}`)
    assert.equal(item.fontSize, expectedFontSize, `select font should match ${viewport.width}px viewport: ${JSON.stringify(item)}`)
  }
  const overflow = await page.evaluate(() => ({ viewport: window.innerWidth, page: document.documentElement.scrollWidth }))
  assert.ok(overflow.page <= overflow.viewport + 1, `select page must not overflow horizontally: ${JSON.stringify(overflow)}`)
  return metrics
}

export async function inspectElementSelect({
  page, suite, evidenceDir, id, select, getWriteCount = () => 0, disabled = false,
  longText = '', minHeight = 44, protectEndControlSelector = '',
}) {
  const viewport = page.viewportSize()
  const beforeWrites = getWriteCount()
  const beforeValue = await selectSnapshot(select)
  const beforeFocus = await page.evaluateHandle(() => document.activeElement)
  const beforeScroll = await readScrollPositions(page)
  const record = {
    suite, id, route: new URL(page.url()).pathname, viewport,
    minimumHeight: minHeight, writesBefore: beforeWrites, screenshots: [],
    visibleWrappers: await assertVisibleSurface(page, viewport),
  }
  try {
    await waitForClosedMenus(page)
    assert.equal(await page.locator('.el-select__popper:visible, .el-dropdown__popper:visible').count(), 0,
      `${id}: presentation inspection must start with selection menus closed`)
    const wrapper = select.locator('.el-select__wrapper')
    assert.equal(await wrapper.count(), 1, `${id}: expected one Element Plus select wrapper`)
    const disabledStyle = await wrapper.evaluate((node) => node.classList.contains('is-disabled'))
    if (disabled) {
      assert.equal(disabledStyle, true, `${id}: existing fixture should expose a disabled select`)
      const rect = await wrapper.boundingBox()
      assert.ok(rect && rect.height >= minHeight, `${id}: disabled select should retain its hit target`)
      await saveEvidence(page, { suite, evidenceDir, id, state: 'disabled-trigger', record })
      assert.equal(await page.locator('.el-select__popper:visible').count(), 0, `${id}: disabled select must not have an open popper`)
    } else {
      assert.equal(disabledStyle, false, `${id}: selected fixture control should be enabled`)
      await page.evaluate(() => document.activeElement?.blur?.())
      await page.mouse.move(0, 0)
      await wrapper.scrollIntoViewIfNeeded()
      await page.waitForTimeout(180)
      const normal = await wrapper.evaluate((node) => {
        const rect = node.getBoundingClientRect()
        const style = getComputedStyle(node)
        return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, radius: Number.parseFloat(style.borderTopLeftRadius), shadow: style.boxShadow }
      })
      assert.ok(normal.height >= minHeight, `${id}: select should be at least ${minHeight}px high: ${JSON.stringify(normal)}`)
      await saveEvidence(page, { suite, evidenceDir, id, state: 'trigger', record })
      await wrapper.hover()
      await page.waitForTimeout(180)
      const hovered = await wrapper.evaluate((node) => {
        const rect = node.getBoundingClientRect()
        const style = getComputedStyle(node)
        return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, radius: Number.parseFloat(style.borderTopLeftRadius), shadow: style.boxShadow }
      })
      assert.deepEqual([hovered.x, hovered.y, hovered.width, hovered.height], [normal.x, normal.y, normal.width, normal.height], `${id}: hover must not change select geometry`)
      assert.ok(Math.abs(hovered.radius - 10) < 0.1, `${id}: hover must retain shared radius`)
      const input = select.locator('input').first()
      if (await input.count()) await input.evaluate((node) => node.focus({ preventScroll: true }))
      else await wrapper.evaluate((node) => node.focus({ preventScroll: true }))
      await page.waitForTimeout(180)
      const focused = await wrapper.evaluate((node) => {
        const rect = node.getBoundingClientRect()
        const style = getComputedStyle(node)
        return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, radius: Number.parseFloat(style.borderTopLeftRadius), shadow: style.boxShadow }
      })
      assert.deepEqual([focused.x, focused.y, focused.width, focused.height], [normal.x, normal.y, normal.width, normal.height], `${id}: focus must not change select geometry`)
      assert.ok(Math.abs(focused.radius - 10) < 0.1, `${id}: focus must retain shared radius`)
      assert.notEqual(focused.shadow, normal.shadow, `${id}: focus should visibly change the wrapper shadow`)
      const triggerText = select.locator('.el-select__selected-item, .el-select__placeholder').first()
      const triggerContrast = await contrastFor(triggerText)
      assert.ok(triggerContrast.ratio >= 4.5, `${id}: visible select text contrast should be at least 4.5:1: ${JSON.stringify(triggerContrast)}`)
      await saveEvidence(page, { suite, evidenceDir, id, state: 'trigger-focus', record })
      await wrapper.click()
      const popper = page.locator('.el-select__popper:visible').last()
      await popper.waitFor({ state: 'visible' })
      await waitForPopupAnimation(popper)
      const popup = await popper.evaluate((node) => {
        const rect = node.getBoundingClientRect()
        const style = getComputedStyle(node)
        return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, right: rect.right, bottom: rect.bottom, radius: Number.parseFloat(style.borderTopLeftRadius) }
      })
      assert.ok(Math.abs(popup.radius - 12) < 0.1, `${id}: teleported select menu should use 12px radius: ${JSON.stringify(popup)}`)
      assert.ok(popup.x >= -1 && popup.right <= viewport.width + 1 && popup.y >= -1 && popup.bottom <= viewport.height + 1,
        `${id}: select menu must stay inside viewport: ${JSON.stringify(popup)}`)
      const rows = popper.locator('.el-select-dropdown__item:visible')
      assert.ok(await rows.count(), `${id}: select menu should expose real option rows`)
      const rowMetrics = await rows.evaluateAll((nodes) => nodes.map((node) => {
        const rect = node.getBoundingClientRect()
        const style = getComputedStyle(node)
        return { text: node.textContent.trim(), height: rect.height, y: rect.y, bottom: rect.bottom, selected: node.classList.contains('is-selected'), whiteSpace: style.whiteSpace, textOverflow: style.textOverflow, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth }
      }))
      for (const row of rowMetrics) assert.ok(row.height >= 44, `${id}: menu row should be at least 44px high: ${JSON.stringify(row)}`)
      const selectedCount = await popper.locator('.el-select-dropdown__item.is-selected:visible').count()
      assert.ok(selectedCount, `${id}: current value should remain visibly selected in the menu`)
      const selectedContrast = await contrastFor(popper.locator('.el-select-dropdown__item.is-selected:visible').first())
      assert.ok(selectedContrast.ratio >= 4.5, `${id}: selected option contrast should be at least 4.5:1: ${JSON.stringify(selectedContrast)}`)
      if (protectEndControlSelector) {
        const marker = await popper.locator('.el-select-dropdown__item.is-selected:visible').first().evaluate((row, selector) => {
          const control = row.querySelector(selector)
          const style = getComputedStyle(row, '::before')
          const rowRect = row.getBoundingClientRect()
          const controlRect = control?.getBoundingClientRect()
          return controlRect ? { markerRight: rowRect.left + Number.parseFloat(style.left) + Number.parseFloat(style.width), controlLeft: controlRect.left } : null
        }, protectEndControlSelector)
        assert.ok(marker && marker.markerRight <= marker.controlLeft - 1,
          `${id}: selected check must not overlap the profile delete control: ${JSON.stringify(marker)}`)
        record.profileDeleteClearance = marker
      }
      if (longText) {
        const longRow = rows.filter({ hasText: longText }).first()
        await longRow.waitFor({ state: 'visible' })
        await longRow.scrollIntoViewIfNeeded()
        const longMetrics = await longRow.evaluate((node) => {
          const rect = node.getBoundingClientRect()
          const style = getComputedStyle(node)
          return { text: node.textContent.trim(), x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height, whiteSpace: style.whiteSpace, textOverflow: style.textOverflow, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth, scrollHeight: node.scrollHeight, clientHeight: node.clientHeight }
        })
        assert.ok(longMetrics.text.includes(longText), `${id}: long option must retain its complete label`)
        assert.equal(longMetrics.whiteSpace, 'normal', `${id}: long option should wrap`)
        assert.notEqual(longMetrics.textOverflow, 'ellipsis', `${id}: long option should not use ellipsis`)
        assert.ok(longMetrics.scrollWidth <= longMetrics.clientWidth + 1 && longMetrics.scrollHeight <= longMetrics.clientHeight + 1,
          `${id}: long option must not clip its text: ${JSON.stringify(longMetrics)}`)
        assert.ok(longMetrics.x >= -1 && longMetrics.right <= viewport.width + 1 && longMetrics.y >= -1 && longMetrics.bottom <= viewport.height + 1,
          `${id}: long option should remain inside the real viewport: ${JSON.stringify(longMetrics)}`)
        await longRow.hover()
        const longContrast = await contrastFor(longRow)
        assert.ok(longContrast.ratio >= 4.5, `${id}: hovered long option contrast should be at least 4.5:1: ${JSON.stringify(longContrast)}`)
        record.longOption = { ...longMetrics, contrast: longContrast }
      }
      await saveEvidence(page, { suite, evidenceDir, id, state: 'popup', record })
      record.normal = normal
      record.hover = hovered
      record.focus = focused
      record.popup = popup
      record.triggerTextContrast = triggerContrast
      record.rows = rowMetrics
      record.selectedContrast = selectedContrast
      await page.keyboard.press('Escape')
      await popper.waitFor({ state: 'hidden' })
    }
    assert.deepEqual(await selectSnapshot(select), beforeValue, `${id}: presentation check must preserve selected/search input values`)
    assert.equal(getWriteCount(), beforeWrites, `${id}: presentation check must not write fixture state`)
    record.writesAfter = getWriteCount()
    record.status = 'PASS'
    saveJson(evidenceDir, record)
  } catch (error) {
    record.status = 'FAIL'
    record.failure = { message: error.message, stack: error.stack }
    saveJson(evidenceDir, record)
    throw error
  } finally {
    await restoreScrollPositions(page, beforeScroll).catch(() => {})
    await beforeFocus.evaluate((element) => { if (element?.isConnected && typeof element.focus === 'function') element.focus({ preventScroll: true }) }).catch(() => {})
    await beforeFocus.dispose().catch(() => {})
  }
}

export async function inspectNativeSelect({ page, suite, evidenceDir, id, select, getWriteCount = () => 0 }) {
  const viewport = page.viewportSize()
  const beforeWrites = getWriteCount()
  const beforeValue = await select.inputValue()
  const beforeFocus = await page.evaluateHandle(() => document.activeElement)
  const beforeScroll = await readScrollPositions(page)
  const record = { suite, id, route: new URL(page.url()).pathname, viewport, writesBefore: beforeWrites, screenshots: [] }
  try {
    await select.scrollIntoViewIfNeeded()
    await page.evaluate(() => document.activeElement?.blur?.())
    await page.waitForTimeout(180)
    const metrics = await select.evaluate((node) => {
      const rect = node.getBoundingClientRect()
      const style = getComputedStyle(node)
      return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, radius: Number.parseFloat(style.borderTopLeftRadius), fontSize: style.fontSize, boxShadow: style.boxShadow, disabled: node.disabled }
    })
    const expectedFontSize = viewport.width <= 600 ? '16px' : '13px'
    assert.ok(metrics.height >= 44, `${id}: native select should be at least 44px high: ${JSON.stringify(metrics)}`)
    assert.ok(Math.abs(metrics.radius - 10) < 0.1, `${id}: native select should use 10px radius: ${JSON.stringify(metrics)}`)
    assert.equal(metrics.fontSize, expectedFontSize, `${id}: native select font should match viewport`)
    if (!metrics.disabled) {
      record.triggerTextContrast = await contrastFor(select)
      assert.ok(record.triggerTextContrast.ratio >= 4.5, `${id}: native select text contrast should be at least 4.5:1: ${JSON.stringify(record.triggerTextContrast)}`)
    }
    await saveEvidence(page, { suite, evidenceDir, id, state: 'native-closed', record })
    await select.evaluate((node) => node.focus({ preventScroll: true }))
    await page.waitForTimeout(180)
    const focused = await select.evaluate((node) => ({ focused: node === document.activeElement, boxShadow: getComputedStyle(node).boxShadow }))
    assert.equal(focused.focused, true, `${id}: native select should accept focus without opening its menu`)
    assert.notEqual(focused.boxShadow, metrics.boxShadow, `${id}: native select should visibly change its focus shadow`)
    await saveEvidence(page, { suite, evidenceDir, id, state: 'native-focus', record })
    assert.equal(await select.inputValue(), beforeValue, `${id}: focus measurement must preserve native selection`)
    assert.equal(getWriteCount(), beforeWrites, `${id}: native measurement must remain read only`)
    record.metrics = metrics
    record.focus = focused
    record.value = beforeValue
    record.writesAfter = getWriteCount()
    record.status = 'PASS'
    saveJson(evidenceDir, record)
  } catch (error) {
    record.status = 'FAIL'
    record.failure = { message: error.message, stack: error.stack }
    saveJson(evidenceDir, record)
    throw error
  } finally {
    await restoreScrollPositions(page, beforeScroll).catch(() => {})
    await beforeFocus.evaluate((element) => { if (element?.isConnected && typeof element.focus === 'function') element.focus({ preventScroll: true }) }).catch(() => {})
    await beforeFocus.dispose().catch(() => {})
  }
}

export async function inspectDropdownMenu({ page, suite, evidenceDir, id, trigger, getWriteCount = () => 0 }) {
  const viewport = page.viewportSize()
  const beforeWrites = getWriteCount()
  const beforeFocus = await page.evaluateHandle(() => document.activeElement)
  const beforeScroll = await readScrollPositions(page)
  const record = { suite, id, route: new URL(page.url()).pathname, viewport, writesBefore: beforeWrites, screenshots: [] }
  try {
    await waitForClosedMenus(page)
    assert.equal(await page.locator('.el-select__popper:visible, .el-dropdown__popper:visible').count(), 0,
      `${id}: presentation inspection must start with selection menus closed`)
    await trigger.scrollIntoViewIfNeeded()
    await trigger.hover()
    await saveEvidence(page, { suite, evidenceDir, id, state: 'dropdown-trigger-hover', record })
    await trigger.click()
    const popper = page.locator('.el-dropdown__popper:visible').last()
    await popper.waitFor({ state: 'visible' })
    await waitForPopupAnimation(popper)
    const panel = await popper.evaluate((node) => {
      const rect = node.getBoundingClientRect()
      const style = getComputedStyle(node)
      return { x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom, radius: Number.parseFloat(style.borderTopLeftRadius) }
    })
    assert.ok(Math.abs(panel.radius - 12) < 0.1, `${id}: dropdown menu should use 12px radius: ${JSON.stringify(panel)}`)
    assert.ok(panel.x >= -1 && panel.right <= viewport.width + 1 && panel.y >= -1 && panel.bottom <= viewport.height + 1,
      `${id}: dropdown should stay inside the real viewport: ${JSON.stringify(panel)}`)
    const rows = popper.locator('.el-dropdown-menu__item:visible')
    assert.ok(await rows.count(), `${id}: dropdown should expose actual menu items`)
    const rowMetrics = await rows.evaluateAll((nodes) => nodes.map((node) => {
      const rect = node.getBoundingClientRect()
      return { text: node.textContent.trim(), height: rect.height, x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom, disabled: node.classList.contains('is-disabled') }
    }))
    for (const row of rowMetrics) assert.ok(row.height >= 44, `${id}: dropdown item should be at least 44px high: ${JSON.stringify(row)}`)
    const enabled = popper.locator('.el-dropdown-menu__item:not(.is-disabled):visible').first()
    await enabled.hover()
    const contrast = await contrastFor(enabled)
    assert.ok(contrast.ratio >= 4.5, `${id}: hovered dropdown item contrast should be at least 4.5:1: ${JSON.stringify(contrast)}`)
    record.panel = panel
    record.rows = rowMetrics
    record.hoveredContrast = contrast
    await saveEvidence(page, { suite, evidenceDir, id, state: 'dropdown-popup-hover', record })
    await page.keyboard.press('Escape')
    await popper.waitFor({ state: 'hidden' })
    assert.equal(getWriteCount(), beforeWrites, `${id}: read-only dropdown inspection must not write fixture state`)
    record.writesAfter = getWriteCount()
    record.status = 'PASS'
    saveJson(evidenceDir, record)
  } catch (error) {
    record.status = 'FAIL'
    record.failure = { message: error.message, stack: error.stack }
    saveJson(evidenceDir, record)
    throw error
  } finally {
    await restoreScrollPositions(page, beforeScroll).catch(() => {})
    await beforeFocus.evaluate((element) => { if (element?.isConnected && typeof element.focus === 'function') element.focus({ preventScroll: true }) }).catch(() => {})
    await beforeFocus.dispose().catch(() => {})
  }
}
