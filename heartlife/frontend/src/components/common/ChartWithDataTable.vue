<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import { formatMood } from '../../utils/format'
import type { WeeklyReportDailyPoint } from '../../types/api'

use([SVGRenderer, LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent])

const props = defineProps<{
  series: WeeklyReportDailyPoint[]
}>()

const chartWrapRef = ref<HTMLElement | null>(null)
const useInteractiveChart = ref(false)

function syncEchartsSvgA11y() {
  const svg = chartWrapRef.value?.querySelector('svg')
  if (svg) {
    svg.setAttribute('role', 'img')
    svg.setAttribute('aria-label', '每日睡眠与活动分钟柱状趋势图')
  }
}

onMounted(() => {
  const width = chartWrapRef.value?.clientWidth ?? 0
  useInteractiveChart.value = width > 0
  if (useInteractiveChart.value) {
    requestAnimationFrame(syncEchartsSvgA11y)
  }
})

function pointDue(pt: WeeklyReportDailyPoint): number {
  return pt.plans_due ?? pt.due_count ?? 0
}

function pointCompleted(pt: WeeklyReportDailyPoint): number {
  return pt.plans_completed ?? pt.completed_count ?? 0
}

const chartOption = computed(() => {
  const labels = props.series.map((pt) => pt.date.slice(5))
  const sleepValues = props.series.map((pt) =>
    pt.sleep_minutes === null || pt.sleep_minutes === undefined ? null : pt.sleep_minutes
  )
  const activityValues = props.series.map((pt) =>
    pt.activity_minutes === null || pt.activity_minutes === undefined ? null : pt.activity_minutes
  )

  return {
    animation: false,
    tooltip: {
      trigger: 'axis',
      textStyle: { fontSize: 15, color: '#24372F' },
      valueFormatter: (value: unknown) =>
        value === null || value === undefined ? '尚未记录' : `${value} 分钟`,
    },
    legend: {
      top: 4,
      itemWidth: 18,
      itemHeight: 12,
      textStyle: {
        color: '#24372F',
        fontSize: 15,
        fontWeight: 600,
      },
      data: ['睡眠时长（分钟）', '活动时长（分钟）'],
    },
    grid: {
      left: 52,
      right: 28,
      top: 48,
      bottom: 36,
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLine: { lineStyle: { color: '#788B80' } },
      axisLabel: {
        color: '#24372F',
        fontSize: 14,
        margin: 12,
      },
    },
    yAxis: {
      type: 'value',
      min: 0,
      axisLabel: {
        color: '#50645A',
        fontSize: 14,
      },
      splitLine: {
        lineStyle: { color: '#E2E8E1', type: 'dashed' },
      },
    },
    series: [
      {
        name: '睡眠时长（分钟）',
        type: 'line',
        data: sleepValues,
        connectNulls: false,
        symbol: 'circle',
        symbolSize: 10,
        lineStyle: { width: 3, color: '#28664F', type: 'solid' },
        itemStyle: { color: '#28664F' },
      },
      {
        name: '活动时长（分钟）',
        type: 'line',
        data: activityValues,
        connectNulls: false,
        symbol: 'diamond',
        symbolSize: 11,
        lineStyle: { width: 2.5, color: '#AD6235', type: 'dashed' },
        itemStyle: { color: '#AD6235' },
      },
    ],
  }
})
</script>

<template>
  <section class="hl-card stack">
    <div class="row-between">
      <div>
        <h2 class="section-title">每日睡眠与活动趋势</h2>
        <p class="hl-muted text-sm" style="margin: 4px 0 0">
          未记录的日期在折线图中自然留白断开，不会按 0 分钟计入统计。
        </p>
      </div>
    </div>

    <!-- Accessible ECharts SVG Container + Deterministic Vector Fallback -->
    <div ref="chartWrapRef" class="hl-chart-box">
      <VChart
        v-if="useInteractiveChart && series.length > 0"
        class="hl-echart"
        :option="chartOption"
        :init-options="{ renderer: 'svg' }"
        autoresize
        @rendered="syncEchartsSvgA11y"
      />
      <svg
        v-else
        role="img"
        aria-label="每日睡眠与活动分钟柱状趋势图"
        viewBox="0 0 680 180"
        class="hl-fallback-svg"
      >
        <title>每日睡眠与活动分钟柱状趋势图</title>
        <line x1="40" y1="146" x2="650" y2="146" stroke="#788B80" stroke-width="1.5" />
        <template v-for="(pt, idx) in series" :key="pt.date">
          <rect
            v-if="pt.sleep_minutes !== null && pt.sleep_minutes !== undefined"
            :x="56 + idx * 82"
            :y="Math.max(20, 146 - Math.min(120, Math.round((pt.sleep_minutes / 540) * 120)))"
            width="20"
            :height="Math.max(4, Math.min(120, Math.round((pt.sleep_minutes / 540) * 120)))"
            rx="4"
            fill="#28664F"
          />
          <rect
            v-if="pt.activity_minutes !== null && pt.activity_minutes !== undefined"
            :x="80 + idx * 82"
            :y="Math.max(20, 146 - Math.min(120, Math.round((pt.activity_minutes / 90) * 120)))"
            width="20"
            :height="Math.max(4, Math.min(120, Math.round((pt.activity_minutes / 90) * 120)))"
            rx="4"
            fill="#AD6235"
          />
          <text
            :x="78 + idx * 82"
            y="168"
            text-anchor="middle"
            font-size="13"
            fill="#24372F"
          >
            {{ pt.date.slice(5) }}
          </text>
        </template>
      </svg>
    </div>

    <!-- Paired Readable Data Table (Required by PRD §5.5 & UI-T22) -->
    <div class="table-wrap">
      <table class="data-table" aria-label="每日健康记录明细表">
        <thead>
          <tr>
            <th scope="col">日期</th>
            <th scope="col">睡眠时长</th>
            <th scope="col">活动时长</th>
            <th scope="col">当日心情</th>
            <th scope="col">计划完成</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="pt in series" :key="pt.date">
            <td class="tabular">{{ pt.date }}</td>
            <td class="tabular">
              {{
                pt.sleep_minutes !== null && pt.sleep_minutes !== undefined
                  ? `${pt.sleep_minutes} 分钟`
                  : '尚未记录'
              }}
            </td>
            <td class="tabular">
              {{
                pt.activity_minutes !== null && pt.activity_minutes !== undefined
                  ? `${pt.activity_minutes} 分钟`
                  : '尚未记录'
              }}
            </td>
            <td>{{ formatMood(pt.mood) }}</td>
            <td class="tabular">
              {{ pointDue(pt) > 0 ? `${pointCompleted(pt)} / ${pointDue(pt)}` : '无计划' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.hl-chart-box {
  width: 100%;
  min-height: 260px;
  background: #FCFBF8;
  border: 1px solid var(--hl-border);
  border-radius: var(--hl-radius-sm);
  padding: 12px 8px 6px;
}

.hl-echart {
  width: 100%;
  height: 260px;
}

.hl-fallback-svg {
  width: 100%;
  height: auto;
  display: block;
}
</style>
