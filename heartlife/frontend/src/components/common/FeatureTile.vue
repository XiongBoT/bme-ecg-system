<script setup lang="ts">
import { ChevronRight } from 'lucide-vue-next'

defineProps<{
  title: string
  description?: string
  to?: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'click'): void
}>()
</script>

<template>
  <RouterLink v-if="to" :to="to" class="hl-feature-tile">
    <span v-if="$slots.icon" class="hl-tile-icon" aria-hidden="true">
      <slot name="icon" />
    </span>
    <span class="hl-tile-body">
      <strong class="hl-tile-title">{{ title }}</strong>
      <span v-if="description" class="hl-tile-desc">{{ description }}</span>
    </span>
    <ChevronRight :size="20" class="hl-tile-arrow" aria-hidden="true" />
  </RouterLink>

  <button
    v-else
    type="button"
    class="hl-feature-tile"
    :disabled="disabled"
    @click="emit('click')"
  >
    <span v-if="$slots.icon" class="hl-tile-icon" aria-hidden="true">
      <slot name="icon" />
    </span>
    <span class="hl-tile-body">
      <strong class="hl-tile-title">{{ title }}</strong>
      <span v-if="description" class="hl-tile-desc">{{ description }}</span>
    </span>
    <ChevronRight :size="20" class="hl-tile-arrow" aria-hidden="true" />
  </button>
</template>

<style scoped>
.hl-feature-tile {
  width: 100%;
  min-height: 64px;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  border-radius: var(--hl-radius-md);
  border: 1.5px solid var(--hl-border);
  background: var(--hl-surface);
  color: var(--hl-text);
  text-align: left;
  font-family: inherit;
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}

.hl-feature-tile:hover:not(:disabled) {
  background: var(--hl-surface-soft);
  border-color: var(--hl-brand);
}

.hl-feature-tile:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.hl-tile-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--hl-surface-soft);
  color: var(--hl-brand);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.hl-tile-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex: 1;
  min-width: 0;
}

.hl-tile-title {
  font-size: var(--hl-body);
  font-weight: 650;
  color: var(--hl-text);
}

.hl-tile-desc {
  font-size: var(--hl-caption);
  color: var(--hl-text-muted);
}

.hl-tile-arrow {
  color: var(--hl-text-muted);
  flex-shrink: 0;
}
</style>
