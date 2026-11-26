<script setup lang="ts">
import {
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'
import { X } from 'lucide-vue-next'

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    description?: string
    maxWidth?: string
  }>(),
  {
    description: '',
    maxWidth: '540px',
  }
)

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'close'): void
}>()

const isTestEnv = import.meta.env.MODE === 'test'

function handleOpenChange(val: boolean) {
  emit('update:open', val)
  if (!val) {
    emit('close')
  }
}
</script>

<template>
  <DialogRoot :open="props.open" @update:open="handleOpenChange">
    <DialogPortal :disabled="isTestEnv">
      <DialogOverlay class="hl-dialog-overlay" />
      <DialogContent class="hl-dialog-content" :style="{ maxWidth: props.maxWidth }">
        <div class="hl-dialog-header">
          <div>
            <DialogTitle class="hl-dialog-title">{{ props.title }}</DialogTitle>
            <DialogDescription v-if="props.description" class="hl-dialog-desc">
              {{ props.description }}
            </DialogDescription>
            <DialogDescription v-else class="sr-only">
              {{ props.title }}对话框，按 Esc 键可关闭
            </DialogDescription>
          </div>
          <DialogClose as-child>
            <button type="button" class="hl-dialog-close" aria-label="关闭弹窗">
              <X :size="22" aria-hidden="true" />
            </button>
          </DialogClose>
        </div>
        <div class="hl-dialog-body">
          <slot />
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>

<style>
.hl-dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 220;
  background: rgb(28 42 35 / 0.48);
}

.hl-dialog-content {
  position: fixed;
  top: 50%;
  left: 50%;
  z-index: 230;
  transform: translate(-50%, -50%);
  width: calc(100vw - 32px);
  max-height: 90vh;
  overflow-y: auto;
  background: var(--hl-surface);
  color: var(--hl-text);
  border: 1.5px solid var(--hl-border);
  border-radius: var(--hl-radius-md);
  box-shadow: var(--hl-shadow-modal);
  padding: 24px;
}

.hl-dialog-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.hl-dialog-title {
  margin: 0;
  font-size: var(--hl-heading);
  line-height: 1.35;
  font-weight: 700;
  color: var(--hl-text);
}

.hl-dialog-desc {
  margin: 6px 0 0;
  font-size: var(--hl-caption);
  color: var(--hl-text-muted);
}

.hl-dialog-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: var(--hl-target);
  min-height: var(--hl-target);
  border-radius: var(--hl-radius-sm);
  border: 1px solid var(--hl-border);
  background: var(--hl-surface);
  color: var(--hl-text);
  cursor: pointer;
  flex-shrink: 0;
}

.hl-dialog-close:hover {
  background: var(--hl-surface-soft);
  border-color: var(--hl-brand);
  color: var(--hl-brand);
}

.hl-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
