<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { CalendarDays, ChevronLeft, ShieldCheck, UserCheck, UserX } from 'lucide-vue-next'
import { api, ApiClientError } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { formatDateTimeShort } from '../utils/format'
import communityEmptySvg from '../assets/heartlife/illustrations/community-empty.svg'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import HlAlert from '../components/ui/HlAlert.vue'
import HlAvatar from '../components/ui/HlAvatar.vue'
import HlBadge from '../components/ui/HlBadge.vue'
import type { PublicUserProfile } from '../types/api'

const route = useRoute()
const auth = useAuthStore()

const userId = computed(() => String(route.params.id || ''))
const profile = ref<PublicUserProfile | null>(null)
const loading = ref(true)
const notFound = ref(false)
const blocked = ref(false)
const errorMessage = ref('')

const isSelf = computed(() => Boolean(auth.user && auth.user.id === userId.value))

const joinDateLabel = computed(() => {
  if (!profile.value?.created_at) return ''
  return formatDateTimeShort(profile.value.created_at).slice(0, 10)
})

async function loadPublicProfile() {
  if (!userId.value) return
  loading.value = true
  notFound.value = false
  errorMessage.value = ''
  try {
    profile.value = await api.get<PublicUserProfile>(`/users/${userId.value}`)
  } catch (err) {
    if (err instanceof ApiClientError && err.status === 404) {
      notFound.value = true
    } else {
      errorMessage.value = err instanceof ApiClientError ? err.message : '暂时无法加载主页，请重试'
    }
  } finally {
    loading.value = false
  }
}

async function toggleBlock() {
  if (!profile.value) return
  errorMessage.value = ''
  try {
    if (blocked.value) {
      await api.delete(`/me/blocks/${profile.value.id}`)
      blocked.value = false
    } else {
      await api.put(`/me/blocks/${profile.value.id}`)
      blocked.value = true
    }
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '操作失败，请稍后重试'
  }
}

watch(userId, () => {
  loadPublicProfile()
})

onMounted(() => {
  loadPublicProfile()
})
</script>

<template>
  <div class="narrow-container stack">
    <div>
      <RouterLink to="/community" class="hl-back-link">
        <ChevronLeft :size="20" aria-hidden="true" />
        <span>返回同伴社区</span>
      </RouterLink>
    </div>

    <HlAlert v-if="errorMessage && profile" variant="error" role="alert">
      {{ errorMessage }}
    </HlAlert>

    <LoadingState v-if="loading" :count="2" @retry="loadPublicProfile" />

    <EmptyState
      v-else-if="notFound || (!profile && !errorMessage)"
      :illustration="communityEmptySvg"
      title="用户不存在或不可用"
      description="该成员主页当前无法访问，您可以返回同伴社区浏览其他温暖分享。"
    >
      <template #actions>
        <RouterLink to="/community" class="btn btn-primary btn-sm">返回社区</RouterLink>
      </template>
    </EmptyState>

    <ErrorState
      v-else-if="errorMessage"
      title="暂时无法加载，请重试"
      :message="errorMessage"
      show-home-link
      @retry="loadPublicProfile"
    />

    <template v-else-if="profile">
      <!-- Warm Public Member Summary Card -->
      <section class="hl-card hl-public-header">
        <div class="hl-public-identity">
          <HlAvatar :name="profile.nickname" size="lg" />
          <div class="stack-sm" style="flex: 1; min-width: 0">
            <div class="row-wrap">
              <h1 class="page-title">{{ profile.nickname }}</h1>
              <HlBadge v-if="profile.is_demo" variant="brand">演示成员</HlBadge>
            </div>

            <p v-if="profile.bio" class="user-content text-sm" style="margin: 0">
              {{ profile.bio }}
            </p>
            <p v-else class="hl-muted text-sm" style="margin: 0">
              这位同伴还没有填写个人简介。
            </p>

            <div v-if="joinDateLabel" class="row-wrap text-sm hl-muted tabular">
              <CalendarDays :size="17" aria-hidden="true" />
              <span>加入心伴：{{ joinDateLabel }}</span>
            </div>
          </div>
        </div>

        <div class="row-wrap">
          <RouterLink v-if="isSelf" to="/me" class="btn btn-secondary btn-sm">
            编辑资料
          </RouterLink>
          <button
            v-else-if="auth.isAuthenticated"
            type="button"
            class="btn btn-secondary btn-sm"
            @click="toggleBlock"
          >
            <UserCheck v-if="blocked" :size="18" aria-hidden="true" />
            <UserX v-else :size="18" aria-hidden="true" />
            <span>{{ blocked ? '取消屏蔽' : '屏蔽该用户' }}</span>
          </button>
        </div>
      </section>

      <!-- Strict Privacy Boundary Notice -->
      <HlAlert variant="info" class="alert-brand" role="note">
        <div class="row-wrap">
          <ShieldCheck :size="20" aria-hidden="true" />
          <span>
            隐私保护说明：公开主页仅展示成员主动公开发布的社区动态，日常健康日记、习惯打卡与微挑战进度均严格保密，绝不对外展示。
          </span>
        </div>
      </HlAlert>

      <!-- Recent Approved Public Posts -->
      <section class="hl-card stack">
        <h2 class="section-title">近期公开分享</h2>

        <EmptyState
          v-if="profile.recent_posts.length === 0"
          title="暂无公开分享"
          description="这位成员近期还没有在同伴社区公开发布动态。"
        />

        <ul v-else class="hl-post-list">
          <li v-for="p in profile.recent_posts" :key="p.id" class="hl-post-row row-between">
            <div class="row-wrap">
              <HlBadge variant="brand">{{ p.category }}</HlBadge>
              <RouterLink :to="`/community/${p.id}`" class="user-content hl-post-link">
                {{ p.title }}
              </RouterLink>
            </div>
            <span class="text-sm hl-muted tabular">{{ formatDateTimeShort(p.created_at) }}</span>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.hl-back-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 44px;
  font-size: var(--hl-caption);
  font-weight: 600;
  color: var(--hl-brand);
}

.hl-public-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}

.hl-public-identity {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  flex: 1 1 300px;
  min-width: 0;
}

.hl-post-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.hl-post-row {
  padding: 14px 16px;
  border-radius: var(--hl-radius-sm);
  background: var(--hl-canvas);
  border: 1px solid var(--hl-border);
}

.hl-post-link {
  font-weight: 650;
  color: var(--hl-text);
}

.hl-post-link:hover {
  color: var(--hl-brand);
}
</style>
