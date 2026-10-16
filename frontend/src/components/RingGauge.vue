<template>
  <div class="ring-gauge" :title="detail || label">
    <div class="ring-canvas" :style="{ width: size + 'px', height: size + 'px' }">
      <svg class="ring-svg" viewBox="0 0 100 100" aria-hidden="true">
        <circle
          class="ring-track"
          cx="50" cy="50" :r="radius" :stroke-width="stroke"
        />
        <circle
          class="ring-arc"
          cx="50" cy="50" :r="radius" :stroke-width="stroke"
          :style="{ stroke: color, color: color, strokeDasharray: circumference, strokeDashoffset: offset }"
        />
      </svg>
      <div class="ring-center">
        <span class="ring-value">{{ shown }}<i>%</i></span>
      </div>
    </div>
    <div class="ring-meta">
      <span class="ring-label">{{ label }}</span>
      <span class="ring-detail">{{ detail }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  percent: { type: Number, default: 0 },
  label: { type: String, default: '' },
  detail: { type: String, default: '' },
  color: { type: String, default: 'var(--el-color-primary)' },
  size: { type: Number, default: 96 },
  stroke: { type: Number, default: 8 },
})

const radius = computed(() => 50 - props.stroke / 2 - 1)
const circumference = computed(() => 2 * Math.PI * radius.value)
const clamped = computed(() => Math.max(0, Math.min(100, props.percent || 0)))
const offset = computed(() => circumference.value * (1 - clamped.value / 100))
const shown = computed(() => Math.round(clamped.value))
</script>

<style scoped>
.ring-gauge {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.ring-canvas {
  position: relative;
  border-radius: 50%;
  background: radial-gradient(circle at 50% 26%,
      rgba(255, 255, 255, 0.85), rgba(255, 255, 255, 0.2) 62%, rgba(255, 255, 255, 0) 80%);
  box-shadow:
    inset 0 4px 8px -6px rgba(255, 255, 255, 0.95),
    inset 0 -7px 12px -9px rgba(21, 36, 58, 0.4);
}
html.dark .ring-canvas {
  background: radial-gradient(circle at 50% 26%,
      rgba(255, 255, 255, 0.12), rgba(255, 255, 255, 0.03) 62%, rgba(255, 255, 255, 0) 80%);
  box-shadow:
    inset 0 4px 8px -6px rgba(255, 255, 255, 0.18),
    inset 0 -7px 12px -9px rgba(0, 0, 0, 0.65);
}

.ring-svg {
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
  overflow: visible;
}
.ring-track {
  fill: none;
  stroke: rgba(21, 36, 58, 0.09);
}
html.dark .ring-track { stroke: rgba(255, 255, 255, 0.1); }

.ring-arc {
  fill: none;
  stroke-linecap: round;
  filter: drop-shadow(0 0 4px currentColor);
  transition: stroke-dashoffset 0.7s var(--jelly-squish, cubic-bezier(.34, 1.56, .64, 1)),
    stroke 0.3s ease;
}

.ring-center {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.ring-value {
  font-size: 21px;
  font-weight: 750;
  letter-spacing: -0.6px;
  color: var(--el-text-color-primary);
  line-height: 1;
}
.ring-value i {
  font-style: normal;
  font-size: 11px;
  font-weight: 600;
  margin-left: 1px;
  color: var(--el-text-color-secondary);
}

.ring-meta {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  max-width: 132px;
  text-align: center;
}
.ring-label {
  font-size: 13px;
  font-weight: 650;
  color: var(--el-text-color-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.ring-detail {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

@media (prefers-reduced-motion: reduce) {
  .ring-arc { transition: none; }
}
</style>
