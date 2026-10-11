import { nextTick, onBeforeUnmount, onMounted, watch } from 'vue'

/** Keep viewport measurement and its observers in the original component lifecycle. */
export function useProductionLayout({
  productionPage,
  processScroll,
  resourceScroll,
  isFitLayout,
  coursewareComposerVisible,
  selectedJob,
  selectedRunId,
  selectedResourceId,
  selectedLearnerId,
  loadingJobs,
  loadingResources,
  selectedTask,
  resources,
  learningDirectionName,
}) {
  let productionObserver = null
  let productionContentObserver = null
  let productionFrame = null
  let productionMounted = false
  let productionMeasureVersion = 0

  function scheduleProductionLayout() {
    if (!productionMounted) return
    if (productionFrame != null) cancelAnimationFrame(productionFrame)
    productionFrame = requestAnimationFrame(async () => {
      productionFrame = null
      const version = ++productionMeasureVersion
      const root = productionPage.value
      if (!root) return
      root.querySelectorAll('.generation-grid > .process-panel, .details-scroll').forEach((region, index) => {
        region.setAttribute('tabindex', '0')
        region.setAttribute('role', 'region')
        region.setAttribute('aria-label', index === 0 ? '课件生成过程' : '课件过程详情')
      })
      const area = root.closest('.content-area')
      const candidate = window.innerWidth >= 1100 && window.innerHeight >= 640
        && !(coursewareComposerVisible.value && selectedJob.value)
      isFitLayout.value = candidate
      await nextTick()
      if (!productionMounted || version !== productionMeasureVersion || !candidate) return
      const regions = [...root.querySelectorAll('.process-scroll, .resource-stage, .generation-grid > .process-panel, .details-scroll')]
      const fixed = [...root.querySelectorAll('.control-panel, .production-footer, .studio-grid > div > .panel-title, .generation-grid .panel-title, .resource-toolbar')]
      const bounds = root.getBoundingClientRect()
      const fits = area && root.scrollHeight <= root.clientHeight + 1
        && bounds.bottom <= area.getBoundingClientRect().bottom + 1
        && regions.every(region => region.clientHeight >= 120 && region.scrollWidth <= region.clientWidth + 1)
        && fixed.every(item => item.scrollHeight <= item.clientHeight + 1 && item.scrollWidth <= item.clientWidth + 1)
      isFitLayout.value = Boolean(fits)
    })
  }

  watch([selectedRunId, selectedResourceId, selectedLearnerId, loadingJobs, loadingResources, coursewareComposerVisible,
    () => selectedTask.value?.job_status, () => selectedTask.value?.error_message, () => resources.value.length,
    learningDirectionName], scheduleProductionLayout, { flush: 'post' })
  watch(selectedRunId, async () => { await nextTick(); processScroll.value?.scrollTo(0, 0); resourceScroll.value?.scrollTo(0, 0) }, { flush: 'post' })
  watch(selectedResourceId, async () => { await nextTick(); resourceScroll.value?.scrollTo(0, 0) }, { flush: 'post' })
  onMounted(() => {
    productionMounted = true
    productionObserver = new ResizeObserver(scheduleProductionLayout)
    productionObserver.observe(productionPage.value.closest('.content-area'), { box: 'border-box' })
    productionContentObserver = new MutationObserver(scheduleProductionLayout)
    productionContentObserver.observe(productionPage.value, { childList: true, subtree: true })
    window.addEventListener('resize', scheduleProductionLayout)
    scheduleProductionLayout()
  })
  onBeforeUnmount(() => {
    productionMounted = false
    productionMeasureVersion += 1
    productionObserver?.disconnect()
    productionContentObserver?.disconnect()
    if (productionFrame != null) cancelAnimationFrame(productionFrame)
    window.removeEventListener('resize', scheduleProductionLayout)
  })
}
