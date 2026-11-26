<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  CalendarCheck2,
  ChevronLeft,
  ChevronRight,
  Footprints,
  MoonStar,
  NotebookPen,
  Printer,
  RotateCcw,
  Target,
} from 'lucide-vue-next'
import { api, ApiClientError } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { formatLocalDateToday, getMondayOfDate, shiftIsoDate } from '../utils/format'
import PageHeader from '../components/common/PageHeader.vue'
import HealthMetricCard from '../components/common/HealthMetricCard.vue'
import ChartWithDataTable from '../components/common/ChartWithDataTable.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import HlBadge from '../components/ui/HlBadge.vue'
import type { WeeklyReportData } from '../types/api'

const auth = useAuthStore()

const currentMonday = computed(() => getMondayOfDate(formatLocalDateToday(auth.user?.timezone)))
const selectedWeekStart = ref(currentMonday.value)

const loading = ref(true)
const errorMessage = ref('')
const report = ref<WeeklyReportData | null>(null)

const isCurrentWeek = computed(() => selectedWeekStart.value >= currentMonday.value)

const statusLabel = computed(() => {
  if (!report.value) return ''
  return report.value.status === 'partial_week' ? '截至今日' : '完整周'
})

const journalDays = computed(
  () => report.value?.journal_days ?? report.value?.coverage?.journal_days ?? 0
)
const observedDays = computed(
  () => report.value?.observed_days ?? report.value?.coverage?.observed_days ?? 7
)

const sleepMeanValue = computed<number | null>(() => {
  const s = report.value?.sleep
  if (!s || s.mean_minutes === null || s.mean_minutes === undefined) return null
  return Math.round(s.mean_minutes)
})

const activityTotalValue = computed<number | null>(() => {
  const a = report.value?.activity
  if (!a || a.total_minutes === null || a.total_minutes === undefined) return null
  return a.total_minutes
})

const planCompletionValue = computed<string | null>(() => {
  const p = report.value?.plans
  if (!p || p.due <= 0 || p.completion_rate === null || p.completion_rate === undefined) {
    return null
  }
  const pct = p.completion_rate <= 1 ? Math.round(p.completion_rate * 100) : Math.round(p.completion_rate)
  return `${pct}%`
})

const planCompletionSubtext = computed(() => {
  const p = report.value?.plans
  if (!p || p.due <= 0 || p.completion_rate === null || p.completion_rate === undefined) {
    return '本周无应执行计划'
  }
  return `已完成 ${p.completed} / ${p.due} 项`
})

async function fetchReport(weekStart: string) {
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await api.get<WeeklyReportData>('/me/weekly-report', {
      week_start: weekStart,
    })
    report.value = data
    if (data.week_start) {
      selectedWeekStart.value = data.week_start
    }
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '暂时无法加载，请重试'
  } finally {
    loading.value = false
  }
}

function shiftWeek(days: number) {
  const next = shiftIsoDate(selectedWeekStart.value, days)
  if (next > currentMonday.value) return
  selectedWeekStart.value = next
  fetchReport(next)
}

function goToCurrentWeek() {
  if (isCurrentWeek.value) return
  selectedWeekStart.value = currentMonday.value
  fetchReport(currentMonday.value)
}

function triggerPrint() {
  if (typeof window !== 'undefined' && typeof window.print === 'function') {
    window.print()
  }
}

onMounted(() => {
  fetchReport(selectedWeekStart.value)
})
</script>

