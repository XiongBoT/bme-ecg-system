<script setup lang="ts">
import { SwitchRoot, SwitchThumb } from 'reka-ui'

const props = defineProps<{
  modelValue: boolean
  label: string
  description?: string
  testId?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
}>()
</script>

<template>
  <div class="hl-switch-row">
    <div class="hl-switch-text">
      <span class="hl-switch-label">{{ props.label }}</span>
      <span v-if="props.description" class="hl-switch-desc">{{ props.description }}</span>
    </div>
    <div class="hl-switch-control">
      <span class="hl-switch-state" aria-hidden="true">
        {{ props.modelValue ? '已开启' : '未开启' }}
      </span>
      <SwitchRoot
        :model-value="props.modelValue"
        :aria-label="props.label"
        :data-testid="props.testId"
        class="hl-switch-root"
        @update:model-value="(v) => emit('update:modelValue', Boolean(v))"
      >
        <SwitchThumb class="hl-switch-thumb" />
      </SwitchRoot>
    </div>
  </div>
</template>

<style scoped>
.hl-switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  border-radius: var(--hl-radius-sm);
  background: var(--hl-surface);
  border: 1px solid var(--hl-border);
}

.hl-switch-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.hl-switch-label {
  font-size: var(--hl-body);
  font-weight: 650;
  color: var(--hl-text);
}

.hl-switch-desc {
  font-size: var(--hl-caption);
  color: var(--hl-text-muted);
}

.hl-switch-control {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.hl-switch-state {
  font-size: var(--hl-caption);
  font-weight: 600;
  color: var(--hl-text-muted);
}

.hl-switch-root {
  width: 56px;
  height: 34px;
  border-radius: 999px;
  border: 2px solid var(--hl-control-border);
  background: #e3e6e1;
  position: relative;
  cursor: pointer;
  padding: 0;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}

.hl-switch-root[data-state="checked"] {
  background: var(--hl-brand);
  border-color: var(--hl-brand);
}

.hl-switch-thumb {
  display: block;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #ffffff;
  transform: translateX(3px);
  transition: transform 0.15s ease;
  box-shadow: 0 1px 3px rgb(0 0 0 / 0.2);
}

.hl-switch-thumb[data-state="checked"] {
  transform: translateX(25px);
}
</style>
