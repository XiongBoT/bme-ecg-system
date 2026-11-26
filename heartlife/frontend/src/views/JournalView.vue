<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  CalendarCheck,
  Check,
  Footprints,
  Lock,
  MoonStar,
  Smile,
  Trash2,
} from 'lucide-vue-next'
import { api, ApiClientError } from '../api/client'
import { useAuthStore } from '../stores/auth'
import PageHeader from '../components/common/PageHeader.vue'
import SectionHeader from '../components/common/SectionHeader.vue'
import ConfirmDialog from '../components/common/ConfirmDialog.vue'
import LoadingState from '../components/common/LoadingState.vue'
import HlAlert from '../components/ui/HlAlert.vue'
import HlBadge from '../components/ui/HlBadge.vue'
import journalCalmSvg from '../assets/heartlife/illustrations/journal-calm.svg'
import { formatLocalDateToday, formatMood } from '../utils/format'
import type { JournalEntry, MoodValue } from '../types/api'

const auth = useAuthStore()

const PRESET_TAGS = ['无特殊感受', '精力充沛', '睡得踏实', '略感疲倦', '心悸']

const SLEEP_QUICK_CHIPS = [
  { label: '360 分钟（6小时）', value: '360' },
  { label: '420 分钟（7小时）', value: '420' },
  { label: '480 分钟（8小时）', value: '480' },
]

const ACTIVITY_QUICK_CHIPS = [
  { label: '20 分钟', value: '20' },
  { label: '30 分钟', value: '30' },
  { label: '45 分钟', value: '45' },
  { label: '0 分钟（今日静养）', value: '0' },
]

const TACTILE_MOOD_OPTIONS: Array<{ value: MoodValue; label: string }> = [
  { value: 'very_good', label: '很舒畅' },
  { value: 'good', label: '不错' },
  { value: 'neutral', label: '平稳' },
  { value: 'bad', label: '略疲惫' },
  { value: 'very_bad', label: '不适' },
]

const todayStr = computed(() => formatLocalDateToday(auth.user?.timezone))
const selectedDate = ref(todayStr.value)

const entries = ref<JournalEntry[]>([])
const currentRecorded = ref(false)

const sleepInput = ref('')
const activityInput = ref('')
const moodInput = ref<MoodValue | null>(null)
const selectedTags = ref<string[]>([])
const customTagInput = ref('')
const noteInput = ref('')

const loading = ref(false)
const saving = ref(false)
const deleteConfirmOpen = ref(false)
const errorMessage = ref('')
const statusMessage = ref('')

let latestLoadSeq = 0

function entryDate(e: JournalEntry): string {
  return e.date || e.local_date || ''
}

function entryTags(e: JournalEntry): string[] {
  if (Array.isArray(e.symptom_tags)) return e.symptom_tags
  if (Array.isArray(e.tags)) return e.tags
  return []
}

const recordedDateSet = computed(() => {
  const s = new Set<string>()
  for (const e of entries.value) {
    const d = entryDate(e)
    if (d) s.add(d)
  }
  return s
})

const monthDays = computed(() => {
  const ym = selectedDate.value.slice(0, 7)
  const [yStr, mStr] = ym.split('-')
  const year = Number(yStr)
  const month = Number(mStr)
  if (!year || !month) return []
  const lastDay = new Date(year, month, 0).getDate()
  const list: Array<{ date: string; dayNum: number; future: boolean }> = []
  for (let d = 1; d <= lastDay; d++) {
    const iso = `${ym}-${String(d).padStart(2, '0')}`
    list.push({
      date: iso,
      dayNum: d,
      future: iso > todayStr.value,
    })
  }
  return list
})

function parseOptionalMinutes(raw: string, label: string): number | null {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  const num = Number(trimmed)
  if (!Number.isInteger(num) || num < 0 || num > 1440) {
    throw new Error(`${label}请填写 0 至 1440 之间的整数，或留空表示尚未记录`)
  }
  return num
}

function applyEntryToForm(entry: JournalEntry | null) {
  if (!entry || entry.recorded === false) {
    currentRecorded.value = false
    sleepInput.value = ''
    activityInput.value = ''
    moodInput.value = null
    selectedTags.value = []
    noteInput.value = ''
    return
  }
  currentRecorded.value = true
  sleepInput.value =
    entry.sleep_minutes === null || entry.sleep_minutes === undefined
      ? ''
      : String(entry.sleep_minutes)
  activityInput.value =
    entry.activity_minutes === null || entry.activity_minutes === undefined
      ? ''
      : String(entry.activity_minutes)
  moodInput.value = entry.mood ?? null
  selectedTags.value = [...entryTags(entry)]
  noteInput.value = entry.note ?? ''
}

