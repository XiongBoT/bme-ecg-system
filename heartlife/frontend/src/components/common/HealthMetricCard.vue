<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    label: string
    value?: number | string | null
    unit?: string
    emptyText?: string
    subtext?: string
    tone?: 'default' | 'soft' | 'accent'
  }>(),
  {
    value: null,
    unit: '',
    emptyText: '尚未记录',
    subtext: '',
    tone: 'default',
  }
)

const isMissing = computed(
  () => props.value === null || props.value === undefined || props.value === ''
)

const cardToneClass = computed(() => {
  if (props.tone === 'soft') return 'hl-card-soft'
  if (props.tone === 'accent') return 'hl-card-accent'
  return 'hl-card'
})
</script>

<template>
  <div :class="[cardToneClass, 'hl-metric-card']">
    <div class="hl-metric-head">
      <span v-if="$slots.icon" class="hl-metric-icon" aria-hidden="true">
        <slot name="icon" />
      </span>
      <span class="hl-metric-label">{{ label }}</span>
    </div>

    <div v-if="isMissing" class="hl-metric-empty">{{ emptyText }}</div>
    <div v-else class="hl-metric-number tabular">
      <span>{{ value }}</span>
      <span v-if="unit" class="hl-metric-unit">{{ unit }}</span>
    </div>

    <p v-if="subtext" class="hl-metric-sub tabular">{{ subtext }}</p>
    <div v-if="$slots.footer" class="hl-metric-footer">
      <slot name="footer" />
    </div>
  </div>
</template>

<style scoped>
.hl-metric-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.hl-metric-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.hl-metric-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: var(--hl-surface-soft);
  color: var(--hl-brand);
  flex-shrink: 0;
}

.hl-metric-label {
  font-size: var(--hl-caption);
  font-weight: 600;
  color: var(--hl-text-muted);
}

.hl-metric-number {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: var(--hl-metric);
  font-weight: 750;
  line-height: 1.2;
  color: var(--hl-text);
}

.hl-metric-unit {
  font-size: var(--hl-body);
  font-weight: 600;
  color: var(--hl-text-muted);
}

.hl-metric-empty {
  font-size: var(--hl-card-title);
  font-weight: 650;
  color: var(--hl-text-muted);
  padding: 4px 0;
}

.hl-metric-sub {
  margin: 0;
  font-size: var(--hl-caption);
  color: var(--hl-text-muted);
}

.hl-metric-footer {
  margin-top: auto;
  padding-top: 4px;
}
</style>
