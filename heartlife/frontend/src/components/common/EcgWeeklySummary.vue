<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { apiRequest, ApiClientError } from '../../api/client'
import { useAuthStore } from '../../stores/auth'
import type { EcgWeeklySummaryData } from '../../types/ecg'
import HealthMetricCard from './HealthMetricCard.vue'

const props = defineProps<{ weekStart: string }>()
const auth = useAuthStore()
const summary = ref<EcgWeeklySummaryData | null>(null)
const loading = ref(false)
const error = ref('')
const unlinked = ref(false)
let sequence = 0
let controller: AbortController | null = null

async function load() {
  const seq = ++sequence
  const userId = auth.user?.id
  const week = props.weekStart
  controller?.abort()
  controller = new AbortController()
  summary.value = null
  error.value = ''
  unlinked.value = false
  loading.value = Boolean(userId)
  if (!userId) return
  const current = () => seq === sequence && auth.user?.id === userId && props.weekStart === week
  try {
    const data = await apiRequest<EcgWeeklySummaryData>('/me/ecg/weekly-summary', { params: { week_start: week }, signal: controller.signal })
    if (current()) summary.value = data
  } catch (err) {
    if (!current() || (err instanceof Error && err.name === 'AbortError')) return
    error.value = err instanceof ApiClientError ? err.message : '暂时无法加载心电周报，请稍后重试。'
    unlinked.value = err instanceof ApiClientError && ['ECG_NOT_LINKED', 'ECG_LINK_REQUIRED', 'ECG_LINK_EXPIRED', 'ECG_LINK_PENDING'].includes(err.code)
  } finally { if (current()) loading.value = false }
}
watch(() => [props.weekStart, auth.user?.id, auth.user?.timezone], () => { void load() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { sequence += 1; controller?.abort() })
</script>

<template>
  <section v-if="auth.user" class="hl-card stack no-print ecg-weekly" aria-label="本人心电周报">
    <div class="row-between"><h2 class="section-title">本周心电记录</h2><span class="text-sm hl-muted">仅本人可见</span></div>
    <p class="text-sm hl-muted">{{ weekStart }} 起的一周 · 不加入家庭共享或生活周报打印。</p>
    <p v-if="loading" role="status">正在读取心电记录…</p>
    <div v-else-if="error" class="stack-sm">
      <p role="status">{{ error }}</p>
      <RouterLink v-if="unlinked" to="/ecg" class="btn btn-secondary">管理心电关联</RouterLink>
      <button v-else type="button" class="btn btn-secondary" @click="load">重试心电周报</button>
    </div>
    <template v-else-if="summary">
      <div class="weekly-metrics">
        <HealthMetricCard label="测量记录" :value="summary.total_records" unit="条" />
        <HealthMetricCard label="累计采样" :value="summary.total_duration_s" unit="秒" />
        <HealthMetricCard label="平均心率" :value="summary.hr_mean" unit="次/分" empty-text="暂无心率数据" :subtext="`有心率摘要 ${summary.hr_records} 条`" />
      </div>
      <p v-if="summary.total_records === 0" role="status">这周暂无已上传完成的心电记录。</p>
      <details v-else>
        <summary>查看每天的测量记录</summary>
        <div class="table-wrap"><table class="data-table" aria-label="本周心电记录明细">
          <thead><tr><th scope="col">日期</th><th scope="col">记录</th><th scope="col">时长（秒）</th><th scope="col">心率（次/分）</th></tr></thead>
          <tbody><tr v-for="(day, index) in summary.daily_series" :key="day.date"><th scope="row">{{ day.date.slice(5) }}</th><template v-if="index < summary.observed_days"><td>{{ day.records }}</td><td>{{ day.duration_s }}</td><td>{{ day.hr_mean == null ? '暂无数据' : day.hr_mean }}</td></template><td v-else colspan="3">尚未到达</td></tr></tbody>
        </table></div>
      </details>
      <p class="text-sm hl-muted">按 {{ summary.timezone }} 的本地日期汇总，截至{{ summary.observed_days < 7 ? '今日' : '周日' }}。心率来自终端质量合格窗口，缺失数据不作为 0 计算。</p>
      <RouterLink to="/ecg" class="btn btn-soft">查看心电趋势与报告</RouterLink>
    </template>
  </section>
</template>

<style scoped>
.ecg-weekly { min-width: 0; }
p { margin: 0; overflow-wrap: anywhere; }
.weekly-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.table-wrap { max-width: 100%; overflow-x: auto; }
summary { min-height: 48px; padding: 12px 0; cursor: pointer; font-weight: 600; }
@media (max-width: 700px) { .weekly-metrics { grid-template-columns: minmax(0, 1fr); } }
</style>
