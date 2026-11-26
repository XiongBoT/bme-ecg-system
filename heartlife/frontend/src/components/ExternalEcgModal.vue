<script setup lang="ts">
import { ExternalLink, HeartPulse } from 'lucide-vue-next'
import HlDialog from './ui/HlDialog.vue'

defineProps<{
  open: boolean
  url: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()
</script>

<template>
  <HlDialog
    :open="open"
    title="前往独立心电检测工具"
    description="即将前往独立心电检测工具，需独立登录，心伴不会传递您的账号凭据或私密日记。"
    max-width="460px"
    @close="emit('close')"
  >
    <div class="hl-card-soft row-wrap">
      <HeartPulse :size="22" style="color: var(--hl-brand)" aria-hidden="true" />
      <span class="text-sm tabular" style="overflow-wrap: anywhere">{{ url }}</span>
    </div>

    <div class="row-wrap" style="justify-content: flex-end">
      <button type="button" class="btn btn-secondary" @click="emit('close')">
        留在当前页面
      </button>
      <a
        :href="url"
        target="_blank"
        rel="noopener noreferrer"
        class="btn btn-primary"
        @click="emit('close')"
      >
        <span>继续前往</span>
        <ExternalLink :size="18" aria-hidden="true" />
      </a>
    </div>
  </HlDialog>
</template>
