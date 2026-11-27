<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ExternalLink, HeartPulse } from 'lucide-vue-next'
import { apiRequest, ApiClientError } from '../api/client'
import { sanitizeExternalHttpsUrl, useAuthStore } from '../stores/auth'
import { formatLocalDateToday } from '../utils/format'
import type { EcgLink, EcgPeriod, EcgSummary } from '../types/ecg'
import PageHeader from '../components/common/PageHeader.vue'
import HealthMetricCard from '../components/common/HealthMetricCard.vue'
import EcgTrend from '../components/common/EcgTrend.vue'
import EcgMeasurementPanel from '../components/common/EcgMeasurementPanel.vue'
import { clearPendingMeasurement } from '../utils/ecgPending'
import ConfirmDialog from '../components/common/ConfirmDialog.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import HlAlert from '../components/ui/HlAlert.vue'

const auth = useAuthStore()
const link = ref<EcgLink | null>(null)
const summary = ref<EcgSummary | null>(null)
const loading = ref(false)
const summaryLoading = ref(false)
const actionBusy = ref(false)
const error = ref('')
const summaryError = ref('')
const notice = ref('')
const code = ref('')
const consent = ref(false)
const revokeDialog = ref(false)
const period = ref<EcgPeriod>('day')
const anchor = ref(formatLocalDateToday(auth.user?.timezone))
const periods: Array<{ value: EcgPeriod; label: string }> = [{ value: 'day', label: '日' }, { value: 'month', label: '月' }, { value: 'year', label: '年' }]
let generation = 0
let summarySequence = 0
let requestController: AbortController | null = null
let summaryController: AbortController | null = null

const ecgUrl = computed(() => sanitizeExternalHttpsUrl(link.value?.ecg_url) || auth.safeEcgExternalUrl)
const connectUrl = computed(() => ecgUrl.value ? new URL('/heartlife-connect', ecgUrl.value).toString() : null)
const linked = computed(() => Boolean(link.value?.linked && !link.value.revocation_pending))
const dateLabel = computed(() => period.value === 'day' ? '选择日期' : period.value === 'month' ? '选择月份' : '选择年份')
const dateInputType = computed(() => period.value === 'month' ? 'month' : period.value === 'year' ? 'number' : 'date')
const dateInputValue = computed(() => period.value === 'month' ? anchor.value.slice(0, 7) : period.value === 'year' ? anchor.value.slice(0, 4) : anchor.value)
const periodLabel = computed(() => period.value === 'day' ? anchor.value : period.value === 'month' ? anchor.value.slice(0, 7) : anchor.value.slice(0, 4))

function stopRequests() {
  generation += 1
  summarySequence += 1
  requestController?.abort()
  summaryController?.abort()
  summary.value = null
  summaryLoading.value = false
}

function context() { return { generation, userId: auth.user?.id } }
function isCurrent(ctx: ReturnType<typeof context>) { return ctx.generation === generation && Boolean(ctx.userId) && ctx.userId === auth.user?.id }
function errorText(err: unknown) { return err instanceof ApiClientError ? err.message : '暂时无法连接，请稍后重试。' }
function aborted(err: unknown) { return err instanceof Error && err.name === 'AbortError' }

async function loadLink() {
  if (!auth.user || actionBusy.value) return
  stopRequests()
  const ctx = context()
  requestController = new AbortController()
  link.value = null
  loading.value = true
  error.value = ''
  summaryError.value = ''
  try {
    const data = await apiRequest<EcgLink>('/me/ecg/link', { signal: requestController.signal })
    if (!isCurrent(ctx)) return
    link.value = data
    if (!data.linked || data.revocation_pending || !data.measurement_allowed) clearPendingMeasurement(auth.user?.id)
    if (data.enabled && data.linked && !data.revocation_pending) void loadSummary()
  } catch (err) {
    if (isCurrent(ctx) && !aborted(err)) error.value = errorText(err)
  } finally {
    if (isCurrent(ctx)) loading.value = false
  }
}

