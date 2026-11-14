<template>
  <canvas ref="canvas" class="hero-atmosphere" aria-hidden="true"></canvas>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

const canvas = ref(null)
const circuitTraces = [
  [[.02, .16], [.19, .16], [.225, .07], [.38, .07], [.41, .15], [.49, .15]],
  [[.07, .91], [.22, .91], [.255, .80], [.36, .80], [.395, .91], [.52, .91]],
  [[.30, .29], [.38, .29], [.416, .41], [.53, .41], [.57, .27], [.65, .27]],
  [[.32, .73], [.46, .73], [.494, .61], [.565, .61], [.60, .74], [.68, .74]],
  [[.53, .10], [.69, .10], [.726, .19], [.82, .19], [.86, .07], [.96, .07]],
  [[.80, .33], [.90, .33], [.936, .22], [.99, .22]],
  [[.81, .67], [.89, .67], [.928, .54], [.98, .54]],
  [[.57, .94], [.71, .94], [.748, .83], [.86, .83], [.90, .92], [.98, .92]],
]
const traceLifetime = 820
const gridGap = 28
const waveRadius = 150

let hero
let context
let observer
let motionPreference
let width = 0
let height = 0
let frame = 0
let pointer = null
let wave = null
let lastPulse = null
let pulses = []
let dotColor
let circuitColor

function clearParallax() {
  hero?.style.removeProperty('--hero-x')
  hero?.style.removeProperty('--hero-y')
}

function resize({ width: nextWidth, height: nextHeight }) {
  if (!nextWidth || !nextHeight || !context) return
  width = nextWidth
  height = nextHeight
  const scale = Math.min(window.devicePixelRatio || 1, 2)
  canvas.value.width = Math.round(width * scale)
  canvas.value.height = Math.round(height * scale)
  context.setTransform(scale, 0, 0, scale, 0, 0)

  dotColor = context.createLinearGradient(0, 0, width, 0)
  dotColor.addColorStop(0, '#83a7d32c')
  dotColor.addColorStop(.52, '#9bbfee52')
  dotColor.addColorStop(1, '#8dd6e270')
  circuitColor = context.createLinearGradient(0, 0, width, 0)
  circuitColor.addColorStop(0, '#7198cc28')
  circuitColor.addColorStop(.42, '#719de05e')
  circuitColor.addColorStop(1, '#71c8d477')
  if (!frame) paint(performance.now())
}

function drawCircuits() {
  context.lineWidth = 1
  context.strokeStyle = circuitColor
  context.beginPath()
  for (const trace of circuitTraces) {
    const [start, ...ends] = trace
    context.moveTo(start[0] * width, start[1] * height)
    for (const [x, y] of ends) context.lineTo(x * width, y * height)
  }
  context.stroke()

  context.beginPath()
  for (const trace of circuitTraces) {
    const [startX, startY] = trace[0]
    const [endX, endY] = trace.at(-1)
    context.rect(startX * width - 2, startY * height - 2, 4, 4)
    context.moveTo(endX * width + 3, endY * height)
    context.arc(endX * width, endY * height, 3, 0, Math.PI * 2)
  }
  context.stroke()
}

function drawGrid(now, strength) {
  const dots = new Path2D()
  const highlighted = new Path2D()
  const mesh = new Path2D()
  for (let y = 12; y < height; y += gridGap) {
    let previous
    for (let x = 12; x < width; x += gridGap) {
      const distance = wave ? Math.hypot(x - wave.x, y - wave.y) : waveRadius
      const influence = Math.max(0, 1 - distance / waveRadius) ** 2 * strength
      const lift = Math.cos(distance / 16 - now / 80) * influence * 22
      const raisedY = y + lift
      dots.rect(x, raisedY, 1.4, 1.4)
      if (influence > .06) {
        highlighted.rect(x - 1, raisedY - 1, 3, 3)
        if (previous) {
          mesh.moveTo(previous.x, previous.y)
          mesh.lineTo(x, raisedY)
        }
        previous = { x, y: raisedY }
      } else {
        previous = null
      }
    }
  }
  context.fillStyle = dotColor
  context.fill(dots)
  context.strokeStyle = 'rgba(102, 202, 233, ' + strength * .38 + ')'
  context.stroke(mesh)
  context.fillStyle = 'rgba(151, 241, 236, ' + strength * .76 + ')'
  context.fill(highlighted)
}

