<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Award, CalendarCheck, Share2, Sparkles } from 'lucide-vue-next'
import { api, ApiClientError } from '../api/client'
import communityEmptySvg from '../assets/heartlife/illustrations/community-empty.svg'
import PageHeader from '../components/common/PageHeader.vue'
import ConfirmDialog from '../components/common/ConfirmDialog.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import HlAlert from '../components/ui/HlAlert.vue'
import HlBadge from '../components/ui/HlBadge.vue'
import type { ChallengeItem, UserChallengeProgress } from '../types/api'

const router = useRouter()

const challenges = ref<ChallengeItem[]>([])
const myProgressList = ref<UserChallengeProgress[]>([])
const badges = ref<Array<{ challenge_id?: string; badge_title: string; achieved_date: string }>>([])

const loading = ref(true)
const errorMessage = ref('')
const statusMessage = ref('')
const pendingIds = reactive(new Set<string>())

// ConfirmDialog before leaving a challenge so progress isn't lost by mistake
const leaveDialogOpen = ref(false)
const pendingLeaveChallenge = ref<ChallengeItem | null>(null)
const leavingChallenge = ref(false)

const progressMap = computed(() => {
  const m = new Map<string, UserChallengeProgress>()
  for (const p of myProgressList.value) {
    const cid = p.challenge_id || p.id
    if (cid && p.status !== 'left') {
      m.set(cid, p)
    }
  }
  return m
})

function isJoined(ch: ChallengeItem): boolean {
  if (typeof ch.joined === 'boolean') return ch.joined
  return progressMap.value.has(ch.id)
}

function getProgressDays(ch: ChallengeItem): number {
  const p = progressMap.value.get(ch.id)
  if (p) return p.progress_days ?? p.completed_days ?? 0
  return ch.progress_days ?? ch.completed_days ?? 0
}

function getProgressPercent(ch: ChallengeItem): number {
  const days = getProgressDays(ch)
  const target = Math.max(1, ch.target_days || 1)
  return Math.min(100, Math.round((days / target) * 100))
}

function isAchieved(ch: ChallengeItem): boolean {
  const p = progressMap.value.get(ch.id)
  if (p && typeof p.achieved === 'boolean') return p.achieved
  if (typeof ch.achieved === 'boolean') return ch.achieved
  return badges.value.some((b) => b.challenge_id === ch.id || b.badge_title === ch.badge_title)
}

async function loadChallenges() {
  loading.value = true
  errorMessage.value = ''
  try {
    const [pubRes, meRes] = await Promise.all([
      api.get<{ items?: ChallengeItem[] } | ChallengeItem[]>('/challenges'),
      api
        .get<{
          items?: UserChallengeProgress[]
          memberships?: UserChallengeProgress[]
          badges?: Array<{ challenge_id?: string; badge_title: string; achieved_date: string }>
        }>('/me/challenges')
        .catch(() => ({ items: [], badges: [] })),
    ])

    challenges.value = Array.isArray(pubRes) ? pubRes : pubRes.items || []
    if (meRes && typeof meRes === 'object') {
      myProgressList.value =
        'items' in meRes && Array.isArray(meRes.items)
          ? meRes.items
          : 'memberships' in meRes && Array.isArray(meRes.memberships)
            ? meRes.memberships
            : []
      badges.value = 'badges' in meRes && Array.isArray(meRes.badges) ? meRes.badges : []
    }
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '暂时无法加载挑战列表，请重试'
  } finally {
    loading.value = false
  }
}

async function joinChallenge(ch: ChallengeItem) {
  if (pendingIds.has(ch.id)) return
  pendingIds.add(ch.id)
  errorMessage.value = ''
  statusMessage.value = ''
  try {
    await api.put(`/challenges/${ch.id}/membership`)
    statusMessage.value = `已加入「${ch.title}」，按照自己的节奏慢慢坚持吧！`
    await loadChallenges()
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '操作失败，请稍后重试'
  } finally {
    pendingIds.delete(ch.id)
  }
}

function promptLeaveChallenge(ch: ChallengeItem) {
  pendingLeaveChallenge.value = ch
  leaveDialogOpen.value = true
}

async function confirmLeaveChallenge() {
  const ch = pendingLeaveChallenge.value
  if (!ch || leavingChallenge.value) return
  leavingChallenge.value = true
  pendingIds.add(ch.id)
  errorMessage.value = ''
  statusMessage.value = ''
  try {
    await api.delete(`/challenges/${ch.id}/membership`)
    leaveDialogOpen.value = false
    pendingLeaveChallenge.value = null
    statusMessage.value = `已退出「${ch.title}」，随时欢迎再次加入。`
    await loadChallenges()
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '退出失败，请稍后重试'
  } finally {
    leavingChallenge.value = false
    pendingIds.delete(ch.id)
  }
}

async function shareProgress(ch: ChallengeItem) {
  if (pendingIds.has(ch.id)) return
  pendingIds.add(ch.id)
  errorMessage.value = ''
  statusMessage.value = ''
  try {
    const res = await api.post<{ post_id?: string; id?: string }>(`/me/challenges/${ch.id}/share`, {})
    const pid = res?.post_id || res?.id
    if (pid) {
      await router.push(`/community/${pid}`)
    } else {
      statusMessage.value = '已分享挑战进展到社区'
    }
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '分享失败，请稍后重试'
  } finally {
    pendingIds.delete(ch.id)
  }
}

onMounted(() => {
  loadChallenges()
})
</script>

