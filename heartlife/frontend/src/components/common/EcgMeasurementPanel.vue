<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiRequest, ApiClientError } from '../../api/client'
import { useAuthStore } from '../../stores/auth'
import { clearPendingMeasurement, readPendingMeasurement, savePendingMeasurement } from '../../utils/ecgPending'
import type { EcgAnalysisStatus, EcgDevice, EcgDevices, EcgMeasurement, EcgMeasurementRequest, EcgMeasurementResult, EcgMeasurements, EcgMeasurementStatus } from '../../types/ecg'

const props = defineProps<{ measurementAllowed: boolean; ecgUrl: string | null; connectUrl: string | null; authorizationExpiresAt?: number | null }>()
const emit = defineEmits<{ completed: [] }>()
const auth = useAuthStore()
const devices = ref<EcgDevice[]>([])
const measurements = ref<EcgMeasurement[]>([])
const deviceId = ref('')
const duration = ref<60 | 180 | 300>(60)
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const denied = ref(false)
const offline = ref(typeof navigator !== 'undefined' && !navigator.onLine)
const pending = ref<EcgMeasurementRequest | null>(null)
const canRestore = ref(true)
let generation = 0
let readSequence = 0
let readController: AbortController | null = null
let postController: AbortController | null = null
let pollTimer: ReturnType<typeof setTimeout> | undefined
let postTimer: ReturnType<typeof setTimeout> | undefined
const allowed = computed(() => Boolean(auth.user && props.measurementAllowed && !denied.value))
const selectedDevice = computed(() => devices.value.find((device) => device.device_id === deviceId.value))
const activeStatuses = new Set<EcgMeasurementStatus>(['queued', 'accepted', 'recording', 'uploading'])
const activeWork = computed(() => measurements.value.some((item) => activeStatuses.has(item.status) || [item.report.model, item.report.physiology].some((state) => state === 'queued' || state === 'running')))
const selectedBusy = computed(() => measurements.value.some((item) => item.device_id === deviceId.value && activeStatuses.has(item.status)))
const canStart = computed(() => allowed.value && !loading.value && !submitting.value && !pending.value && !offline.value && selectedDevice.value?.online && selectedDevice.value.ready && !selectedBusy.value)
const statusLabels: Record<EcgMeasurementStatus, string> = { queued: '等待终端领取', accepted: '终端已接受', recording: '正在采集', uploading: '正在上传', completed: '上传完成', expired: '请求已过期', failed: '测量未完成' }
const analysisLabels: Record<EcgAnalysisStatus, string> = { not_started: '尚未分析', queued: '等待分析', running: '正在分析', completed: '分析完成', failed: '分析失败', ineligible: '不满足分析条件' }

