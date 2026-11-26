<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  BookOpen,
  Bot,
  CalendarCheck,
  CheckCircle2,
  Circle,
  Clock,
  Footprints,
  MoonStar,
  NotebookPen,
  Smile,
  Trophy,
} from 'lucide-vue-next'
import { api, ApiClientError } from '../api/client'
import { useAuthStore } from '../stores/auth'
import ExternalEcgModal from '../components/ExternalEcgModal.vue'
import SectionHeader from '../components/common/SectionHeader.vue'
import HealthMetricCard from '../components/common/HealthMetricCard.vue'
import FeatureTile from '../components/common/FeatureTile.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import HlBadge from '../components/ui/HlBadge.vue'
import HlAvatar from '../components/ui/HlAvatar.vue'
import HlAlert from '../components/ui/HlAlert.vue'
import welcomeCompanionSvg from '../assets/heartlife/illustrations/welcome-companion.svg'
import { formatLocalDateToday, formatMood } from '../utils/format'
import type { DashboardData, PostSummary, TodayItem } from '../types/api'

const auth = useAuthStore()

const loading = ref(true)
const loadError = ref('')
const actionError = ref('')
const dashboard = ref<DashboardData | null>(null)
const pendingCheckins = reactive(new Set<string>())
const ecgModalOpen = ref(false)

let latestDashboardSeq = 0

const greetingPeriod = computed(() => {
  try {
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: auth.user?.timezone || 'Asia/Shanghai',
      hour: 'numeric',
      hour12: false,
    })
    const hourNum = Number(formatter.format(new Date()))
    if (!Number.isNaN(hourNum)) {
      if (hourNum >= 5 && hourNum < 12) return '早上好'
      if (hourNum >= 12 && hourNum < 18) return '下午好'
      return '晚上好'
    }
  } catch {
    // Fallback to local clock
  }
  const h = new Date().getHours()
  if (h >= 5 && h < 12) return '早上好'
  if (h >= 12 && h < 18) return '下午好'
  return '晚上好'
})

const greetingHeading = computed(() => {
  const nick = auth.user?.nickname?.trim()
  return nick ? `${greetingPeriod.value}，${nick}` : `${greetingPeriod.value}，欢迎回来`
})

const displayDate = computed(
  () => dashboard.value?.today_date || formatLocalDateToday(auth.user?.timezone)
)

const planProgressText = computed(() => {
  const ps = dashboard.value?.plans_summary
  if (!ps || ps.due_count === 0) return '无计划'
  return `${ps.completed_count} / ${ps.due_count}`
})

const journalRecorded = computed(() => Boolean(dashboard.value?.today_journal?.recorded))

const sleepMetricValue = computed<number | null>(() => {
  const j = dashboard.value?.today_journal
  if (!j || !j.recorded || j.sleep_minutes === null || j.sleep_minutes === undefined) {
    return null
  }
  return j.sleep_minutes
})

const activityMetricValue = computed<number | null>(() => {
  const j = dashboard.value?.today_journal
  if (!j || !j.recorded || j.activity_minutes === null || j.activity_minutes === undefined) {
    return null
  }
  return j.activity_minutes
})

const moodMetricValue = computed<string | null>(() => {
  const j = dashboard.value?.today_journal
  if (!j || !j.recorded || !j.mood) {
    return null
  }
  return formatMood(j.mood)
})

function getPlanId(item: TodayItem): string {
  return item.plan_id || item.id || ''
}

function getStreak(item: TodayItem): number {
  return item.streak_days ?? item.current_streak ?? item.streak ?? 0
}

function postAuthorName(post: PostSummary): string {
  return post.author?.nickname || post.author_nickname || '心伴友邻'
}

async function loadDashboard() {
  const seq = ++latestDashboardSeq
  loading.value = true
  loadError.value = ''
  actionError.value = ''
  try {
    const data = await api.get<DashboardData>('/me/dashboard')
    if (seq !== latestDashboardSeq) return
    dashboard.value = data
    if (typeof data.unread_notifications_count === 'number') {
      auth.unreadCount = data.unread_notifications_count
    }
  } catch (err) {
    if (seq !== latestDashboardSeq) return
    loadError.value = err instanceof ApiClientError ? err.message : '暂时无法加载首页数据，请重试'
  } finally {
    if (seq === latestDashboardSeq) {
      loading.value = false
    }
  }
}

