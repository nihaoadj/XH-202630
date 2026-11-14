<template>
  <div ref="surface" class="progress-atmosphere" aria-hidden="true">
    <span class="progress-grid-base" />
    <span class="progress-grid-reveal" />
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

const surface = ref(null)
let panel
let motionPreference
let frame = 0
let target = null
let position = null

function paint() {
  frame = 0
  if (!target || !position || !surface.value) return

  position.x += (target.x - position.x) * .3
  position.y += (target.y - position.y) * .3
  surface.value.style.setProperty('--pointer-x', position.x + 'px')
  surface.value.style.setProperty('--pointer-y', position.y + 'px')

  if (Math.hypot(target.x - position.x, target.y - position.y) > .35) {
    frame = requestAnimationFrame(paint)
  }
}

function follow(event) {
  if (!surface.value || event.pointerType === 'touch' || motionPreference?.matches) return

  const bounds = surface.value.getBoundingClientRect()
  target = {
    x: Math.max(0, Math.min(bounds.width, event.clientX - bounds.left)),
    y: Math.max(0, Math.min(bounds.height, event.clientY - bounds.top)),
  }

  if (!position) position = { ...target }
  surface.value.setAttribute('data-pointer', '')
  if (!frame) frame = requestAnimationFrame(paint)
}

function reset() {
  cancelAnimationFrame(frame)
  frame = 0
  target = null
  position = null
  surface.value?.removeAttribute('data-pointer')
}

onMounted(() => {
  panel = surface.value.parentElement
  motionPreference = matchMedia('(prefers-reduced-motion: reduce)')
  panel.addEventListener('pointermove', follow, { passive: true, capture: true })
  panel.addEventListener('pointerleave', reset)
  panel.addEventListener('pointercancel', reset)
  motionPreference.addEventListener('change', reset)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(frame)
  panel?.removeEventListener('pointermove', follow, true)
  panel?.removeEventListener('pointerleave', reset)
  panel?.removeEventListener('pointercancel', reset)
  motionPreference?.removeEventListener('change', reset)
})
</script>

<style scoped>
.progress-atmosphere {
  position:absolute;
  z-index:-1;
  inset:0;
  overflow:hidden;
  border-radius:inherit;
  pointer-events:none;
}
.progress-atmosphere::before,
.progress-atmosphere::after {
  position:absolute;
  inset:0;
  content:'';
}
.progress-atmosphere::before {
  background-image:
    linear-gradient(rgba(116,185,205,.13) 1px,transparent 1px),
    linear-gradient(90deg,rgba(116,185,205,.13) 1px,transparent 1px);
  background-position:center center;
  background-size:24px 24px;
  opacity:.78;
  mask-image:linear-gradient(to bottom,rgba(0,0,0,.62),#000 13%,#000 90%,rgba(0,0,0,.78));
}
.progress-atmosphere::after {
  background-image:
    radial-gradient(circle,rgba(143,243,225,.68) 0 1px,transparent 1.35px),
    radial-gradient(ellipse at center,rgba(111,224,213,.09),transparent 86%),
    linear-gradient(rgba(130,223,218,.38) 1px,transparent 1px),
    linear-gradient(90deg,rgba(130,223,218,.38) 1px,transparent 1px);
  background-position:center center;
  background-size:24px 24px;
  opacity:0;
  mask-image:radial-gradient(ellipse 68px 68px at var(--pointer-x,50%) var(--pointer-y,50%),#000 0%,rgba(0,0,0,.82) 52%,transparent 100%);
  transition:opacity 320ms ease;
}
.progress-atmosphere[data-pointer]::after {
  opacity:.82;
  animation:grid-signal 2.1s ease-in-out infinite alternate;
}
@keyframes grid-signal {
  from { opacity:.42; }
  to { opacity:.9; }
}
@media(prefers-reduced-motion:reduce) {
  .progress-atmosphere::after { display:none; transition:none; animation:none; }
}
</style>