function currentContext() { return { generation, userId: auth.user?.id } }
function current(ctx: ReturnType<typeof currentContext>) { return ctx.generation === generation && Boolean(ctx.userId) && ctx.userId === auth.user?.id && allowed.value }
function stopPolling() { if (pollTimer !== undefined) clearTimeout(pollTimer); pollTimer = undefined }
function visible() { return typeof document === 'undefined' || !document.hidden }
function reset() {
  generation += 1
  readSequence += 1
  stopPolling()
  readController?.abort()
  postController?.abort()
  if (postTimer !== undefined) clearTimeout(postTimer)
  postTimer = undefined
  devices.value = []
  measurements.value = []
  deviceId.value = ''
  duration.value = 60
  pending.value = null
  canRestore.value = true
  loading.value = false
  submitting.value = false
  error.value = ''
  denied.value = false
}
function handleError(err: unknown) {
  error.value = err instanceof ApiClientError ? err.message : '暂时无法连接心电服务，请稍后重试。'
  if (err instanceof ApiClientError && (err.status === 401 || err.status === 403 || ['ECG_LINK_EXPIRED', 'ECG_LINK_CHANGED', 'ECG_NOT_LINKED'].includes(err.code))) {
    denied.value = true
    devices.value = []
    measurements.value = []
    pending.value = null
    clearPendingMeasurement(auth.user?.id)
    stopPolling()
  }
}
function schedulePoll() {
  stopPolling()
  if (allowed.value && activeWork.value && !offline.value && visible()) pollTimer = setTimeout(() => { void refresh() }, 4000)
}
function recheckPermission() {
  // Re-read only; a denied POST is never replayed automatically.
  denied.value = false
  void refresh()
}
async function refresh() {
  if (!allowed.value || offline.value || !visible() || submitting.value) return
  const ctx = currentContext()
  const seq = ++readSequence
  readController?.abort()
  readController = new AbortController()
  loading.value = true
  if (!pending.value) error.value = ''
  try {
    const [deviceData, measurementData] = await Promise.all([
      apiRequest<EcgDevices>('/me/ecg/devices', { signal: readController.signal }),
      apiRequest<EcgMeasurements>('/me/ecg/measurements', { signal: readController.signal }),
    ])
    if (!current(ctx) || seq !== readSequence) return
    if (!deviceData.measurement_allowed || !measurementData.measurement_allowed) {
      handleError(new ApiClientError(403, 'ECG_MEASUREMENT_FORBIDDEN', '测量授权已失效，请重新关联。'))
      return
    }
    const newlyUploaded = measurementData.measurements.some((item) => item.status === 'completed' && measurements.value.some((old) => old.id === item.id && old.status !== 'completed'))
    devices.value = deviceData.devices
    measurements.value = measurementData.measurements
    if (newlyUploaded) emit('completed')
    if (deviceId.value && !devices.value.some((device) => device.device_id === deviceId.value) && !pending.value) deviceId.value = ''
  } catch (err) {
    if (current(ctx) && seq === readSequence && !(err instanceof Error && err.name === 'AbortError')) handleError(err)
  } finally {
    if (ctx.generation === generation && seq === readSequence) { loading.value = false; schedulePoll() }
  }
}
function requestKey() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
async function submit(retry = false) {
  if (!allowed.value || offline.value || submitting.value || (retry ? !pending.value : !canStart.value)) return
  if (!retry) {
    try { pending.value = { device_id: deviceId.value, duration_s: duration.value, request_key: requestKey() } }
    catch { error.value = '当前浏览器无法创建测量请求，请更新浏览器后重试。'; return }
    canRestore.value = savePendingMeasurement(auth.user!.id, props.authorizationExpiresAt ?? null, pending.value)
  }
  const payload = pending.value!
  const ctx = currentContext()
  stopPolling()
  readSequence += 1
  readController?.abort()
  loading.value = false
  postController = new AbortController()
  let timedOut = false
  const controller = postController
  postTimer = setTimeout(() => { timedOut = true; controller.abort() }, 15000)
  submitting.value = true
  error.value = ''
  try {
    const data = await apiRequest<EcgMeasurementResult>('/me/ecg/measurements', { method: 'POST', body: payload, signal: controller.signal })
    if (!current(ctx)) return
    const item = data?.measurement
    if (!data?.measurement_allowed || !item || typeof item.id !== 'string' || !item.id || item.device_id !== payload.device_id || item.duration_s !== payload.duration_s || !(item.status in statusLabels) || !item.report || !(item.report.model in analysisLabels) || !(item.report.physiology in analysisLabels)) {
      throw new ApiClientError(502, 'ECG_INVALID_RESPONSE', '尚未确认测量结果，请重试同一次测量。')
    }
    pending.value = null
    clearPendingMeasurement(auth.user?.id)
    measurements.value = [data.measurement, ...measurements.value.filter((item) => item.id !== data.measurement.id)].slice(0, 10)
  } catch (err) {
    if (!current(ctx)) return
    handleError(err)
    if (timedOut) error.value = '尚未确认是否收到请求，请重试同一次测量。'
    // 5xx, network failure or a client timeout may follow a committed request.
    // Keep the exact key and parameters until the server acknowledges it.
    if (err instanceof ApiClientError && err.status < 500 && err.status !== 408) { pending.value = null; clearPendingMeasurement(auth.user?.id) }
  } finally {
    if (ctx.generation === generation) {
      if (postTimer !== undefined) clearTimeout(postTimer)
      postTimer = undefined
      submitting.value = false
      schedulePoll()
    }
  }
}
function safeReportUrl(item: EcgMeasurement) {
  if (!item.report_url || !props.ecgUrl || item.status !== 'completed') return null
  try {
    const url = new URL(item.report_url)
    const base = new URL(props.ecgUrl)
    if (url.protocol !== 'https:' || url.origin !== base.origin || url.username || url.password || url.pathname !== '/' || url.searchParams.get('record') !== item.session_id) return null
    return url.toString()
  } catch { return null }
}
function timestamp(value: number) {
  return new Intl.DateTimeFormat('zh-CN', { timeZone: auth.user?.timezone || 'Asia/Shanghai', dateStyle: 'short', timeStyle: 'short' }).format(new Date(value * 1000))
}
function resume() {
  offline.value = !navigator.onLine
  stopPolling()
  if (visible() && !offline.value) void refresh()
  else { readSequence += 1; readController?.abort(); loading.value = false }
}
watch(() => [auth.user?.id, props.measurementAllowed, props.authorizationExpiresAt] as const, (_next, previous) => {
  if (previous?.[0] && (previous[0] !== auth.user?.id || !props.measurementAllowed || previous[2] !== props.authorizationExpiresAt)) clearPendingMeasurement(previous[0])
  reset()
  if (allowed.value) {
    pending.value = readPendingMeasurement(auth.user!.id, props.authorizationExpiresAt ?? null)
    if (pending.value) { deviceId.value = pending.value.device_id; duration.value = pending.value.duration_s }
    void refresh()
  }
}, { immediate: true, flush: 'sync' })
onMounted(() => { document.addEventListener('visibilitychange', resume); window.addEventListener('online', resume); window.addEventListener('offline', resume) })
onBeforeUnmount(() => { reset(); document.removeEventListener('visibilitychange', resume); window.removeEventListener('online', resume); window.removeEventListener('offline', resume) })
</script>

