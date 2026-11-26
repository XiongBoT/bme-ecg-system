<script setup lang="ts">
defineProps<{
  title: string
  description?: string
  illustration?: string
}>()
</script>

<template>
  <div class="empty-state">
    <img
      v-if="illustration"
      :src="illustration"
      alt=""
      aria-hidden="true"
      width="200"
      height="114"
      class="hl-empty-illu"
    />
    <p class="empty-title">{{ title }}</p>
    <p v-if="description" class="hl-empty-desc">{{ description }}</p>
    <div v-if="$slots.actions" class="row-wrap" style="justify-content: center; margin-top: 4px">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.hl-empty-illu {
  max-width: 200px;
  height: auto;
  border-radius: 14px;
}

.hl-empty-desc {
  margin: 0;
  max-width: 460px;
  font-size: var(--hl-caption);
  color: var(--hl-text-muted);
}
</style>
