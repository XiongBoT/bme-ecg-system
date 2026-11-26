<script setup lang="ts">
import { cn } from '../../utils/cn'

const props = withDefaults(
  defineProps<{
    class?: string
  }>(),
  {
    class: '',
  }
)
</script>

<template>
  <div :class="cn('hl-skeleton', props.class)" aria-hidden="true"></div>
</template>

<style scoped>
.hl-skeleton {
  background: linear-gradient(90deg, #ece9df 25%, #f4f2eb 50%, #ece9df 75%);
  background-size: 200% 100%;
  border-radius: var(--hl-radius-sm);
  animation: hlSkeletonPulse 1.6s ease-in-out infinite;
}

@keyframes hlSkeletonPulse {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}
</style>