<template>
  <section v-if="auth.user" class="hl-card stack ecg-measurement" aria-label="固定时长心电测量">
    <div class="row-between"><h2 class="section-title">开始一次测量</h2><button v-if="allowed" class="btn btn-soft" type="button" :disabled="loading || submitting || offline" @click="refresh">{{ loading ? '正在刷新…' : '刷新设备与进度' }}</button></div>
    <template v-if="!measurementAllowed">
      <p>当前关联仅允许读取摘要。需要远程测量时，请在心电平台解除旧关联，重新勾选测量权限并绑定。</p>
      <a v-if="connectUrl" :href="connectUrl" target="_blank" rel="noopener noreferrer" class="btn btn-secondary">前往管理心电授权</a>
    </template>
    <p v-if="error" class="measurement-error" role="alert">{{ error }}</p>
    <div v-if="denied" class="stack-sm">
      <button type="button" class="btn btn-secondary" :disabled="offline" @click="recheckPermission">重新检查测量权限</button>
      <a v-if="connectUrl" :href="connectUrl" target="_blank" rel="noopener noreferrer" class="btn btn-soft">管理心电授权</a>
    </div>
    <p v-if="offline" role="status">当前网络已断开，恢复连接后可刷新进度。</p>
    <template v-if="allowed">
      <p class="text-sm hl-muted">佩戴好电极，在终端确认本人账号并进入待机。测量由采集终端执行。</p>
      <form class="stack-sm" @submit.prevent="submit()">
        <div class="measure-fields">
          <div class="field"><label class="field-label" for="ecg-measure-device">采集设备</label>
            <select id="ecg-measure-device" v-model="deviceId" class="input" :disabled="submitting || Boolean(pending) || loading || offline" required>
              <option value="">请选择已就绪设备</option>
              <option v-for="device in devices" :key="device.device_id" :value="device.device_id" :disabled="!device.online || !device.ready">{{ device.label || device.device_id }}{{ device.ready && device.online ? '' : ` · ${device.reason || '暂不可测量'}` }}</option>
            </select>
          </div>
          <div class="field"><label class="field-label" for="ecg-measure-duration">测量时长</label>
            <select id="ecg-measure-duration" v-model.number="duration" class="input" :disabled="submitting || Boolean(pending)"><option :value="60">1 分钟</option><option :value="180">3 分钟</option><option :value="300">5 分钟</option></select>
          </div>
        </div>
        <p v-if="!loading && !devices.length" class="hl-muted">暂无已授权设备，请联系管理员开通设备权限。</p>
        <p v-if="selectedBusy" class="hl-muted">该设备已有测量任务，请等待完成。</p>
        <button type="submit" class="btn btn-primary" :disabled="!canStart">{{ submitting ? '正在提交…' : '开始测量' }}</button>
      </form>
      <div v-if="pending && !submitting" class="stack-sm" role="status">
        <p>请求结果尚未确认，重试会沿用同一个请求编号，不会重复发起采集。</p>
        <p v-if="!canRestore" class="text-sm hl-muted">浏览器未允许保存待确认请求，请留在此页完成确认。</p>
        <button type="button" class="btn btn-secondary" :disabled="offline" @click="submit(true)">重试同一次测量</button>
      </div>
      <section v-if="measurements.length" class="stack-sm" aria-label="最近测量进度">
        <h3 class="section-title">最近测量</h3>
        <ol class="measurement-list">
          <li v-for="item in measurements" :key="item.id" class="measurement-item stack-sm">
            <div class="row-between"><strong aria-live="polite">{{ statusLabels[item.status] }}</strong><span class="text-sm">{{ item.duration_s / 60 }} 分钟</span></div>
            <p class="text-sm hl-muted">{{ devices.find((device) => device.device_id === item.device_id)?.label || item.device_id }} · {{ timestamp(item.created_at) }}</p>
            <p v-if="item.message" class="text-sm">{{ item.message }}</p>
            <template v-if="item.status === 'completed'">
              <p class="text-sm">心搏分类：{{ analysisLabels[item.report.model] }} · QRS / RR：{{ analysisLabels[item.report.physiology] }}</p>
              <a v-if="safeReportUrl(item)" :href="safeReportUrl(item)!" target="_blank" rel="noopener noreferrer" class="btn btn-soft">查看记录与分析</a>
            </template>
          </li>
        </ol>
        <p class="text-sm hl-muted">上传与分析分别进行；尚未分析时可到心电工作台操作。</p>
      </section>
    </template>
  </section>
</template>

<style scoped>
.ecg-measurement, .field { min-width: 0; }
p { margin: 0; overflow-wrap: anywhere; }
.measure-fields { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: 16px; }
select { width: 100%; min-width: 0; text-overflow: ellipsis; }
.measurement-list { list-style: none; margin: 0; padding: 0; }
.measurement-item { padding: 16px 0; border-top: 1px solid var(--hl-border); }
.measurement-error { color: var(--hl-danger, #b42318); }
@media (max-width: 560px) { .measure-fields { grid-template-columns: minmax(0, 1fr); } }
</style>