async function loadMonthAndDate(targetDate: string) {
  const seq = ++latestLoadSeq
  loading.value = true
  errorMessage.value = ''
  const ym = targetDate.slice(0, 7)
  const [yStr, mStr] = ym.split('-')
  const lastDay = new Date(Number(yStr), Number(mStr), 0).getDate()
  const monthEnd = `${ym}-${String(lastDay).padStart(2, '0')}`
  const toDate = monthEnd > todayStr.value ? todayStr.value : monthEnd

  try {
    const listRes = await api.get<{ items?: JournalEntry[] } | JournalEntry[]>('/me/journals', {
      from: `${ym}-01`,
      to: toDate,
    })
    if (seq !== latestLoadSeq) return

    const items = Array.isArray(listRes) ? listRes : listRes.items || []
    entries.value = [...items].sort((a, b) => entryDate(b).localeCompare(entryDate(a)))

    const foundInList = entries.value.find((e) => entryDate(e) === targetDate) || null
    if (foundInList) {
      applyEntryToForm(foundInList)
    } else {
      try {
        const single = await api.get<JournalEntry>(`/me/journals/${targetDate}`)
        if (seq !== latestLoadSeq) return
        applyEntryToForm(single)
      } catch (err) {
        if (seq !== latestLoadSeq) return
        if (err instanceof ApiClientError && err.status === 404) {
          applyEntryToForm(null)
        } else {
          throw err
        }
      }
    }
  } catch (err) {
    if (seq !== latestLoadSeq) return
    errorMessage.value = err instanceof ApiClientError ? err.message : '暂时无法加载记录，请重试'
  } finally {
    if (seq === latestLoadSeq) {
      loading.value = false
    }
  }
}

function toggleTag(tag: string) {
  const idx = selectedTags.value.indexOf(tag)
  if (idx >= 0) {
    selectedTags.value.splice(idx, 1)
  } else {
    selectedTags.value.push(tag)
  }
}

function addCustomTag() {
  const t = customTagInput.value.trim()
  if (!t) return
  if (t.length > 20) {
    errorMessage.value = '单个感受标签不超过 20 个字符'
    return
  }
  if (!selectedTags.value.includes(t)) {
    selectedTags.value.push(t)
  }
  customTagInput.value = ''
}

function toggleMood(val: MoodValue) {
  moodInput.value = moodInput.value === val ? null : val
}

async function handleSave() {
  errorMessage.value = ''
  statusMessage.value = ''

  let sleepMinutes: number | null
  let activityMinutes: number | null
  try {
    // UI-T19 & T-0301: Blank '' serializes strictly as null; explicit '0' serializes as 0
    sleepMinutes = parseOptionalMinutes(sleepInput.value, '睡眠时长')
    activityMinutes = parseOptionalMinutes(activityInput.value, '活动时长')
  } catch (validationErr) {
    errorMessage.value = (validationErr as Error).message
    return
  }

  saving.value = true
  try {
    const payload = {
      sleep_minutes: sleepMinutes,
      activity_minutes: activityMinutes,
      mood: moodInput.value,
      symptom_tags: selectedTags.value,
      note: noteInput.value.trim() === '' ? null : noteInput.value.trim(),
    }
    const saved = await api.put<JournalEntry>(`/me/journals/${selectedDate.value}`, payload)
    applyEntryToForm(saved || { ...payload, local_date: selectedDate.value, recorded: true })
    statusMessage.value = '已保存当日生活健康记录'
    await loadMonthAndDate(selectedDate.value)
  } catch (err) {
    // Preserve all user form inputs on failure
    errorMessage.value =
      err instanceof ApiClientError ? err.message : '保存暂时失败，您的输入已保留，请重试'
  } finally {
    saving.value = false
  }
}

async function confirmDelete() {
  if (!currentRecorded.value) {
    deleteConfirmOpen.value = false
    return
  }
  saving.value = true
  errorMessage.value = ''
  statusMessage.value = ''
  try {
    await api.delete(`/me/journals/${selectedDate.value}`)
    deleteConfirmOpen.value = false
    applyEntryToForm(null)
    statusMessage.value = '已删除当日记录，该日期已恢复为尚未记录'
    await loadMonthAndDate(selectedDate.value)
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '删除失败，请稍后重试'
  } finally {
    saving.value = false
  }
}

