const PUBLISHED = 'published'
const APPROVED = 'approved'

export function normalizeRepresentation(resource) {
  if (resource?.representation === 'html') return 'html'
  return 'text'
}

export function resourcePublicationStatus(resource) {
  return String(resource?.publication_status || '').toLowerCase()
}

export function resourceReviewStatus(resource) {
  return String(
    resource?.review_status
      || resource?.resource_status
      || resource?.approval_status
      || '',
  ).toLowerCase()
}

export function isPublishedResource(resource) {
  return resourcePublicationStatus(resource) === PUBLISHED
}

export function isExplicitlyApprovedResource(resource) {
  return resourceReviewStatus(resource) === APPROVED
}

export function isReadableResource(resource) {
  if (!resource || !isPublishedResource(resource)) return false
  const reviewStatus = resourceReviewStatus(resource)
  // Historical published resources did not always project review_status. They
  // remain readable, while every explicit non-approved state stays hidden.
  return !reviewStatus || reviewStatus === APPROVED
}

export function isHtmlPracticeResource(resource) {
  return resource?.resource_type === '实操指南' && normalizeRepresentation(resource) === 'html'
}

export function isHtmlPreviewable(resource) {
  return isHtmlPracticeResource(resource)
    && isPublishedResource(resource)
    && isExplicitlyApprovedResource(resource)
}

function sameVersion(source, html) {
  if (source?.version == null || html?.source_resource_version == null) return false
  return String(source.version) === String(html.source_resource_version)
}

export function canUseInteractivePair(source, html) {
  if (!source || !html || normalizeRepresentation(source) !== 'text') return false
  if (source.resource_type !== '实操指南' || !isHtmlPreviewable(html)) return false
  if (!isReadableResource(source)) return false
  if (!source.resource_family_id || source.resource_family_id !== html.resource_family_id) return false
  if (html.derived_from_resource_id !== source.resource_id) return false
  if (!sameVersion(source, html)) return false
  if (!source.canonical_text_hash || source.canonical_text_hash !== html.canonical_text_hash) return false
  return true
}

function materialKey(resource) {
  if (resource?.resource_type === '实操指南' && resource.resource_family_id) {
    return `family:${resource.resource_family_id}`
  }
  return `resource:${resource?.resource_id || 'unknown'}`
}

export function buildResourceMaterials(resources) {
  const materials = new Map()
  for (const resource of resources || []) {
    if (!isReadableResource(resource)) continue
    const key = materialKey(resource)
    const material = materials.get(key) || {
      key,
      resource_family_id: resource.resource_family_id || null,
      text: null,
      html: null,
    }
    if (normalizeRepresentation(resource) === 'html') material.html = resource
    else material.text = resource
    materials.set(key, material)
  }

  return Array.from(materials.values())
    .filter((material) => material.text)
    .map((material) => ({
      ...material,
      displayResource: material.text,
      interactiveAvailable: canUseInteractivePair(material.text, material.html),
    }))
}

export function unwrapResourceDetail(data, fallback = null) {
  return data?.resource || data?.item || data || fallback
}

export function unwrapHtmlPreview(data) {
  const preview = data?.preview || data || {}
  return {
    ...preview,
    html_fragment: preview.html_fragment || preview.content_text || preview.content || '',
  }
}