async function toggleTodayPlan(item: TodayItem) {
  if (!dashboard.value) return
  const pid = getPlanId(item)
  if (!pid || pendingCheckins.has(pid)) return

  pendingCheckins.add(pid)
  actionError.value = ''
  const dateStr = dashboard.value.today_date
  const nextCompleted = !item.completed

  try {
    if (nextCompleted) {
      await api.put(`/me/plans/${pid}/checkins/${dateStr}`)
    } else {
      await api.delete(`/me/plans/${pid}/checkins/${dateStr}`)
    }
    item.completed = nextCompleted
    dashboard.value.plans_summary.completed_count = dashboard.value.plans_summary.items.filter(
      (i) => i.completed
    ).length
  } catch (err) {
    // UI-T20: Keep original item.completed & completed_count untouched on failure
    actionError.value =
      err instanceof ApiClientError ? err.message : '打卡状态暂未保存成功，请稍后重试'
  } finally {
    pendingCheckins.delete(pid)
  }
}

onMounted(() => {
  loadDashboard()
})
</script>

<template>
  <div class="stack">
    <!-- Warm Companion Hero Card (PRD §5.1 / §5.3: <= 1/3 viewport, zero fake scores) -->
    <section class="hl-card hl-hero-card" aria-label="今日陪伴问候">
      <div class="hl-hero-content">
        <div class="row-wrap">
          <HlBadge variant="brand" class="tabular">
            <CalendarCheck :size="16" aria-hidden="true" />
            <span>{{ displayDate }}</span>
          </HlBadge>
        </div>

        <h1 class="page-title hl-hero-title">{{ greetingHeading }}</h1>
        <p class="hl-hero-subtitle">慢慢来，把今天的小事照顾好，就是很棒的一天。</p>

        <div class="hl-hero-actions">
          <RouterLink to="/journal" class="btn btn-primary">
            <NotebookPen :size="20" aria-hidden="true" />
            <span>记录今日</span>
          </RouterLink>

          <RouterLink to="/weekly-report" class="btn btn-secondary">
            查看本周回顾
          </RouterLink>

          <button
            v-if="auth.safeEcgExternalUrl"
            type="button"
            class="btn btn-soft"
            @click="ecgModalOpen = true"
          >
            独立心电检测
          </button>
        </div>
      </div>

      <div class="hl-hero-art" aria-hidden="true">
        <img
          :src="welcomeCompanionSvg"
          alt=""
          aria-hidden="true"
          width="320"
          height="160"
          class="hl-hero-illustration"
        />
      </div>
    </section>

    <HlAlert v-if="actionError" variant="error">
      {{ actionError }}
    </HlAlert>

    <LoadingState v-if="loading && !dashboard" :count="2" @retry="loadDashboard" />

    <ErrorState
      v-else-if="loadError && !dashboard"
      title="暂时无法加载，请重试"
      :message="loadError"
      @retry="loadDashboard"
    />

    <template v-else-if="dashboard">
      <!-- Desktop 2-Column Companion Grid (~58% Left / ~42% Right on >=1024px) -->
      <div class="hl-home-grid">
        <!-- Left Column: Today's Habit Plans + Community Warm Highlights -->
        <div class="stack">
          <section class="hl-card stack" aria-label="今日计划">
            <SectionHeader title="今日计划">
              <template #action>
                <div class="row-wrap">
                  <HlBadge
                    :variant="dashboard.plans_summary.due_count > 0 ? 'brand' : 'neutral'"
                    class="tabular"
                  >
                    {{ planProgressText }}
                  </HlBadge>
                  <RouterLink to="/plans" class="btn btn-ghost btn-sm">管理计划</RouterLink>
                </div>
              </template>
            </SectionHeader>

            <EmptyState
              v-if="
                dashboard.plans_summary.due_count === 0 ||
                dashboard.plans_summary.items.length === 0
              "
              title="今天还没有安排习惯计划"
              description="可以从饭后散步、温水补充或规律睡眠等温和习惯开始。"
            >
              <template #actions>
                <RouterLink to="/plans" class="btn btn-primary btn-sm">去创建习惯计划</RouterLink>
              </template>
            </EmptyState>

            <ul v-else class="hl-clean-list">
              <li
                v-for="item in dashboard.plans_summary.items"
                :key="getPlanId(item)"
                class="hl-plan-checkin-row"
                :class="{ 'hl-plan-checkin-done': item.completed }"
              >
                <div class="hl-plan-checkin-main">
                  <CheckCircle2
                    v-if="item.completed"
                    :size="24"
                    class="hl-plan-icon-done"
                    aria-hidden="true"
                  />
                  <Circle
                    v-else
                    :size="24"
                    class="hl-plan-icon-todo"
                    aria-hidden="true"
                  />
                  <div class="hl-plan-checkin-text">
                    <span class="hl-plan-title" :class="{ 'hl-plan-title-done': item.completed }">
                      {{ item.title }}
                    </span>
                    <div class="row-wrap">
                      <HlBadge v-if="getStreak(item) > 0" variant="accent" class="tabular">
                        连续 {{ getStreak(item) }} 天
                      </HlBadge>
                      <HlBadge
                        v-if="item.reminder_enabled && item.reminder_time"
                        variant="neutral"
                        class="tabular"
                      >
                        <Clock :size="14" aria-hidden="true" />
                        <span>{{ item.reminder_time }}</span>
                      </HlBadge>
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  class="btn btn-sm"
                  :class="item.completed ? 'btn-soft' : 'btn-primary'"
                  :disabled="pendingCheckins.has(getPlanId(item))"
                  @click="toggleTodayPlan(item)"
                >
                  {{ item.completed ? '已完成' : '完成打卡' }}
                </button>
              </li>
            </ul>
          </section>

          <section class="hl-card stack" aria-label="社区温暖分享">
            <SectionHeader
              title="社区温暖分享"
              action-to="/community"
              action-label="前往互助社区"
            />

            <EmptyState
              v-if="
                !dashboard.community_highlights || dashboard.community_highlights.length === 0
              "
              title="还没有社区动态"
              description="去同伴社区看看大家的生活记录，互相鼓励坚持。"
            >
              <template #actions>
                <RouterLink to="/community" class="btn btn-secondary btn-sm">
                  前往互助社区
                </RouterLink>
              </template>
            </EmptyState>

            <ul v-else class="hl-clean-list">
              <li
                v-for="post in dashboard.community_highlights.slice(0, 3)"
                :key="post.id"
                class="hl-community-preview-card"
              >
                <div class="row-between">
                  <div class="row-wrap">
                    <HlAvatar :name="postAuthorName(post)" size="sm" />
                    <span class="hl-preview-author">{{ postAuthorName(post) }}</span>
                  </div>
                  <HlBadge variant="brand">{{ post.category }}</HlBadge>
                </div>
                <RouterLink :to="`/community/${post.id}`" class="hl-preview-link user-content">
                  {{ post.title }}
                </RouterLink>
              </li>
            </ul>
          </section>
        </div>

        <!-- Right Column: Today's Health Metrics + Encyclopedia + Feature Tiles -->
        <div class="stack">
          <section class="hl-card stack" aria-label="今日生活记录">
            <SectionHeader title="今日生活记录">
              <template #action>
                <HlBadge :variant="journalRecorded ? 'brand' : 'neutral'">
                  {{ journalRecorded ? '今日已记录' : '尚未记录' }}
                </HlBadge>
              </template>
            </SectionHeader>

            <div class="hl-metrics-stack">
              <HealthMetricCard
                label="睡眠时长"
                :value="sleepMetricValue"
                unit="分钟"
                empty-text="尚未记录"
                tone="soft"
              >
                <template #icon>
                  <MoonStar :size="20" />
                </template>
              </HealthMetricCard>

              <HealthMetricCard
                label="活动时长"
                :value="activityMetricValue"
                unit="分钟"
                empty-text="尚未记录"
                tone="soft"
              >
                <template #icon>
                  <Footprints :size="20" />
                </template>
              </HealthMetricCard>

              <HealthMetricCard
                label="今日心情"
                :value="moodMetricValue"
                empty-text="尚未记录"
                tone="soft"
              >
                <template #icon>
                  <Smile :size="20" />
                </template>
              </HealthMetricCard>
            </div>

            <div class="row-between">
              <span class="text-sm hl-muted">空白项保持尚未记录，不会按 0 计入统计。</span>
              <RouterLink
                to="/journal"
                class="btn btn-sm"
                :class="journalRecorded ? 'btn-soft' : 'btn-primary'"
              >
                {{ journalRecorded ? '修改今日记录' : '去补充今日记录' }}
              </RouterLink>
            </div>
          </section>

          <section class="hl-card stack-sm" aria-label="精选健康百科">
            <SectionHeader
              title="精选健康百科"
              action-to="/knowledge"
              action-label="浏览健康百科"
            />

            <p
              v-if="!dashboard.recommended_articles || dashboard.recommended_articles.length === 0"
              class="text-sm hl-muted"
              style="margin: 0"
            >
              还没有推荐科普文章，可前往健康百科浏览全部内容。
            </p>

            <ul v-else class="hl-clean-list">
              <li
                v-for="art in dashboard.recommended_articles.slice(0, 3)"
                :key="art.id"
                class="hl-article-item"
              >
                <div class="row-wrap" style="margin-bottom: 4px">
                  <BookOpen :size="18" style="color: var(--hl-brand)" aria-hidden="true" />
                  <HlBadge variant="neutral">{{ art.category }}</HlBadge>
                </div>
                <RouterLink :to="`/knowledge/${art.id}`" class="hl-article-link">
                  {{ art.title }}
                </RouterLink>
              </li>
            </ul>
          </section>

          <section class="hl-card stack-sm" aria-label="更多关怀服务">
            <h2 class="section-title">日常工具与服务</h2>
            <div class="stack-sm">
              <FeatureTile
                title="健康周报"
                description="查看本周睡眠、活动与习惯完成趋势"
                to="/weekly-report"
              >
                <template #icon>
                  <CalendarCheck :size="22" />
                </template>
              </FeatureTile>

              <FeatureTile
                title="微习惯挑战"
                description="循序渐进参与温和无排名的日常打卡活动"
                to="/challenges"
              >
                <template #icon>
                  <Trophy :size="22" />
                </template>
              </FeatureTile>

              <FeatureTile
                v-if="auth.publicConfig.assistant_enabled"
                title="健康生活助手"
                description="结合科普内容解答日常作息与运动疑问"
                to="/assistant"
              >
                <template #icon>
                  <Bot :size="22" />
                </template>
              </FeatureTile>
            </div>
          </section>
        </div>
      </div>
    </template>

    <ExternalEcgModal
      v-if="auth.safeEcgExternalUrl"
      :open="ecgModalOpen"
      :url="auth.safeEcgExternalUrl"
      @close="ecgModalOpen = false"
    />
  </div>
