<script setup lang="ts">
import { computed } from 'vue'
import { cn } from '../../utils/cn'

const props = withDefaults(
  defineProps<{
    variant?: 'neutral' | 'brand' | 'accent' | 'danger'
    class?: string
  }>(),
  {
    variant: 'neutral',
    class: '',
  }
)

const variantClass = computed(() => {
  if (props.variant === 'brand') return 'badge-brand'
  if (props.variant === 'accent') return 'badge-accent'
  if (props.variant === 'danger') return 'badge-danger'
  return ''
})
</script>

<template>
  <span :class="cn('badge', variantClass, props.class)">
    <slot />
  </span>
</template>
