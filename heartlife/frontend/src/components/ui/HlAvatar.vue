<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    name?: string | null
    size?: 'sm' | 'md' | 'lg'
  }>(),
  {
    name: '心',
    size: 'md',
  }
)

const PALETTE = [
  { bg: '#E8F1E7', fg: '#20533F', border: '#BDD2BC' },
  { bg: '#F8E9DB', fg: '#85451F', border: '#E4C5A8' },
  { bg: '#E4EFEA', fg: '#1F5647', border: '#B6D1C6' },
  { bg: '#F3ECE2', fg: '#6E4726', border: '#DAC8B2' },
]

const initial = computed(() => {
  const raw = (props.name || '').replace(/^【演示】/, '').trim()
  if (!raw) return '心'
  return Array.from(raw)[0] || '心'
})

const tone = computed(() => {
  const s = props.name || '心'
  let hash = 0
  for (let i = 0; i < s.length; i++) {
    hash = (hash * 31 + s.charCodeAt(i)) >>> 0
  }
  return PALETTE[hash % PALETTE.length]
})

const sizePx = computed(() => {
  if (props.size === 'sm') return '40px'
  if (props.size === 'lg') return '56px'
  return '48px'
})
</script>

<template>
  <span
    class="hl-avatar"
    aria-hidden="true"
    :style="{
      width: sizePx,
      height: sizePx,
      backgroundColor: tone.bg,
      color: tone.fg,
      borderColor: tone.border,
    }"
  >
    {{ initial }}
  </span>
</template>

<style scoped>
.hl-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border-radius: 50%;
  border: 1.5px solid;
  font-weight: 700;
  font-size: 1.125rem;
  line-height: 1;
  user-select: none;
}
</style>