</template>

<style scoped>
.hl-hero-card {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(200px, 320px);
  gap: 24px;
  align-items: center;
  background: linear-gradient(135deg, var(--hl-surface) 0%, var(--hl-surface-soft) 100%);
  border: 1.5px solid var(--hl-border);
}

.hl-hero-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.hl-hero-title {
  margin: 0;
}

.hl-hero-subtitle {
  margin: 0;
  font-size: var(--hl-body);
  color: var(--hl-text-muted);
  max-width: 560px;
}

.hl-hero-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 4px;
}

.hl-hero-art {
  display: flex;
  justify-content: flex-end;
  align-items: center;
}

.hl-hero-illustration {
  width: 100%;
  max-width: 320px;
  max-height: 164px;
  height: auto;
  border-radius: var(--hl-radius-md);
  object-fit: contain;
}

.hl-home-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.38fr) minmax(0, 1fr);
  gap: 24px;
  align-items: start;
}

.hl-metrics-stack {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 12px;
}

.hl-clean-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.hl-plan-checkin-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  min-height: 64px;
  padding: 14px 16px;
  border-radius: var(--hl-radius-md);
  background: var(--hl-canvas);
  border: 1.5px solid var(--hl-border);
}

.hl-plan-checkin-done {
  background: var(--hl-surface-soft);
}

