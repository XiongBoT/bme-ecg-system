<script setup lang="ts">
import { computed } from 'vue'
import { cn } from '../../utils/cn'

const props = withDefaults(
  defineProps<{
    variant?: 'default' | 'soft' | 'accent'
    as?: string
    class?: string
  }>(),
  {
    variant: 'default',
    as: 'div',
    class: '',
  }
)

const baseClass = computed(() => {
  if (props.variant === 'soft') return 'hl-card-soft'
  if (props.variant === 'accent') return 'hl-card-accent'
  return 'hl-card'
})
</script>

<template>
  <component :is="as" :class="cn(baseClass, props.class)">
    <slot />
  </component>
</template>