watch(selectedDate, (nextDate) => {
  statusMessage.value = ''
  deleteConfirmOpen.value = false
  if (nextDate) {
    loadMonthAndDate(nextDate)
  }
})

onMounted(() => {
  loadMonthAndDate(selectedDate.value)
})
</script>

<template>
  <div class="narrow-container stack">
    <PageHeader
      title="生活健康记录"
      subtitle="如实记录睡眠、活动与心情，空白未填项将保持“未记录”，不会按 0 计入统计。"
    >
      <template #actions>
        <RouterLink to="/weekly-report" class="btn btn-secondary btn-sm">
          <CalendarCheck :size="18" aria-hidden="true" />
          <span>查看健康周报</span>
        </RouterLink>
      </template>
    </PageHeader>

    <!-- Date Picker & Month Quick-Select Calendar Card -->
    <section class="hl-card stack-sm" aria-label="日期选择与当月概览">
      <div class="row-between">
        <div class="row-wrap">
          <label for="journal-date" class="field-label">记录日期</label>
          <input
            id="journal-date"
            v-model="selectedDate"
            type="date"
            class="input tabular"
            style="width: auto"
            :max="todayStr"
          />
          <button
            type="button"
            class="btn btn-soft btn-sm"
            :disabled="selectedDate === todayStr"
            @click="selectedDate = todayStr"
          >
            回到今天
          </button>
        </div>

        <HlBadge variant="brand" class="tabular">
          {{ selectedDate.slice(0, 7) }} · 已记录 {{ recordedDateSet.size }} 天
        </HlBadge>
      </div>

      <div class="hl-month-strip" role="group" aria-label="当月日期快速切换">
        <button
          v-for="d in monthDays"
          :key="d.date"
          type="button"
          class="hl-day-pill tabular"
          :class="{
            'hl-day-selected': d.date === selectedDate,
            'hl-day-recorded': recordedDateSet.has(d.date),
          }"
          :disabled="d.future"
          :aria-pressed="d.date === selectedDate"
          :aria-current="d.date === todayStr ? 'date' : undefined"
          @click="selectedDate = d.date"
        >
          <span>{{ d.dayNum }}</span>
          <span class="sr-only">
            日（{{ d.date }}，{{ recordedDateSet.has(d.date) ? '已记录' : '尚未记录' }}）
          </span>
          <span
            v-if="recordedDateSet.has(d.date)"
            class="hl-day-dot"
            aria-hidden="true"
          ></span>
        </button>
      </div>
    </section>

    <HlAlert v-if="errorMessage" variant="error">
      {{ errorMessage }}
    </HlAlert>

    <HlAlert v-if="statusMessage" variant="success">
      {{ statusMessage }}
    </HlAlert>

    <LoadingState v-if="loading && entries.length === 0 && !currentRecorded" :count="1" />

    <!-- Warm Non-Judgmental Unrecorded Prompt Card (PRD §5.3 / §5.4) -->
    <section
      v-if="!currentRecorded && !loading"
      class="hl-card-soft hl-unrecorded-card"
      aria-label="当日记录提示"
    >
      <img
        :src="journalCalmSvg"
        alt=""
        aria-hidden="true"
        width="140"
        height="80"
        class="hl-journal-calm-img"
      />
      <div class="stack-sm">
        <h2 class="card-title">这一天还没有记录</h2>
        <p class="text-sm hl-muted" style="margin: 0">
          今天还可以记录一次，哪怕只记下一项也没关系。没有填写的项目会保持“尚未记录”。
        </p>
      </div>
    </section>

    <!-- Structured Single-Page Journal Form -->
    <form class="hl-card stack" @submit.prevent="handleSave">
      <div class="row-between">
        <h2 class="section-title tabular">{{ selectedDate }} 记录内容</h2>
        <HlBadge :variant="currentRecorded ? 'brand' : 'neutral'">
          {{ currentRecorded ? '已保存记录' : '尚未记录' }}
        </HlBadge>
      </div>

      <div class="grid-2">
        <!-- Sleep Minutes + Optional Quick Fill Chips -->
        <div class="field">
          <label for="journal-sleep" class="field-label">
            <span class="hl-label-inline">
              <MoonStar :size="20" style="color: var(--hl-brand)" aria-hidden="true" />
              <span>睡眠时长（分钟）</span>
            </span>
          </label>
          <input
            id="journal-sleep"
            type="number"
            min="0"
            max="1440"
            step="1"
            class="input tabular"
            placeholder="留空表示尚未记录"
            :value="sleepInput"
            @input="sleepInput = ($event.target as HTMLInputElement).value"
          />
          <div class="row-wrap" aria-label="常用睡眠时长快捷填入">
            <button
              v-for="chip in SLEEP_QUICK_CHIPS"
              :key="chip.value"
              type="button"
              class="pill tabular"
              :class="{ 'pill-active': sleepInput === chip.value }"
              @click="sleepInput = chip.value"
            >
              {{ chip.label }}
            </button>
            <button
              v-if="sleepInput !== ''"
              type="button"
              class="btn btn-ghost btn-sm"
              @click="sleepInput = ''"
            >
              清空睡眠
            </button>
          </div>
        </div>

        <!-- Activity Minutes + Optional Quick Fill Chips -->
        <div class="field">
          <label for="journal-activity" class="field-label">
            <span class="hl-label-inline">
              <Footprints :size="20" style="color: var(--hl-brand)" aria-hidden="true" />
              <span>活动时长（分钟）</span>
            </span>
          </label>
          <input
            id="journal-activity"
            type="number"
            min="0"
            max="1440"
            step="1"
            class="input tabular"
            placeholder="留空表示尚未记录"
            :value="activityInput"
            @input="activityInput = ($event.target as HTMLInputElement).value"
          />
          <div class="row-wrap" aria-label="常用活动时长快捷填入">
            <button
              v-for="chip in ACTIVITY_QUICK_CHIPS"
              :key="chip.value"
              type="button"
              class="pill tabular"
              :class="{ 'pill-active': activityInput === chip.value }"
              @click="activityInput = chip.value"
            >
              {{ chip.label }}
            </button>
            <button
              v-if="activityInput !== ''"
              type="button"
              class="btn btn-ghost btn-sm"
              @click="activityInput = ''"
            >
              清空活动
            </button>
          </div>
        </div>
      </div>

      <!-- Tactile >=48px Mood Selector -->
      <div class="field">
        <div class="row-between">
          <span class="field-label hl-label-inline">
            <Smile :size="20" style="color: var(--hl-brand)" aria-hidden="true" />
            <span>今日心情（可选）</span>
          </span>
          <button
            v-if="moodInput !== null"
            type="button"
            class="btn btn-ghost btn-sm"
            @click="moodInput = null"
          >
            清除心情
          </button>
        </div>

        <div class="hl-mood-grid" role="group" aria-label="今日心情选择">
          <button
            v-for="opt in TACTILE_MOOD_OPTIONS"
            :key="opt.value"
            type="button"
            class="pill hl-mood-btn"
            :class="{ 'pill-active': moodInput === opt.value }"
            :aria-pressed="moodInput === opt.value"
            @click="toggleMood(opt.value)"
          >
            <Check v-if="moodInput === opt.value" :size="18" aria-hidden="true" />
            <span>{{ opt.label }}</span>
          </button>
        </div>
      </div>

      <!-- Symptom / Feeling Self-Description Tags (Never Diagnostic) -->
      <div class="field">
        <span class="field-label">日常身体感受自述（可选，不做疾病诊断）</span>
        <div class="row-wrap" role="group" aria-label="感受标签选择">
          <button
            v-for="tag in PRESET_TAGS"
            :key="tag"
            type="button"
            class="pill"
            :class="{ 'pill-active': selectedTags.includes(tag) }"
            :aria-pressed="selectedTags.includes(tag)"
            @click="toggleTag(tag)"
          >
            <Check v-if="selectedTags.includes(tag)" :size="17" aria-hidden="true" />
            <span>{{ tag }}</span>
          </button>

          <button
            v-for="custom in selectedTags.filter((t) => !PRESET_TAGS.includes(t))"
            :key="custom"
            type="button"
            class="pill pill-active"
            :aria-pressed="true"
            @click="toggleTag(custom)"
          >
            <Check :size="17" aria-hidden="true" />
            <span>{{ custom }} ×</span>
          </button>
        </div>

        <div class="hl-custom-tag-row">
          <label for="journal-custom-tag" class="sr-only">添加自定义感受标签</label>
          <input
            id="journal-custom-tag"
            v-model="customTagInput"
            type="text"
            class="input"
            maxlength="20"
            placeholder="输入其他日常感受标签（最多20字）"
            @keydown.enter.prevent="addCustomTag"
          />
          <button type="button" class="btn btn-secondary btn-sm" @click="addCustomTag">
            添加标签
          </button>
        </div>
      </div>

      <!-- Private Note with Clear Privacy Guarantee -->
      <div class="field">
        <label for="journal-note" class="field-label">私密备注（可选）</label>
        <textarea
          id="journal-note"
          v-model="noteInput"
          class="textarea"
          maxlength="1000"
          rows="3"
          placeholder="记录睡前阅读、散步路线或生活细节..."
        ></textarea>
        <p class="hl-privacy-hint text-sm hl-muted">
          <Lock :size="16" aria-hidden="true" />
          <span>仅自己可见，不会出现在社区或公开主页</span>
        </p>
      </div>

      <div class="row-between" style="padding-top: 4px">
        <button
          v-if="currentRecorded"
          type="button"
          class="btn btn-danger"
          :disabled="saving"
          @click="deleteConfirmOpen = true"
        >
          <Trash2 :size="18" aria-hidden="true" />
          <span>删除当日记录</span>
        </button>
        <span v-else></span>

        <button type="submit" class="btn btn-primary" :disabled="saving || loading">
          {{ saving ? '保存中...' : '保存记录' }}
        </button>
      </div>
    </form>

    <!-- Current Month Recorded Entries List -->
    <section class="hl-card stack-sm" aria-label="当月已记录列表">
      <SectionHeader title="当月已保存记录" />

      <p v-if="entries.length === 0" class="text-sm hl-muted" style="margin: 0">
        本月还没有已保存的记录。
      </p>

      <ul v-else class="hl-recent-list">
        <li v-for="item in entries" :key="entryDate(item)" class="hl-recent-row">
          <div class="hl-recent-meta tabular">
            <strong>{{ entryDate(item) }}</strong>
            <span class="text-sm hl-muted">
              睡眠：{{
                item.sleep_minutes !== null && item.sleep_minutes !== undefined
                  ? `${item.sleep_minutes} 分钟`
                  : '尚未记录'
              }}
            </span>
            <span class="text-sm hl-muted">
              活动：{{
                item.activity_minutes !== null && item.activity_minutes !== undefined
                  ? `${item.activity_minutes} 分钟`
                  : '尚未记录'
              }}
            </span>
            <HlBadge v-if="item.mood" variant="brand">{{ formatMood(item.mood) }}</HlBadge>
          </div>
          <button
            type="button"
            class="btn btn-soft btn-sm"
            @click="selectedDate = entryDate(item)"
          >
            查看该日
          </button>
        </li>
      </ul>
    </section>

    <!-- Two-Step Delete Confirmation Dialog -->
    <ConfirmDialog
      v-model:open="deleteConfirmOpen"
      title="确认删除当日记录"
      description="删除后该日期将恢复为“尚未记录”状态，请确认是否继续。"
      confirm-label="确认删除"
      cancel-label="保留记录"
      :danger="true"
      :loading="saving"
      @confirm="confirmDelete"
    />
  </div>