async function loadSummary() {
  if (!linked.value || !link.value?.enabled || actionBusy.value || !auth.user) return
  const ctx = context()
  const seq = ++summarySequence
  summaryController?.abort()
  summaryController = new AbortController()
  summary.value = null
  summaryError.value = ''
  summaryLoading.value = true
  try {
    const data = await apiRequest<EcgSummary>('/me/ecg/summary', {
      signal: summaryController.signal, params: { period: period.value, anchor: anchor.value },
    })
    if (isCurrent(ctx) && seq === summarySequence && linked.value) {
      summary.value = data
      if (link.value && data.measurement_allowed !== undefined) link.value.measurement_allowed = data.measurement_allowed
    }
  } catch (err) {
    if (isCurrent(ctx) && seq === summarySequence && !aborted(err)) summaryError.value = errorText(err)
  } finally {
    if (isCurrent(ctx) && seq === summarySequence) summaryLoading.value = false
  }
}

async function bind() {
  if (!auth.user || !consent.value || !code.value.trim() || actionBusy.value || !link.value?.enabled || linked.value || link.value.revocation_pending) return
  stopRequests()
  const ctx = context()
  requestController = new AbortController()
  actionBusy.value = true
  error.value = ''
  notice.value = ''
  try {
    const data = await apiRequest<EcgLink>('/me/ecg/link', { method: 'POST', body: { code: code.value.trim() }, signal: requestController.signal })
    if (!isCurrent(ctx)) return
    link.value = data
    code.value = ''
    consent.value = false
    notice.value = '已关联。请核对下方心电账号。'
  } catch (err) {
    if (isCurrent(ctx) && !aborted(err)) {
      error.value = errorText(err)
      // An exchange timeout may have created a pending authorization remotely.
      // Re-read the local status before offering another binding attempt.
      if (link.value && (!(err instanceof ApiClientError) || err.status >= 500)) {
        link.value = { ...link.value, linked: false, revocation_pending: true }
      }
      try {
        const status = await apiRequest<EcgLink>('/me/ecg/link', { signal: requestController?.signal })
        if (isCurrent(ctx)) {
          link.value = status
          if (status.linked || status.revocation_pending) { code.value = ''; consent.value = false }
        }
      } catch { /* Keep the pending state when the status cannot be confirmed. */ }
    }
  } finally {
    if (isCurrent(ctx)) {
      actionBusy.value = false
      if (linked.value) void loadSummary()
    }
  }
}

async function revoke() {
  if (!auth.user || actionBusy.value || !link.value) return
  clearPendingMeasurement(auth.user.id)
  stopRequests()
  const ctx = context()
  requestController = new AbortController()
  actionBusy.value = true
  error.value = ''
  summaryError.value = ''
  notice.value = ''
  // Never display a delayed summary after the user has requested disconnection.
  code.value = ''
  consent.value = false
  link.value = { ...link.value, linked: false, revocation_pending: true }
  try {
    const data = await apiRequest<{ linked: false; revocation_pending: boolean }>('/me/ecg/link', { method: 'DELETE', signal: requestController.signal })
    if (!isCurrent(ctx)) return
    link.value = { ...link.value, ...data, ecg_username: data.revocation_pending ? link.value.ecg_username : null, expires_at: null }
    if (!data.revocation_pending) notice.value = '已解除关联，心电平台的原始记录仍保留。'
  } catch (err) {
    if (isCurrent(ctx) && !aborted(err)) error.value = errorText(err)
  } finally {
    if (isCurrent(ctx)) { actionBusy.value = false; revokeDialog.value = false }
  }
}

function selectPeriod(value: EcgPeriod) { if (period.value !== value) { period.value = value; void loadSummary() } }
function changeDate(event: Event) {
  const value = (event.target as HTMLInputElement).value
  const next = period.value === 'year' ? `${value}-01-01` : period.value === 'month' ? `${value}-01` : value
  if (!/^\d{4}-\d{2}-\d{2}$/.test(next) || next.slice(0, 4) < '1900' || next.slice(0, 4) > '2100') return
  anchor.value = next
  void loadSummary()
}
function timestamp(value: string | number) {
  const date = new Date(typeof value === 'number' ? value * 1000 : value)
  if (Number.isNaN(date.getTime())) return '时间未知'
  return new Intl.DateTimeFormat('zh-CN', { timeZone: auth.user?.timezone || 'Asia/Shanghai', dateStyle: 'short', timeStyle: 'short' }).format(date)
}
function reportUrl(raw: string | null | undefined) {
  if (!raw || !ecgUrl.value) return null
  try {
    const url = new URL(raw)
    const base = new URL(ecgUrl.value)
    if (url.protocol !== 'https:' || url.origin !== base.origin || url.username || url.password) return null
    return url.toString()
  } catch { return null }
}

