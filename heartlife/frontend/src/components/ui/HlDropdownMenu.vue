<script setup lang="ts">
import {
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuPortal,
  DropdownMenuRoot,
  DropdownMenuTrigger,
} from 'reka-ui'
import { MoreHorizontal } from 'lucide-vue-next'

export interface DropdownActionItem {
  key: string
  label: string
  danger?: boolean
}

const props = withDefaults(
  defineProps<{
    label?: string
    items: DropdownActionItem[]
  }>(),
  {
    label: '更多操作',
  }
)

const emit = defineEmits<{
  (e: 'select', key: string): void
}>()
</script>

<template>
  <DropdownMenuRoot>
    <DropdownMenuTrigger as-child>
      <button type="button" class="btn btn-ghost btn-sm hl-menu-trigger" :aria-label="props.label">
        <MoreHorizontal :size="20" aria-hidden="true" />
        <span>更多</span>
      </button>
    </DropdownMenuTrigger>
    <DropdownMenuPortal>
      <DropdownMenuContent class="hl-dropdown-content" :side-offset="6" align="end">
        <DropdownMenuItem
          v-for="item in props.items"
          :key="item.key"
          class="hl-dropdown-item"
          :class="{ 'hl-dropdown-item-danger': item.danger }"
          @select="emit('select', item.key)"
        >
          {{ item.label }}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenuPortal>
  </DropdownMenuRoot>
</template>

<style>
.hl-dropdown-content {
  z-index: 240;
  min-width: 168px;
  background: var(--hl-surface);
  border: 1.5px solid var(--hl-control-border);
  border-radius: var(--hl-radius-sm);
  box-shadow: var(--hl-shadow-modal);
  padding: 6px;
}

.hl-dropdown-item {
  display: flex;
  align-items: center;
  min-height: var(--hl-target);
  padding: 8px 14px;
  border-radius: 8px;
  font-family: var(--hl-font);
  font-size: var(--hl-caption);
  font-weight: 600;
  color: var(--hl-text);
  cursor: pointer;
  user-select: none;
}

.hl-dropdown-item[data-highlighted] {
  background: var(--hl-surface-soft);
  color: var(--hl-brand);
  outline: none;
}

.hl-dropdown-item-danger {
  color: var(--hl-danger);
}

.hl-dropdown-item-danger[data-highlighted] {
  background: var(--hl-danger-soft);
  color: var(--hl-danger);
}
</style>
