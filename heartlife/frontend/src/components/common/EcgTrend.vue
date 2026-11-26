<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { EcgBucket, EcgPeriod } from '../../types/ecg'

const props = defineProps<{ buckets: EcgBucket[]; period: EcgPeriod }>()
const chartContainer = ref<HTMLElement | null>(null)
const chartWidth = ref(736)
let observer: ResizeObserver | null = null
onMounted(() => {
  const updateWidth = () => {
    const width = chartContainer.value?.clientWidth
    if (width) chartWidth.value = Math.max(240, width)
  }
  updateWidth()
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(updateWidth)
    if (chartContainer.value) observer.observe(chartContainer.value)
  }
})
onBeforeUnmount(() => observer?.disconnect())
const numeric = (v: number | null | undefined): v is number => typeof v === 'number' && Number.isFinite(v)
const values = computed(() => props.buckets.flatMap((b) => numeric(b.hr_mean) ? [b.hr_mean] : []))
const min = computed(() => values.value.length ? Math.max(0, Math.floor((Math.min(...values.value) - 5) / 10) * 10) : 0)
const max = computed(() => values.value.length ? Math.max(min.value + 20, Math.ceil((Math.max(...values.value) + 5) / 10) * 10) : 100)
const ticks = computed(() => [min.value, (min.value + max.value) / 2, max.value])
const x = (i: number) => 52 + i * (chartWidth.value - 96) / Math.max(1, props.buckets.length - 1)
const y = (v: number) => 184 - (v - min.value) / (max.value - min.value) * 144
const segments = computed(() => {
  const result: string[] = []
  let segment: string[] = []
  props.buckets.forEach((b, i) => {
    if (numeric(b.hr_mean)) segment.push(`${x(i)},${y(b.hr_mean)}`)
    else if (segment.length) { result.push(segment.join(' ')); segment = [] }
  })
  if (segment.length) result.push(segment.join(' '))
  return result
})
const labels = computed(() => props.buckets.map((bucket, index) => ({ bucket, index })).filter(({ index }) =>
  index % Math.max(1, Math.ceil(props.buckets.length / (chartWidth.value < 500 ? 3 : 6))) === 0 || index === props.buckets.length - 1))
const periodUnit = computed(() => props.period === 'day' ? '时刻' : props.period === 'month' ? '日' : '月')
</script>

<template>
  <section class="hl-card stack" aria-label="心率趋势与明细">
    <h2 class="section-title">心率趋势</h2>
    <p class="text-sm hl-muted">来自终端质量合格窗口的平均心率，缺失区间不连线。</p>
    <div ref="chartContainer" class="ecg-chart-container">
    <svg v-if="values.length" class="ecg-chart" :viewBox="`0 0 ${chartWidth} 230`" role="img" aria-label="平均心率趋势，单位为次每分钟；完整数值见下方明细">
      <title>平均心率趋势</title>
      <text x="52" y="18" class="axis-label">次/分</text>
      <g v-for="tick in ticks" :key="tick">
        <line x1="52" :y1="y(tick)" :x2="chartWidth - 44" :y2="y(tick)" class="grid-line" />
        <text x="44" :y="y(tick) + 5" text-anchor="end" class="axis-label">{{ tick }}</text>
      </g>
      <polyline v-for="(segment, i) in segments" :key="i" :points="segment" fill="none" class="trend-line" />
      <template v-for="(bucket, i) in buckets" :key="bucket.index">
        <circle v-if="numeric(bucket.hr_mean)" :cx="x(i)" :cy="y(bucket.hr_mean)" r="4" class="trend-point">
          <title>{{ bucket.label }}：{{ bucket.hr_mean }} 次/分</title>
        </circle>
      </template>
      <text v-for="{ bucket, index } in labels" :key="index" :x="x(index)" y="211" text-anchor="middle" class="axis-label">{{ bucket.label }}</text>
    </svg>
    <p v-else class="hl-muted" role="status">该时段暂无可用心率统计。</p>
    </div>
    <details>
      <summary>查看统计明细</summary>
      <div class="table-wrap">
        <table class="data-table" aria-label="心电趋势明细">
          <thead><tr><th scope="col">{{ periodUnit }}</th><th scope="col">记录数</th><th scope="col">时长（秒）</th><th scope="col">心率（次/分）</th></tr></thead>
          <tbody>
            <tr v-for="bucket in buckets" :key="bucket.index">
              <th scope="row">{{ bucket.label }}</th><td>{{ bucket.records }}</td><td>{{ bucket.duration_s }}</td>
              <td>{{ numeric(bucket.hr_mean) ? bucket.hr_mean : '暂无数据' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </details>
  </section>
</template>

<style scoped>
p { margin: 0; }
.ecg-chart { display: block; width: 100%; height: auto; min-width: 0; }
.ecg-chart-container { min-width: 0; }
.axis-label { font-size: 16px; fill: var(--hl-text-muted); }
.grid-line { stroke: var(--hl-border); stroke-width: 1; }
.trend-line { stroke: var(--hl-brand); stroke-width: 2; }
.trend-point { fill: var(--hl-brand); }
summary { cursor: pointer; min-height: 48px; padding: 10px 0; font-weight: 600; }
.table-wrap { max-width: 100%; overflow-x: auto; }
</style>
