<script setup lang="ts">
import { computed } from 'vue'
import { AlertCircle, CheckCircle2, Info } from 'lucide-vue-next'
import { cn } from '../../utils/cn'

const props = withDefaults(
  defineProps<{
    variant?: 'info' | 'success' | 'warning' | 'error'
    role?: 'alert' | 'status' | 'note'
    class?: string
  }>(),
  {
    variant: 'info',
    role: undefined,
    class: '',
  }
)

const computedRole = computed(() => {
  if (props.role) return props.role
  return props.variant === 'error' ? 'alert' : 'status'
})

const variantClass = computed(() => {
  if (props.variant === 'error') return 'alert-error'
  if (props.variant === 'warning') return 'alert-warning'
  if (props.variant === 'success') return 'alert-brand'
  return ''
})
</script>

<template>
  <div :role="computedRole" :class="cn('alert', variantClass, props.class)">
    <AlertCircle
      v-if="variant === 'error' || variant === 'warning'"
      class="hl-alert-icon"
      aria-hidden="true"
    />
    <CheckCircle2
      v-else-if="variant === 'success'"
      class="hl-alert-icon"
      aria-hidden="true"
    />
    <Info v-else class="hl-alert-icon" aria-hidden="true" />
    <div class="hl-alert-content">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.hl-alert-icon {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  margin-top: 3px;
}

.hl-alert-content {
  flex: 1;
  min-width: 0;
}
</style>
