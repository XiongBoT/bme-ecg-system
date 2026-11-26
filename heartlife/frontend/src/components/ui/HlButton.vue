<script setup lang="ts">
import { computed } from 'vue'
import { cn } from '../../utils/cn'

const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'soft' | 'accent' | 'ghost' | 'danger'
    type?: 'button' | 'submit' | 'reset'
    disabled?: boolean
    loading?: boolean
    block?: boolean
    class?: string
  }>(),
  {
    variant: 'primary',
    type: 'button',
    disabled: false,
    loading: false,
    block: false,
    class: '',
  }
)

const variantClass = computed(() => {
  switch (props.variant) {
    case 'secondary':
      return 'btn-secondary'
    case 'soft':
      return 'btn-soft'
    case 'accent':
      return 'btn-accent'
    case 'ghost':
      return 'btn-ghost'
    case 'danger':
      return 'btn-danger'
    default:
      return 'btn-primary'
  }
})
</script>

<template>
  <button
    :type="type"
    :disabled="disabled || loading"
    :aria-busy="loading ? 'true' : undefined"
    :class="cn('btn', variantClass, block && 'w-full', props.class)"
  >
    <slot />
  </button>
</template>