<template>
  <div class="stack">
    <PageHeader
      title="健康周报"
      subtitle="汇总一周睡眠、活动与计划执行情况；未记录日期保持留白，不按 0 计入均值。"
    >
      <template #actions>
        <button
          type="button"
          class="btn btn-secondary btn-sm no-print"
          @click="triggerPrint"
        >
          <Printer :size="19" aria-hidden="true" />
          <span>打印周报</span>
        </button>
        <RouterLink to="/journal" class="btn btn-primary btn-sm no-print">
          <NotebookPen :size="19" aria-hidden="true" />
          <span>补充记录</span>
        </RouterLink>
      </template>
    </PageHeader>

    <!-- Week Switcher Toolbar -->
    <section class="hl-card row-between" aria-label="周报日期周期切换">
      <div class="row-wrap">
        <button
          type="button"
          class="btn btn-secondary btn-sm no-print"
          @click="shiftWeek(-7)"
        >
          <ChevronLeft :size="19" aria-hidden="true" />
          <span>上一周</span>
        </button>

        <div class="hl-week-period row-wrap">
          <span class="hl-week-dates tabular">
            {{ report ? `${report.week_start} ~ ${report.week_end}` : selectedWeekStart }}
          </span>
          <HlBadge
            v-if="report"
            :variant="report.status === 'partial_week' ? 'accent' : 'brand'"
          >
            {{ statusLabel }}
          </HlBadge>
        </div>

        <button
          type="button"
          class="btn btn-secondary btn-sm no-print"
          :disabled="isCurrentWeek"
          @click="shiftWeek(7)"
        >
          <span>下一周</span>
          <ChevronRight :size="19" aria-hidden="true" />
        </button>
      </div>

      <button
        type="button"
        class="btn btn-soft btn-sm no-print"
        :disabled="isCurrentWeek"
        @click="goToCurrentWeek"
      >
        <RotateCcw :size="18" aria-hidden="true" />
        <span>回到本周</span>
      </button>
    </section>

    <LoadingState v-if="loading" :count="2" />

    <ErrorState
      v-else-if="errorMessage && !report"
      title="暂时无法加载，请重试"
      :message="errorMessage"
      show-home-link
      @retry="fetchReport(selectedWeekStart)"
    />

    <template v-else-if="report">
      <ErrorState
        v-if="errorMessage"
        title="暂时无法加载，请重试"
        :message="errorMessage"
        @retry="fetchReport(selectedWeekStart)"
      />

      <!-- 4 Summary KPI Cards with Explicit Denominators & Missing-vs-Zero Clarity -->
      <section class="grid-4" aria-label="本周统计摘要">
        <HealthMetricCard
          label="记录覆盖"
          :value="`${journalDays} / ${observedDays}`"
          unit=" 天"
          :subtext="`${report.week_start} 起`"
        >
          <template #icon>
            <CalendarCheck2 :size="20" />
          </template>
        </HealthMetricCard>

        <HealthMetricCard
          label="平均睡眠"
          :value="sleepMeanValue"
          unit=" 分钟"
          empty-text="尚未记录"
          :subtext="`有效记录 ${report.sleep.valid_days} 天`"
        >
          <template #icon>
            <MoonStar :size="20" />
          </template>
        </HealthMetricCard>

        <HealthMetricCard
          label="累计活动"
          :value="activityTotalValue"
          unit=" 分钟"
          empty-text="尚未记录"
          :subtext="`有效记录 ${report.activity.valid_days} 天`"
        >
          <template #icon>
            <Footprints :size="20" />
          </template>
        </HealthMetricCard>

        <HealthMetricCard
          label="计划完成率"
          :value="planCompletionValue"
          empty-text="无计划"
          :subtext="planCompletionSubtext"
        >
          <template #icon>
            <Target :size="20" />
          </template>
        </HealthMetricCard>
      </section>

      <!-- Trend Chart + Paired Accessible Breakdown Table (PRD §5.5 & UI-T22) -->
      <ChartWithDataTable :series="report.daily_series || []" />
    </template>
  </div>
</template>

<style scoped>
.hl-week-period {
  padding: 6px 12px;
  border-radius: var(--hl-radius-sm);
  background: var(--hl-canvas);
  border: 1px solid var(--hl-border);
}

.hl-week-dates {
  font-size: var(--hl-body);
  font-weight: 650;
  color: var(--hl-text);
}
</style>