<template>
  <div class="stack">
    <PageHeader
      title="微习惯挑战"
      subtitle="不排名、不攀比，只和自己比昨天多坚持一点点。"
    />

    <HlAlert v-if="errorMessage && challenges.length > 0" variant="error" role="alert">
      {{ errorMessage }}
    </HlAlert>
    <HlAlert v-if="statusMessage" variant="success" role="status">
      {{ statusMessage }}
    </HlAlert>

    <!-- Earned Badges Celebration Card -->
    <section v-if="badges.length > 0" class="hl-card-accent stack-sm" aria-label="已获得的习惯徽章">
      <div class="row-wrap">
        <Award :size="22" style="color: var(--hl-accent-ink)" aria-hidden="true" />
        <h2 class="card-title" style="color: var(--hl-accent-ink)">我的坚持纪念徽章</h2>
      </div>
      <div class="row-wrap">
        <HlBadge v-for="(b, idx) in badges" :key="idx" variant="accent" class="tabular">
          <Sparkles :size="15" aria-hidden="true" />
          <span>已获得徽章：{{ b.badge_title }} · {{ b.achieved_date }}</span>
        </HlBadge>
      </div>
    </section>

    <LoadingState v-if="loading" :count="2" @retry="loadChallenges" />

    <ErrorState
      v-else-if="errorMessage"
      title="暂时无法加载，请重试"
      :message="errorMessage"
      show-home-link
      @retry="loadChallenges"
    />

    <EmptyState
      v-else-if="challenges.length === 0"
      :illustration="communityEmptySvg"
      title="当前暂无微习惯挑战"
      description="您可以先在「日常习惯计划」中设定适合自己的每日健康小目标。"
    >
      <template #actions>
        <RouterLink to="/plans" class="btn btn-primary btn-sm">前往日常计划</RouterLink>
      </template>
    </EmptyState>

    <div v-else class="grid-2">
      <article v-for="ch in challenges" :key="ch.id" class="hl-card hl-challenge-card">
        <div class="row-between">
          <HlBadge v-if="isAchieved(ch)" variant="accent">
            <Award :size="16" aria-hidden="true" />
            <span>已获得徽章：{{ ch.badge_title }}</span>
          </HlBadge>
          <HlBadge v-else variant="brand">
            <Sparkles :size="15" aria-hidden="true" />
            <span>纪念徽章：{{ ch.badge_title }}</span>
          </HlBadge>

          <span class="row-wrap text-sm hl-muted tabular" style="gap: 5px">
            <CalendarCheck :size="17" aria-hidden="true" />
            <span>目标 {{ ch.target_days }} 天</span>
          </span>
        </div>

        <h2 class="section-title">{{ ch.title }}</h2>
        <p class="hl-muted text-sm" style="margin: 0; flex: 1">{{ ch.description }}</p>

        <!-- Accessible Progress Bar & Clear Numeric Label -->
        <div v-if="isJoined(ch)" class="hl-challenge-progress stack-sm">
          <div class="row-between text-sm tabular">
            <strong style="color: var(--hl-text)">
              已完成 {{ getProgressDays(ch) }} / {{ ch.target_days }} 天
            </strong>
            <span class="hl-muted">{{ getProgressPercent(ch) }}%</span>
          </div>
          <div
            role="progressbar"
            :aria-valuenow="getProgressDays(ch)"
            :aria-valuemin="0"
            :aria-valuemax="ch.target_days"
            :aria-label="`${ch.title}完成进度`"
            class="hl-progress-track"
          >
            <div
              class="hl-progress-fill"
              :style="{ width: `${getProgressPercent(ch)}%` }"
            ></div>
          </div>
        </div>

        <div class="row-between" style="padding-top: 6px">
          <button
            v-if="!isJoined(ch)"
            type="button"
            class="btn btn-primary btn-sm"
            :disabled="pendingIds.has(ch.id)"
            @click="joinChallenge(ch)"
          >
            参与挑战
          </button>
          <button
            v-else
            type="button"
            class="btn btn-secondary btn-sm"
            :disabled="pendingIds.has(ch.id)"
            @click="promptLeaveChallenge(ch)"
          >
            退出挑战
          </button>

          <button
            v-if="isJoined(ch)"
            type="button"
            class="btn btn-accent btn-sm"
            :disabled="pendingIds.has(ch.id)"
            @click="shareProgress(ch)"
          >
            <Share2 :size="18" aria-hidden="true" />
            <span>分享进展到社区</span>
          </button>
        </div>
      </article>
    </div>

    <ConfirmDialog
      v-model:open="leaveDialogOpen"
      title="确认退出微习惯挑战"
      :description="`确认退出「${pendingLeaveChallenge?.title || ''}」吗？退出后当前挑战进度将暂停统计，已获得的纪念徽章会继续保留。`"
      confirm-label="确认退出"
      danger
      :loading="leavingChallenge"
      @confirm="confirmLeaveChallenge"
    />
  </div>
</template>

<style scoped>
.hl-challenge-card {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.hl-challenge-progress {
  padding: 14px 16px;
  border-radius: var(--hl-radius-sm);
  background: var(--hl-accent-soft);
  border: 1px solid #e6cdb5;
}

.hl-progress-track {
  width: 100%;
  height: 12px;
  border-radius: 999px;
  background: var(--hl-surface);
  border: 1px solid #d9bf9f;
  overflow: hidden;
}

.hl-progress-fill {
  height: 100%;
  background: var(--hl-brand);
  border-radius: 999px;
  transition: width 0.2s ease;
}
</style>
