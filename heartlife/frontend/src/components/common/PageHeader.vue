<script setup lang="ts">
import { ChevronLeft } from 'lucide-vue-next'

defineProps<{
  title: string
  subtitle?: string
  backTo?: string
  backLabel?: string
}>()
</script>

<template>
  <header class="hl-page-header">
    <div v-if="backTo" class="hl-back-row">
      <RouterLink :to="backTo" class="hl-back-link">
        <ChevronLeft :size="20" aria-hidden="true" />
        <span>{{ backLabel || '返回上一页' }}</span>
      </RouterLink>
    </div>
    <div class="hl-header-main">
      <div class="hl-header-titles">
        <h1 class="page-title">{{ title }}</h1>
        <p v-if="subtitle" class="hl-page-subtitle">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="hl-header-actions">
        <slot name="actions" />
      </div>
    </div>
  </header>
</template>

<style scoped>
.hl-page-header {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 24px;
}

.hl-back-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 44px;
  font-size: var(--hl-caption);
  font-weight: 600;
  color: var(--hl-brand);
}

.hl-header-main {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.hl-header-titles {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  flex: 1 1 260px;
}

.hl-page-subtitle {
  margin: 0;
  font-size: var(--hl-body);
  color: var(--hl-text-muted);
  line-height: 1.55;
}

.hl-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
</style>
