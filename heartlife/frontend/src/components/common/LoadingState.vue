<script setup lang="ts">
import { RefreshCw } from 'lucide-vue-next'
import HlSkeleton from '../ui/HlSkeleton.vue'

withDefaults(
  defineProps<{
    count?: number
    slow?: boolean
    timedOut?: boolean
  }>(),
  {
    count: 3,
    slow: false,
    timedOut: false,
  }
)

const emit = defineEmits<{
  (e: 'retry'): void
}>()
</script>

<template>
  <div role="status" aria-live="polite" class="stack">
    <span class="sr-only">正在加载</span>

    <div v-if="timedOut" class="hl-card-accent stack-sm">
      <p style="margin: 0; font-weight: 650">加载时间较长，可能网络连接不稳定</p>
      <div class="row-wrap">
        <button type="button" class="btn btn-primary btn-sm" @click="emit('retry')">
          <RefreshCw :size="18" aria-hidden="true" />
          <span>重试</span>
        </button>
        <RouterLink to="/" class="btn btn-secondary btn-sm">返回首页</RouterLink>
      </div>
    </div>
    <div v-else-if="slow" class="hl-card-soft">
      <span class="text-sm">加载时间较长，请稍候...</span>
    </div>

    <div v-for="n in Math.min(3, count)" :key="n" class="hl-card stack-sm" aria-hidden="true">
      <div class="row-wrap">
        <HlSkeleton class="hl-sk-avatar" />
        <div class="stack-sm" style="flex: 1">
          <HlSkeleton class="hl-sk-line-short" />
          <HlSkeleton class="hl-sk-line-tiny" />
        </div>
      </div>
      <HlSkeleton class="hl-sk-title" />
      <HlSkeleton class="hl-sk-body" />
    </div>
  </div>
</template>

<style scoped>
.hl-sk-avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
}

.hl-sk-line-short {
  width: 140px;
  height: 18px;
}

.hl-sk-line-tiny {
  width: 96px;
  height: 14px;
}

.hl-sk-title {
  width: 72%;
  height: 24px;
}

.hl-sk-body {
  width: 100%;
  height: 54px;
}
</style>
