import { ref } from 'vue'

/**
 * Own only selected-task resources and node tiers. The page supplies identity,
 * API reads and notifications; selection, jobs and subscription cleanup stay there.
 */
export function useGenerationResources({ getContext, isMounted, listNodes, listRunResources, listLibraryResources, messages }) {
  const resources = ref([])
  const nodeTiers = ref({})
  const loadingResources = ref(false)
  const resourcesLoaded = ref(false)
  const selectedResourceId = ref('')
  let resourcesRequestVersion = 0
  let nodeTiersRequestVersion = 0

  function invalidateResources() { ++resourcesRequestVersion }
  function invalidateNodeTiers() { ++nodeTiersRequestVersion }

  function resourceTierLabel(resource) {
    const tiers = [...new Set((resource?.knowledge_points || [])
      .map(point => nodeTiers.value[String(point || '').trim()])
      .filter(tier => Number.isInteger(tier)))]
    return tiers.length ? tiers.map(tier => `第 ${tier} 阶`).join('、') : ''
  }

  async function loadNodeTiers() {
    const version = ++nodeTiersRequestVersion
    const { learnerId, knowledgeBaseId } = getContext()
    const isCurrent = () => isMounted() && version === nodeTiersRequestVersion
      && learnerId === getContext().learnerId && knowledgeBaseId === getContext().knowledgeBaseId
    if (!knowledgeBaseId) {
      nodeTiers.value = {}
      return
    }
    try {
      const response = await listNodes(knowledgeBaseId)
      if (!isCurrent()) return
      nodeTiers.value = Object.fromEntries((response.data?.nodes || response.data || [])
        .map(node => [node.node_id, node.tier])
        .filter(([, tier]) => Number.isInteger(tier)))
    } catch (error) {
      if (!isCurrent()) return
      nodeTiers.value = {}
      console.warn('学习节点阶级加载失败，标题将隐藏阶级信息', error)
    }
  }

  async function loadResourcesForSelectedJob() {
    const version = ++resourcesRequestVersion
    const { learnerId, textRunId: runId } = getContext()
    const isCurrent = () => isMounted() && version === resourcesRequestVersion
      && learnerId === getContext().learnerId && runId === getContext().textRunId
    if (!learnerId || !runId) {
      resources.value = []
      resourcesLoaded.value = true
      selectedResourceId.value = ''
      return
    }
    loadingResources.value = true
    const collected = []
    function applyCollectedResources() {
      resources.value = collected
      resourcesLoaded.value = true
      if (!resources.value.length) selectedResourceId.value = ''
      else if (!resources.value.some(item => item.resource_id === selectedResourceId.value)) selectedResourceId.value = resources.value[0].resource_id
    }
    try {
      await loadNodeTiers()
      if (!isCurrent()) return
      const pageSize = 100
      const seen = new Set()
      let maxPages = 1
      let page = 1
      let hasNext = false
      while (true) {
        const response = await listRunResources(learnerId, { run_id: runId, page, page_size: pageSize })
        if (!isCurrent()) return
        const items = response.data.resources || []
        if (page === 1) {
          // The first response owns the denominator for this run; never chase an
          // ever-growing total on later pages.
          const total = Number(response.data.total ?? items.length) || 0
          maxPages = Math.max(1, Math.ceil(total / pageSize))
        }
        for (const item of items) {
          if (seen.has(item.resource_id)) continue
          seen.add(item.resource_id)
          collected.push({ ...item, tier_label: item.tier_label || resourceTierLabel(item) })
        }
        hasNext = Boolean(response.data.has_next)
        if (!hasNext || !items.length || page >= maxPages) break
        page += 1
      }
      applyCollectedResources()
      if (hasNext && page >= maxPages) {
        // Keep the readable results already fetched; the authoritative summary is
        // never recomputed from a partial page.
        messages.warning('资源较多，已显示前部分已发布内容，可刷新查看全部')
      }
    } catch (error) {
      if (!isCurrent()) return
      console.error(error)
      if (collected.length) {
        applyCollectedResources()
        messages.warning('已加载部分已发布资源，后续页面加载失败，可刷新重试')
      } else {
        messages.error(error?.response?.data?.message || '资源列表加载失败')
      }
    } finally {
      if (isCurrent()) loadingResources.value = false
    }
  }

  async function loadCoursewareSourceResources() {
    const version = ++resourcesRequestVersion
    const { learnerId, runId, sourceBatchId: batchId } = getContext()
    const isCurrent = () => isMounted() && version === resourcesRequestVersion
      && learnerId === getContext().learnerId && runId === getContext().runId
    if (!learnerId || !batchId) {
      resources.value = []
      resourcesLoaded.value = true
      return
    }
    loadingResources.value = true
    try {
      await loadNodeTiers()
      if (!isCurrent()) return
      const response = await listLibraryResources(learnerId)
      if (!isCurrent()) return
      resources.value = (response.data || []).filter(resource => (
        resource.resource_kind !== 'interactive_courseware' && resource.batch_id === batchId
      )).map(resource => ({ ...resource, tier_label: resource.tier_label || resourceTierLabel(resource) }))
      resourcesLoaded.value = true
    } catch (error) {
      if (!isCurrent()) return
      console.error(error)
      resources.value = []
      resourcesLoaded.value = true
      messages.error(error?.response?.data?.message || '课件来源资源加载失败')
    } finally {
      if (isCurrent()) loadingResources.value = false
    }
  }

  return {
    resources, nodeTiers, loadingResources, resourcesLoaded, selectedResourceId,
    resourceTierLabel, loadNodeTiers, loadResourcesForSelectedJob, loadCoursewareSourceResources,
    invalidateResources, invalidateNodeTiers,
  }
}