function drawPulses(now) {
  for (const pulse of pulses) {
    const progress = Math.max(0, now - pulse.time) / traceLifetime
    const intensity = (1 - progress) ** 2
    context.strokeStyle = 'rgba(124, 235, 229, ' + intensity * .62 + ')'
    context.beginPath()
    context.setLineDash([2, 4])
    context.arc(pulse.x, pulse.y, 7 + progress * 54, 0, Math.PI * 2)
    context.stroke()
    context.setLineDash([])

    context.beginPath()
    for (let index = 0; index < 5; index++) {
      const angle = pulse.angle + (index - 2) * .46 + Math.PI
      const distance = 8 + progress * (24 + index * 7)
      const x = Math.cos(angle)
      const y = Math.sin(angle)
      context.moveTo(pulse.x + x * distance, pulse.y + y * distance)
      context.lineTo(pulse.x + x * (distance + 5), pulse.y + y * (distance + 5))
    }
    context.stroke()
  }
}

function paint(now) {
  frame = 0
  if (!width || !height) return
  if (pointer && now - pointer.time >= traceLifetime) {
    pointer = null
    wave = null
    leave()
  }
  if (pointer) {
    wave.x += (pointer.x - wave.x) * .24
    wave.y += (pointer.y - wave.y) * .24
  }
  const strength = pointer ? (1 - Math.max(0, now - pointer.time) / traceLifetime) ** 2 : 0
  pulses = pulses.filter(pulse => now - pulse.time < traceLifetime)
  context.clearRect(0, 0, width, height)
  drawCircuits()
  drawGrid(now, strength)
  drawPulses(now)
  if (pointer || pulses.length) frame = requestAnimationFrame(paint)
}

function followPointer(event) {
  if (event.pointerType === 'touch' || motionPreference.matches || !width) return
  const bounds = canvas.value.getBoundingClientRect()
  if (!bounds.width || !bounds.height) return
  const x = (event.clientX - bounds.left) / bounds.width * width
  const y = (event.clientY - bounds.top) / bounds.height * height
  const time = performance.now()
  if (!wave) wave = { x, y }
  pointer = { x, y, time }

  if (!lastPulse || Math.hypot(x - lastPulse.x, y - lastPulse.y) >= 26) {
    const angle = lastPulse ? Math.atan2(y - lastPulse.y, x - lastPulse.x) : 0
    lastPulse = { x, y }
    pulses.push({ x, y, angle, time })
    if (pulses.length > 12) pulses.shift()
  }
  hero.style.setProperty('--hero-x', (x / width * 2 - 1).toFixed(3))
  hero.style.setProperty('--hero-y', (y / height * 2 - 1).toFixed(3))
  if (!frame) frame = requestAnimationFrame(paint)
}

function leave() {
  lastPulse = null
  clearParallax()
}

function stopMotion() {
  cancelAnimationFrame(frame)
  pointer = null
  wave = null
  pulses = []
  leave()
  paint(performance.now())
}

onMounted(() => {
  context = canvas.value.getContext('2d')
  if (!context) return
  hero = canvas.value.parentElement
  motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)')
  motionPreference.addEventListener('change', stopMotion)
  hero.addEventListener('pointermove', followPointer, { passive: true })
  hero.addEventListener('pointerleave', leave)
  hero.addEventListener('pointercancel', leave)
  observer = new ResizeObserver(([entry]) => resize(entry.contentRect))
  observer.observe(canvas.value)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(frame)
  observer?.disconnect()
  motionPreference?.removeEventListener('change', stopMotion)
  hero?.removeEventListener('pointermove', followPointer)
  hero?.removeEventListener('pointerleave', leave)
  hero?.removeEventListener('pointercancel', leave)
  clearParallax()
})
</script>

<style scoped>
.hero-atmosphere {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
</style>