.hl-plan-checkin-main {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1 1 200px;
  min-width: 0;
}

.hl-plan-icon-done {
  color: var(--hl-brand);
  flex-shrink: 0;
}

.hl-plan-icon-todo {
  color: var(--hl-control-border);
  flex-shrink: 0;
}

.hl-plan-checkin-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.hl-plan-title {
  font-size: var(--hl-body);
  font-weight: 650;
  color: var(--hl-text);
  overflow-wrap: anywhere;
}

.hl-plan-title-done {
  color: var(--hl-text-muted);
  text-decoration: line-through;
}

.hl-community-preview-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
  border-radius: var(--hl-radius-md);
  background: var(--hl-canvas);
  border: 1px solid var(--hl-border);
}

.hl-preview-author {
  font-size: var(--hl-caption);
  font-weight: 600;
  color: var(--hl-text);
}

.hl-preview-link {
  font-size: var(--hl-body);
  font-weight: 650;
  color: var(--hl-text);
}

.hl-preview-link:hover {
  color: var(--hl-brand);
}

.hl-article-item {
  padding: 12px 14px;
  border-radius: var(--hl-radius-sm);
  background: var(--hl-canvas);
  border: 1px solid var(--hl-border);
}

.hl-article-link {
  display: block;
  font-size: var(--hl-body);
  font-weight: 650;
  color: var(--hl-text);
  overflow-wrap: anywhere;
}

.hl-article-link:hover {
  color: var(--hl-brand);
}

@media (max-width: 1180px) {
  .hl-metrics-stack {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 1023px) {
  .hl-home-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .hl-metrics-stack {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 767px) {
  .hl-hero-card {
    grid-template-columns: minmax(0, 1fr);
    gap: 16px;
  }

  .hl-hero-art {
    justify-content: flex-start;
  }

  .hl-hero-illustration {
    max-width: 240px;
    max-height: 120px;
  }

  .hl-metrics-stack {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 420px) {
  .hl-hero-art {
    display: none;
  }
}
</style>
