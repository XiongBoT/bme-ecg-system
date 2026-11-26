<script setup lang="ts">
import HlDialog from '../ui/HlDialog.vue'

withDefaults(
  defineProps<{
    open: boolean
    title: string
    description: string
    confirmLabel?: string
    cancelLabel?: string
    danger?: boolean
    loading?: boolean
  }>(),
  {
    confirmLabel: '确认',
    cancelLabel: '取消',
    danger: false,
    loading: false,
  }
)

const emit = defineEmits<{
  (e: 'update:open', val: boolean): void
  (e: 'confirm'): void
}>()
</script>

<template>
  <HlDialog
    :open="open"
    :title="title"
    :description="description"
    max-width="460px"
    @update:open="(v) => emit('update:open', v)"
  >
    <div class="row-wrap" style="justify-content: flex-end; margin-top: 8px">
      <button
        type="button"
        class="btn btn-secondary"
        :disabled="loading"
        @click="emit('update:open', false)"
      >
        {{ cancelLabel }}
      </button>
      <button
        type="button"
        class="btn"
        :class="danger ? 'btn-danger' : 'btn-primary'"
        :disabled="loading"
        @click="emit('confirm')"
      >
        {{ loading ? '处理中...' : confirmLabel }}
      </button>
    </div>
  </HlDialog>
</template>
