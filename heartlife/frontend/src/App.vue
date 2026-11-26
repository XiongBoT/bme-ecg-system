<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from './components/AppShell.vue'
import { usePreferencesStore } from './stores/preferences'

const route = useRoute()
const prefs = usePreferencesStore()
const isAuthRoute = computed(() => route.name === 'login')

onMounted(() => {
  prefs.hydrate()
})
</script>

<template>
  <div v-if="isAuthRoute" class="hl-shell auth-page-shell">
    <main class="main-container">
      <RouterView />
    </main>
    <footer class="standalone-footer no-print">
      健康生活记录与科普参考 · 不作为医疗诊断建议
    </footer>
  </div>
  <AppShell v-else>
    <RouterView />
  </AppShell>
</template>

<style scoped>
.auth-page-shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.standalone-footer {
  text-align: center;
  padding: 20px 16px 32px;
  font-size: var(--hl-caption);
  color: var(--hl-text-muted);
  border-top: 1px solid var(--hl-border);
}
</style>
