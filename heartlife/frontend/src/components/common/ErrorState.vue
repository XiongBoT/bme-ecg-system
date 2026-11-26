<script setup lang="ts">
import { AlertCircle, RefreshCw } from 'lucide-vue-next'

withDefaults(
  defineProps<{
    title?: string
    message?: string
    showHomeLink?: boolean
  }>(),
  {
    title: '暂时无法加载，请重试',
    message: '',
    showHomeLink: false,
  }
)

const emit = defineEmits<{
  (e: 'retry'): void
}>()
</script>

<template>
  <div role="alert" class="hl-error-card">
    <div class="hl-error-head">
      <AlertCircle :size="26" class="hl-error-icon" aria-hidden="true" />
      <div>
        <p class="hl-error-title">{{ title }}</p>
        <p v-if="message && message !== title" class="hl-error-msg">{{ message }}</p>
      </div>
    </div>
    <div class="row-wrap">
      <button type="button" class="btn btn-primary btn-sm" @click="emit('retry')">
        <RefreshCw :size="18" aria-hidden="true" />
        <span>重试</span>
      </button>
      <RouterLink v-if="showHomeLink" to="/" class="btn btn-secondary btn-sm">
        返回首页
      </RouterLink>
    </div>
  </div>
</template>

<style scoped>
.hl-error-card {
  background: var(--hl-surface);
  border: 1.5px solid var(--hl-danger);
  border-radius: var(--hl-radius-md);
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.hl-error-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.hl-error-icon {
  color: var(--hl-danger);
  flex-shrink: 0;
  margin-top: 2px;
}

.hl-error-title {
  margin: 0;
  font-size: var(--hl-card-title);
  font-weight: 650;
  color: var(--hl-text);
}

.hl-error-msg {
  margin: 4px 0 0;
  font-size: var(--hl-caption);
  color: var(--hl-text-muted);
}
</style>