watch(() => auth.user?.id, () => {
  stopRequests()
  link.value = null
  code.value = ''
  consent.value = false
  revokeDialog.value = false
  error.value = ''
  summaryError.value = ''
  notice.value = ''
  actionBusy.value = false
  loading.value = false
  period.value = 'day'
  anchor.value = formatLocalDateToday(auth.user?.timezone)
  if (auth.user) void loadLink()
}, { immediate: true, flush: 'sync' })
onBeforeUnmount(stopRequests)
</script>

<template>
  <div class="stack ecg-page">
    <PageHeader title="我的心电记录" subtitle="查看本人测量摘要与趋势，授权后可发起测量。" back-to="/" back-label="返回首页">
      <template #actions>
        <a v-if="ecgUrl" :href="ecgUrl" target="_blank" rel="noopener noreferrer" class="btn btn-secondary">
          <ExternalLink :size="18" aria-hidden="true" />打开心电工作台
        </a>
      </template>
    </PageHeader>
    <LoadingState v-if="loading" :count="2" />
    <ErrorState v-else-if="!link && error" title="暂时无法读取关联状态" :message="error" show-home-link @retry="loadLink" />
    <template v-else-if="link">
      <HlAlert v-if="notice" variant="success">{{ notice }}</HlAlert>
      <HlAlert v-if="error" variant="error">{{ error }}</HlAlert>

      <section v-if="link.revocation_pending" class="hl-card stack-sm" aria-label="撤销待完成">
        <h2 class="section-title">授权状态待确认</h2>
        <p>当前不展示心电摘要。请稍后重试解除关联，或前往心电平台撤销授权。</p>
        <button class="btn btn-secondary" type="button" :disabled="actionBusy" @click="revoke">{{ actionBusy ? '正在撤销…' : '重试撤销' }}</button>
      </section>
      <section v-else-if="!link.enabled" class="hl-card stack-sm">
        <h2 class="section-title">心电摘要尚未开放</h2>
        <p>目前可在独立心电工作台登录并查看记录。</p>
      </section>
      <section v-else-if="!linked" class="hl-card stack" aria-label="关联本人心电账号">
        <div class="row-wrap"><HeartPulse :size="24" aria-hidden="true" /><h2 class="section-title">关联本人心电账号</h2></div>
        <p>先在心电平台登录本人账号并生成关联码，再回到这里完成关联。关联码 5 分钟内有效。</p>
        <a v-if="connectUrl" :href="connectUrl" target="_blank" rel="noopener noreferrer" class="btn btn-secondary">前往获取关联码</a>
        <form class="stack" @submit.prevent="bind">
          <div class="field">
            <label class="field-label" for="ecg-link-code">一次性关联码</label>
            <input id="ecg-link-code" v-model="code" class="input tabular" type="text" autocomplete="off" autocapitalize="none" spellcheck="false" maxlength="256" :disabled="actionBusy" required />
          </div>
          <label class="checkbox-label">
            <input v-model="consent" type="checkbox" :disabled="actionBusy" required />
            <span>这是我本人的心电账号，同意心伴展示摘要和趋势。测量权限以心电平台的单独授权为准，可随时解除关联。</span>
          </label>
          <button type="submit" class="btn btn-primary" :disabled="actionBusy || !consent || !code.trim()">{{ actionBusy ? '正在关联…' : '确认关联' }}</button>
        </form>
      </section>
      <template v-else>
        <section class="hl-card row-between" aria-label="已关联的心电账号">
          <div class="stack-sm"><h2 class="section-title">心电账号：{{ link.ecg_username }}</h2>
            <p class="text-sm hl-muted">仅本人查看 · {{ link.measurement_allowed ? '已授权固定时长测量' : '只读摘要' }}<span v-if="link.expires_at"> · 授权至 {{ timestamp(link.expires_at) }}</span></p>
          </div>
          <button type="button" class="btn btn-secondary" :disabled="actionBusy" @click="revokeDialog = true">解除关联</button>
        </section>
        <EcgMeasurementPanel :measurement-allowed="link.measurement_allowed === true" :ecg-url="ecgUrl" :connect-url="connectUrl" :authorization-expires-at="link.expires_at" @completed="loadSummary" />
        <section class="hl-card stack-sm" aria-label="心电趋势筛选">
          <div class="row-between">
            <div class="row-wrap" role="group" aria-label="统计周期">
              <button v-for="item in periods" :key="item.value" type="button" class="pill" :class="{ 'pill-active': period === item.value }" :aria-pressed="period === item.value" @click="selectPeriod(item.value)">{{ item.label }}</button>
            </div>
            <button type="button" class="btn btn-soft" :disabled="summaryLoading" @click="loadSummary">刷新摘要</button>
          </div>
          <div class="field ecg-date"><label for="ecg-date" class="field-label">{{ dateLabel }}</label>
            <input id="ecg-date" class="input" :type="dateInputType" :value="dateInputValue" :min="period === 'year' ? 1900 : undefined" :max="period === 'year' ? 2100 : undefined" @change="changeDate" />
          </div>
        </section>
        <LoadingState v-if="summaryLoading" :count="2" />
        <ErrorState v-else-if="summaryError" title="心电摘要暂不可用" :message="summaryError" @retry="loadSummary" />
        <template v-else-if="summary">
          <section class="grid-2" aria-label="本期心电统计">
            <HealthMetricCard label="测量记录" :value="summary.trends.total_records" unit="条" :subtext="periodLabel" />
            <HealthMetricCard label="累计采样时长" :value="summary.trends.total_duration_s" unit="秒" :subtext="periodLabel" />
          </section>
          <p v-if="summary.trends.total_records === 0" class="hl-muted" role="status">该时段暂无已上传完成的心电记录。</p>
          <EcgTrend :buckets="summary.trends.buckets" :period="period" />
          <p class="text-sm hl-muted">{{ summary.trends.note }}</p>
          <section class="hl-card stack" aria-label="最近心电记录">
            <h2 class="section-title">最近记录</h2>
            <p class="text-sm hl-muted">最近 5 条已上传完成的记录。详细波形、分析进度和报告在心电工作台查看，需独立登录。</p>
            <p v-if="!summary.recent_records.length" class="hl-muted">暂无记录</p>
            <ul v-else class="ecg-records">
              <li v-for="record in summary.recent_records" :key="record.session_id" class="ecg-record stack-sm">
                <div class="row-between"><strong>{{ timestamp(record.started_utc) }}</strong>
                  <a v-if="reportUrl(record.report_url)" :href="reportUrl(record.report_url)!" target="_blank" rel="noopener noreferrer" class="btn btn-soft">查看记录与报告</a>
                </div>
                <div class="row-wrap text-sm"><span>采样 {{ record.duration_s }} 秒</span><span>{{ record.hr_mean == null ? '暂无心率数据' : `平均心率 ${record.hr_mean} 次/分` }}</span></div>
                <span class="text-sm hl-muted ecg-record-id">记录编号：{{ record.session_id }}</span>
              </li>
            </ul>
          </section>
        </template>
      </template>
    </template>
    <ConfirmDialog v-model:open="revokeDialog" title="解除心电账号关联" description="心伴将停止读取摘要和发起测量。已经下发的测量仍可能继续，原始记录不会删除。" confirm-label="确认解除" danger :loading="actionBusy" @confirm="revoke" />
  </div>
</template>

<style scoped>
.ecg-page { min-width: 0; }
p { margin: 0; }
.ecg-date { max-width: 20rem; }
.ecg-date input { width: 100%; min-width: 0; }
.ecg-records { padding: 0; margin: 0; list-style: none; }
.ecg-record { padding: 16px 0; border-top: 1px solid var(--hl-border); }
.ecg-record-id { overflow-wrap: anywhere; }
</style>