</template>

<style scoped>
.hl-month-strip {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(48px, 1fr));
  gap: 8px;
}

.hl-day-pill {
  min-height: var(--hl-target);
  border-radius: 10px;
  border: 1.5px solid var(--hl-border);
  background: var(--hl-surface);
  color: var(--hl-text);
  font-family: inherit;
  font-size: var(--hl-caption);
  font-weight: 600;
  cursor: pointer;
  padding: 4px 2px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}

.hl-day-pill:hover:not(:disabled) {
  border-color: var(--hl-brand);
  background: var(--hl-surface-soft);
}

.hl-day-pill:disabled {
  opacity: 0.36;
  cursor: not-allowed;
}

.hl-day-recorded {
  background: var(--hl-surface-soft);
  border-color: var(--hl-brand);
  color: var(--hl-brand);
}

.hl-day-selected {
  background: var(--hl-brand) !important;
  border-color: var(--hl-brand) !important;
  color: var(--hl-on-brand) !important;
  font-weight: 700;
}

.hl-day-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.hl-unrecorded-card {
  display: flex;
  align-items: center;
  gap: 18px;
}

.hl-journal-calm-img {
  width: 128px;
  height: auto;
  border-radius: 12px;
  flex-shrink: 0;
}

.hl-label-inline {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.hl-mood-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}

.hl-mood-btn {
  width: 100%;
}

.hl-custom-tag-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.hl-custom-tag-row .input {
  flex: 1 1 220px;
}

.hl-privacy-hint {
  margin: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.hl-recent-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.hl-recent-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px 14px;
  border-radius: var(--hl-radius-sm);
  background: var(--hl-canvas);
  border: 1px solid var(--hl-border);
}

.hl-recent-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

@media (max-width: 640px) {
  .hl-unrecorded-card {
    flex-direction: column;
    align-items: flex-start;
  }

  .hl-mood-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
