import { nextTick } from 'vue'

const animations = new Map()
const moduleStates = new WeakMap()
const moduleTargets = new WeakMap()
const preference = window.matchMedia('(prefers-reduced-motion: reduce)')

function timing(kind) {
  const style = getComputedStyle(document.documentElement)
  const defaults = { 'page-enter': 260, 'page-exit': 120, 'module-enter': 200, 'fallback-exit': 80 }
  // Production CSS can rewrite milliseconds as seconds; WAAPI expects milliseconds.
  const token = style.getPropertyValue(`--motion-${kind}`).trim()
  const time = /^(\d+(?:\.\d+)?|\.\d+)(ms|s)$/.exec(token)
  const duration = time ? Number(time[1]) * (time[2] === 's' ? 1000 : 1) : defaults[kind]
  return {
    duration,
    easing: style.getPropertyValue('--motion-ease').trim() || 'cubic-bezier(.22,1,.36,1)',
    fill: 'both',
  }
}

function cancelElement(element) {
  animations.get(element)?.cancel()
  animations.delete(element)
  element?.removeAttribute('data-motion-running')
}

function animateElement(element, frames, kind, label) {
  if (!element?.animate || preference.matches) return null
  cancelElement(element)
  try {
    const animation = element.animate(frames, timing(kind))
    animations.set(element, animation)
    element.dataset.motionRunning = label
    const clean = () => {
      if (animations.get(element) !== animation) return
      animations.delete(element)
      element.removeAttribute('data-motion-running')
      animation.cancel() // Remove fill without leaving a permanent compositing layer.
    }
    animation.finished.then(clean, clean)
    return animation
  } catch {
    return null // Motion is optional; the selected content stays visible.
  }
}

function descriptor(value) {
  return typeof value === 'object' && value !== null
    ? { key: value.key, ready: value.ready !== false, order: value.order, slideTarget: value.slideTarget, appear: value.appear === true }
    : { key: value, ready: true }
}

function cancelModule(element) {
  cancelElement(element)
  cancelElement(moduleTargets.get(element))
  moduleTargets.delete(element)
}

function revealModule(element, current, previous) {
  cancelModule(element)
  if (!current.ready || document.documentElement.hasAttribute('data-page-motion')) return
  animateElement(element, [{ opacity: .55 }, { opacity: 1 }], 'module-enter', 'module')
  // Move only the wizard's padded title interior. Moving the outer panel
  // would temporarily overflow its ancestors and invalidate the fit check.
  if (current.slideTarget && Number.isFinite(current.order) && Number.isFinite(previous?.order)) {
    const target = element.querySelector(current.slideTarget)
    if (!target) return
    const offset = current.order < previous.order ? -8 : 8
    moduleTargets.set(element, target)
    animateElement(target, [{ transform: `translateX(${offset}px)` }, { transform: 'translateX(0)' }], 'module-enter', 'module-direction')
  }
}

export const moduleMotion = {
  mounted(element, binding) {
    const current = descriptor(binding.value)
    moduleStates.set(element, current)
    element.setAttribute('data-motion-module', '')
    if (current.appear) revealModule(element, current)
  },
  updated(element, binding) {
    const previous = moduleStates.get(element)
    const current = descriptor(binding.value)
    moduleStates.set(element, current)
    if (!current.ready) { cancelModule(element); return }
    if (previous?.key !== current.key || !previous?.ready) revealModule(element, current, previous)
  },
  beforeUnmount(element) {
    cancelModule(element)
    moduleStates.delete(element)
  },
}

function pageRegion(wholeLayout = false) {
  if (wholeLayout) return document.querySelector('#app')
  return document.querySelector('.content-area') || document.querySelector('#app > *')
}

function layoutKind(route) {
  if (route.meta.authLayout || route.meta.publicLayout) return 'public'
  if (route.name === 'resources' && route.query.focus === '1') return 'focus'
  return 'shell'
}

function changesPage(to, from) {
  // Several public routes share the same LandingView and only switch a
  // teleported account form. Compare resolved components, not route records.
  return from.matched.length > 0 && (
    to.matched.at(-1)?.components?.default !== from.matched.at(-1)?.components?.default
    || layoutKind(to) !== layoutKind(from)
  )
}

