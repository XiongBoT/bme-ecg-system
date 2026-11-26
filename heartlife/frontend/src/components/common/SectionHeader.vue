<script setup lang="ts">
import { ChevronRight } from 'lucide-vue-next'

defineProps<{
  title: string
  actionTo?: string
  actionLabel?: string
}>()
</script>

<template>
  <div class="row-between" style="margin-bottom: 4px">
    <h2 class="section-title">{{ title }}</h2>
    <slot name="action">
      <RouterLink v-if="actionTo && actionLabel" :to="actionTo" class="hl-section-link">
        <span>{{ actionLabel }}</span>
        <ChevronRight :size="18" aria-hidden="true" />
      </RouterLink>
    </slot>
  </div>
</template>

<style scoped>
.hl-section-link {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  min-height: 44px;
  padding: 4px 8px;
  border-radius: 8px;
  font-size: var(--hl-caption);
  font-weight: 600;
  color: var(--hl-brand);
}

.hl-section-link:hover {
  background: var(--hl-surface-soft);
}
</style>
