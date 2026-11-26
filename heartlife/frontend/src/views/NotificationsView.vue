<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Bell, CheckCheck } from 'lucide-vue-next'
import { api, ApiClientError } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { formatDateTimeShort } from '../utils/format'
import communityEmptySvg from '../assets/heartlife/illustrations/community-empty.svg'
import PageHeader from '../components/common/PageHeader.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import HlAlert from '../components/ui/HlAlert.vue'
import HlBadge from '../components/ui/HlBadge.vue'
import type { NotificationItem } from '../types/api'

const auth = useAuthStore()
const router = useRouter()

const notifications = ref<NotificationItem[]>([])
const loading = ref(true)
const errorMessage = ref('')
const unavailableNotice = ref('')
const markingAll = ref(false)

const hasUnread = computed(() => notifications.value.some((n) => !n.read_at))

async function loadNotifications() {
  loading.value = true
  errorMessage.value = ''
  try {
    const res = await api.get<{ items?: NotificationItem[]; unread_count?: number } | NotificationItem[]>(
      '/me/notifications'
    )
    const items = Array.isArray(res) ? res : res.items || []
    notifications.value = items
    auth.unreadCount =
      !Array.isArray(res) && typeof res.unread_count === 'number'
        ? res.unread_count
        : items.filter((n) => !n.read_at).length
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '暂时无法加载，请重试'
  } finally {
    loading.value = false
  }
}

async function markAllRead() {
  errorMessage.value = ''
  markingAll.value = true
  try {
    await api.post('/me/notifications/read-all')
    const nowIso = new Date().toISOString()
    for (const item of notifications.value) {
      if (!item.read_at) item.read_at = nowIso
    }
    auth.unreadCount = 0
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '操作失败，请稍后重试'
  } finally {
    markingAll.value = false
  }
}

function resolveTargetRoute(item: NotificationItem): string | null {
  if (item.target_type === 'post' || item.target_type === 'comment') {
    return `/community/${item.target_id}`
  }
  if (item.target_type === 'article') {
    return `/knowledge/${item.target_id}`
  }
  if (item.target_type === 'plan') {
    return '/plans'
  }
  if (item.target_type === 'challenge') {
    return '/challenges'
  }
  return null
}

async function handleClickItem(item: NotificationItem) {
  unavailableNotice.value = ''
  try {
    const readRes = await api.post<{ target_available?: boolean }>(
      `/me/notifications/${item.id}/read`
    )
    if (!item.read_at) {
      item.read_at = new Date().toISOString()
      auth.unreadCount = Math.max(0, auth.unreadCount - 1)
    }
    if (readRes && typeof readRes.target_available === 'boolean') {
      item.target_available = readRes.target_available
    }
  } catch {
    // Still check target availability locally
  }

  if (item.target_available === false) {
    unavailableNotice.value = '原内容已不可用'
    return
  }

  const target = resolveTargetRoute(item)
  if (target) {
    await router.push(target)
  }
}

onMounted(() => {
  loadNotifications()
})
</script>

<template>
  <div class="narrow-container stack">
    <PageHeader
      title="消息通知"
      subtitle="查看社区互动、计划提醒与系统通知，未读与已读状态清晰标明。"
    >
      <template #actions>
        <button
          v-if="hasUnread"
          type="button"
          class="btn btn-secondary btn-sm"
          :disabled="markingAll"
          @click="markAllRead"
        >
          <CheckCheck :size="20" aria-hidden="true" />
          <span>{{ markingAll ? '正在标记...' : '全部标记已读' }}</span>
        </button>
      </template>
    </PageHeader>

    <HlAlert v-if="unavailableNotice" variant="warning" role="status">
      {{ unavailableNotice }}
    </HlAlert>

    <HlAlert v-if="errorMessage && notifications.length > 0" variant="error" role="alert">
      {{ errorMessage }}
    </HlAlert>

    <LoadingState v-if="loading" :count="3" @retry="loadNotifications" />

    <ErrorState
      v-else-if="errorMessage"
      title="暂时无法加载，请重试"
      :message="errorMessage"
      show-home-link
      @retry="loadNotifications"
    />

    <EmptyState
      v-else-if="notifications.length === 0"
      :illustration="communityEmptySvg"
      title="还没有消息通知"
      description="当有同伴赞同、评论您的分享，或有新的提醒时，会在这里显示。"
    >
      <template #actions>
        <RouterLink to="/community" class="btn btn-primary btn-sm">前往同伴社区</RouterLink>
      </template>
    </EmptyState>

    <ul v-else class="hl-notif-list">
      <li v-for="item in notifications" :key="item.id">
        <button
          type="button"
          class="hl-notif-card notif-card"
          :class="!item.read_at ? 'hl-notif-unread' : 'hl-notif-read'"
          @click="handleClickItem(item)"
        >
          <div class="hl-notif-top">
            <div class="row-wrap">
              <Bell
                :size="20"
                :style="{ color: !item.read_at ? 'var(--hl-brand)' : 'var(--hl-text-muted)' }"
                aria-hidden="true"
              />
              <!-- Explicit Unread / Read Text Badge (WCAG 1.4.1 & PRD §5.6 — never dot-only!) -->
              <HlBadge v-if="!item.read_at" variant="accent">未读</HlBadge>
              <HlBadge v-else variant="neutral">已读</HlBadge>
            </div>
            <span class="text-sm hl-muted tabular">{{ formatDateTimeShort(item.created_at) }}</span>
          </div>

          <div class="user-content hl-notif-summary">{{ item.summary }}</div>

          <div v-if="item.target_available === false" class="hl-notif-unavailable">
            原内容已不可用
          </div>
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.hl-notif-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.hl-notif-card {
  width: 100%;
  min-height: var(--hl-target);
  text-align: left;
  border-radius: var(--hl-radius-md);
  padding: 18px 20px;
  cursor: pointer;
  font-family: inherit;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}

.hl-notif-unread {
  background: var(--hl-surface-soft);
  border: 1.5px solid var(--hl-brand);
  border-left-width: 5px;
}

.hl-notif-read {
  background: var(--hl-surface);
  border: 1px solid var(--hl-border);
}

.hl-notif-card:hover {
  border-color: var(--hl-brand);
}

.hl-notif-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  width: 100%;
}

.hl-notif-summary {
  font-size: var(--hl-body);
  font-weight: 600;
  color: var(--hl-text);
}

.hl-notif-read .hl-notif-summary {
  font-weight: 500;
}

.hl-notif-unavailable {
  display: inline-flex;
  align-self: flex-start;
  padding: 4px 10px;
  border-radius: 8px;
  background: var(--hl-accent-soft);
  color: var(--hl-accent-ink);
  font-size: var(--hl-caption);
  font-weight: 600;
}
</style>