// Keep the existing router-view tree. Native snapshots carry the outgoing
// pixels, so the old business component can unmount at the normal commit.
export function installPageMotion(router) {
  let active = null
  let disposed = false

  function nameRegion(transaction, element) {
    if (!element || transaction.regions.has(element)) return
    transaction.regions.set(element, [element.style.getPropertyValue('view-transition-name'), element.style.getPropertyPriority('view-transition-name')])
    element.style.setProperty('view-transition-name', 'app-page')
  }

  function finish(transaction) {
    if (active !== transaction) return
    active = null
    clearTimeout(transaction.watchdog)
    transaction.releaseGuard?.()
    transaction.releaseCommit?.()
    transaction.transition?.skipTransition()
    cancelElement(transaction.outgoing)
    cancelElement(transaction.incoming)
    for (const [element, [value, priority]] of transaction.regions) {
      if (value) element.style.setProperty('view-transition-name', value, priority)
      else element.style.removeProperty('view-transition-name')
    }
    document.documentElement.removeAttribute('data-page-motion')
  }

  const removeGuard = router.beforeResolve((to, from) => {
    if (disposed) return
    // Query-only updates emitted by a newly mounted page must not interrupt
    // its already committed transition or remount a reused component.
    if (!changesPage(to, from)) return
    if (active) finish(active)
    if (preference.matches) return
    const wholeLayout = layoutKind(to) !== 'shell' || layoutKind(from) !== 'shell'
    const outgoing = pageRegion(wholeLayout)
    if (!outgoing) return
    const transaction = { to, outgoing, wholeLayout, regions: new Map(), committed: false }
    active = transaction
    document.documentElement.dataset.pageMotion = 'fallback'

    // Full-layout snapshots suppress hit-testing of their captured controls.
    // Keep focus-mode exit and public overlays live via opacity-only motion.
    if (!wholeLayout && typeof document.startViewTransition === 'function') {
      let releaseGuard
      const guard = new Promise((resolve) => { releaseGuard = resolve })
      transaction.releaseGuard = releaseGuard
      const commit = new Promise((resolve) => { transaction.releaseCommit = resolve })
      nameRegion(transaction, outgoing)
      document.documentElement.dataset.pageMotion = 'native'
      try {
        transaction.transition = document.startViewTransition(() => {
          releaseGuard() // Router commits while this update callback is pending.
          return commit
        })
        transaction.transition.ready.catch(() => {})
        transaction.transition.finished.then(() => finish(transaction), () => finish(transaction))
        // Capture must never block an otherwise valid navigation in a hidden
        // tab or a browser that skips rendering the transition callback.
        transaction.watchdog = setTimeout(() => {
          if (!transaction.committed) finish(transaction)
        }, 180)
        return guard
      } catch {
        finish(transaction)
        active = transaction
        transaction.regions.clear()
        transaction.transition = null
        document.documentElement.dataset.pageMotion = 'fallback'
      }
    }
    // Opacity-only fallback does not create a transform containing block
    // for the page's fixed controls, drawers or courseware overlays.
    const exit = animateElement(outgoing, [{ opacity: 1 }, { opacity: .65 }], 'fallback-exit', 'page-exit')
    // Animation.finished resolves with the Animation itself. A router guard
    // must resolve to void, otherwise Router treats that object as a redirect.
    return exit?.finished.then(() => undefined, () => undefined)
  })

  const removeAfter = router.afterEach(async (to, _from, failure) => {
    const transaction = active
    if (!transaction || transaction.to !== to) return
    if (failure) { finish(transaction); return }
    transaction.committed = true
    clearTimeout(transaction.watchdog)
    await nextTick()
    if (active !== transaction || disposed) return
    transaction.incoming = pageRegion(transaction.wholeLayout)
    if (transaction.transition) {
      nameRegion(transaction, transaction.incoming)
      transaction.releaseCommit()
    } else {
      cancelElement(transaction.outgoing)
      const enter = animateElement(transaction.incoming, [{ opacity: .55 }, { opacity: 1 }], 'page-enter', 'page-enter')
      if (enter) enter.finished.then(() => finish(transaction), () => finish(transaction))
      else finish(transaction)
    }
  })

  const removeError = router.onError(() => { if (active) finish(active) })
  const stopMotion = () => {
    if (active) finish(active)
    for (const element of [...animations.keys()]) cancelElement(element)
  }
  preference.addEventListener('change', stopMotion)
  return () => {
    disposed = true
    stopMotion()
    removeGuard(); removeAfter(); removeError()
    preference.removeEventListener('change', stopMotion)
  }
}
