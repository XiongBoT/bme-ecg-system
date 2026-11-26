<script setup lang="ts">
import { computed, onMounted, reactive, ref, type Component } from 'vue'
import {
  CalendarCheck,
  Check,
  CheckCircle2,
  Circle,
  Clock,
  Droplets,
  Footprints,
  HeartPulse,
  MoonStar,
  Pencil,
} from 'lucide-vue-next'
import { api, ApiClientError } from '../api/client'
import { useAuthStore } from '../stores/auth'
import PageHeader from '../components/common/PageHeader.vue'
import SectionHeader from '../components/common/SectionHeader.vue'
import FeatureTile from '../components/common/FeatureTile.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import HlAlert from '../components/ui/HlAlert.vue'
import HlBadge from '../components/ui/HlBadge.vue'
import {
  formatLocalDateToday,
  formatWeekdaysLabel,
  maskToWeekdays,
  WEEKDAY_OPTIONS,
  weekdaysToMask,
} from '../utils/format'
import type { PlanItem, PlanTemplate, TodayItem } from '../types/api'

const auth = useAuthStore()

const FALLBACK_TEMPLATES: PlanTemplate[] = [
  {
    key: 'sleep_log',
    title: '每日记录睡眠',
    weekdays: [1, 2, 3, 4, 5, 6, 7],
    reminder_time: '21:30',
  },
  {
    key: 'walk_habit',
    title: '晚饭后散步 20 分钟',
    weekdays: [1, 2, 3, 4, 5, 6, 7],
    reminder_time: '19:30',
  },
  {
    key: 'water_break',
    title: '午后起身活动与饮水',
    weekdays: [1, 2, 3, 4, 5],
    reminder_time: '15:00',
  },
]

const todayDate = ref(formatLocalDateToday(auth.user?.timezone))
const todayItems = ref<TodayItem[]>([])
const templates = ref<PlanTemplate[]>(FALLBACK_TEMPLATES)
const plans = ref<PlanItem[]>([])
const preferMaskField = ref(false)

const loading = ref(true)
const initialLoadFailed = ref(false)
const errorMessage = ref('')
const statusMessage = ref('')

const pendingCheckins = reactive(new Set<string>())
const creating = ref(false)

// Custom create form
const newTitle = ref('')
const newWeekdays = ref<number[]>([1, 2, 3, 4, 5, 6, 7])
const newReminderEnabled = ref(false)
const newReminderTime = ref('20:30')

// Inline edit form
const editingPlanId = ref<string | null>(null)
const editTitle = ref('')
const editWeekdays = ref<number[]>([1, 2, 3, 4, 5, 6, 7])
const editReminderEnabled = ref(false)
const editReminderTime = ref('20:30')
const savingEdit = ref(false)

const completedTodayCount = computed(() => todayItems.value.filter((i) => i.completed).length)

const todayProgressBadge = computed(() => {
  if (todayItems.value.length === 0) return '无计划'
  return `${completedTodayCount.value} / ${todayItems.value.length}`
})

function getPlanId(item: TodayItem | PlanItem): string {
  return 'plan_id' in item && item.plan_id ? item.plan_id : item.id || ''
}

function getStreak(item: TodayItem | PlanItem): number {
  return item.streak_days ?? item.current_streak ?? item.streak ?? 0
}

function templateIcon(tpl: PlanTemplate): Component {
  const keyAndTitle = `${tpl.key || tpl.template_key || ''} ${tpl.title}`
  if (/水|饮/.test(keyAndTitle) || keyAndTitle.includes('water')) return Droplets
  if (/睡|眠|作息/.test(keyAndTitle) || keyAndTitle.includes('sleep')) return MoonStar
  if (/步|走|运动|活动/.test(keyAndTitle) || keyAndTitle.includes('walk')) return Footprints
  return HeartPulse
}

function templateDescription(tpl: PlanTemplate): string {
  const freq = formatWeekdaysLabel(tpl.weekdays, tpl.weekday_mask)
  const rem = tpl.reminder_time ? ` · 提醒 ${tpl.reminder_time}` : ''
  return `${freq}执行${rem}，点击一键加入计划`
}

async function loadAll() {
  loading.value = true
  initialLoadFailed.value = false
  errorMessage.value = ''
  try {
    const [todayRes, tplRes, plansRes] = await Promise.all([
      api.get<{ date?: string; today_date?: string; items?: TodayItem[] }>('/me/today'),
      api
        .get<{ items?: PlanTemplate[]; templates?: PlanTemplate[] } | PlanTemplate[]>(
          '/plan-templates'
        )
        .catch(() => FALLBACK_TEMPLATES),
      api.get<{ items?: PlanItem[] } | PlanItem[]>('/me/plans'),
    ])

    todayDate.value = todayRes.date || todayRes.today_date || todayDate.value
    todayItems.value = todayRes.items || []

    const parsedTemplates = Array.isArray(tplRes)
      ? tplRes
      : tplRes.items || tplRes.templates || FALLBACK_TEMPLATES
    if (parsedTemplates.length > 0) {
      templates.value = parsedTemplates
      const sample = parsedTemplates[0]
      if ('weekday_mask' in sample && !('weekdays' in sample)) {
        preferMaskField.value = true
      }
    }

    const parsedPlans = Array.isArray(plansRes) ? plansRes : plansRes.items || []
    plans.value = parsedPlans
    if (
      parsedPlans.length > 0 &&
      'weekday_mask' in parsedPlans[0] &&
      !('weekdays' in parsedPlans[0])
    ) {
      preferMaskField.value = true
    }
  } catch (err) {
    initialLoadFailed.value = todayItems.value.length === 0 && plans.value.length === 0
    errorMessage.value = err instanceof ApiClientError ? err.message : '暂时无法加载习惯计划，请重试'
  } finally {
    loading.value = false
  }
}

async function submitPlanCreate(payloadBase: {
  title: string
  days: number[]
  template_key?: string
  reminder_enabled: boolean
  reminder_time: string | null
}) {
  const buildBody = (useMask: boolean) => {
    const body: Record<string, unknown> = {
      title: payloadBase.title,
      reminder_enabled: payloadBase.reminder_enabled,
      reminder_time: payloadBase.reminder_enabled ? payloadBase.reminder_time : null,
    }
    if (payloadBase.template_key) {
      body.template_key = payloadBase.template_key
    }
    if (useMask) {
      body.weekday_mask = weekdaysToMask(payloadBase.days)
    } else {
      body.weekdays = payloadBase.days
    }
    return body
  }

  try {
    await api.post('/me/plans', buildBody(preferMaskField.value))
  } catch (err) {
    if (err instanceof ApiClientError && err.status === 422) {
      preferMaskField.value = !preferMaskField.value
      await api.post('/me/plans', buildBody(preferMaskField.value))
    } else {
      throw err
    }
  }
}

async function submitPlanPatch(
  planId: string,
  fields: {
    title?: string
    days?: number[]
    active?: boolean
    reminder_enabled?: boolean
    reminder_time?: string | null
  }
) {
  const buildBody = (useMask: boolean) => {
    const body: Record<string, unknown> = {}
    if (fields.title !== undefined) body.title = fields.title
    if (fields.active !== undefined) body.active = fields.active
    if (fields.reminder_enabled !== undefined) body.reminder_enabled = fields.reminder_enabled
    if (fields.reminder_time !== undefined) body.reminder_time = fields.reminder_time
    if (fields.days !== undefined) {
      if (useMask) {
        body.weekday_mask = weekdaysToMask(fields.days)
      } else {
        body.weekdays = fields.days
      }
    }
    return body
  }

  try {
    await api.patch(`/me/plans/${planId}`, buildBody(preferMaskField.value))
  } catch (err) {
    if (err instanceof ApiClientError && err.status === 422 && fields.days !== undefined) {
      preferMaskField.value = !preferMaskField.value
      await api.patch(`/me/plans/${planId}`, buildBody(preferMaskField.value))
    } else {
      throw err
    }
  }
}

async function toggleCheckin(item: TodayItem) {
  const pid = getPlanId(item)
  if (!pid || pendingCheckins.has(pid)) return
  pendingCheckins.add(pid)
  errorMessage.value = ''
  statusMessage.value = ''

  const prevCompleted = item.completed
  const prevStreak = item.streak_days
  const nextCompleted = !prevCompleted

  try {
    if (nextCompleted) {
      await api.put(`/me/plans/${pid}/checkins/${todayDate.value}`)
    } else {
      await api.delete(`/me/plans/${pid}/checkins/${todayDate.value}`)
    }
    item.completed = nextCompleted
    statusMessage.value = nextCompleted
      ? `已完成「${item.title}」今日打卡`
      : `已撤销「${item.title}」今日打卡`
    await loadAll()
  } catch (err) {
    // UI-T20: Roll back / preserve exact previous completion & streak state on failure
    item.completed = prevCompleted
    item.streak_days = prevStreak
    errorMessage.value =
      err instanceof ApiClientError ? err.message : '打卡操作失败，请稍后重试'
  } finally {
    pendingCheckins.delete(pid)
  }
}

async function quickAddTemplate(tpl: PlanTemplate) {
  if (creating.value) return
  creating.value = true
  errorMessage.value = ''
  statusMessage.value = ''
  const days =
    Array.isArray(tpl.weekdays) && tpl.weekdays.length > 0
      ? tpl.weekdays
      : maskToWeekdays(tpl.weekday_mask)
  try {
    await submitPlanCreate({
      title: tpl.title,
      days,
      template_key: tpl.key || tpl.template_key,
      reminder_enabled: Boolean(tpl.reminder_time),
      reminder_time: tpl.reminder_time || null,
    })
    statusMessage.value = `已添加习惯计划「${tpl.title}」`
    await loadAll()
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '添加模板计划失败，请重试'
  } finally {
    creating.value = false
  }
}

function toggleDayInList(list: number[], day: number) {
  const idx = list.indexOf(day)
  if (idx >= 0) {
    if (list.length > 1) list.splice(idx, 1)
  } else {
    list.push(day)
    list.sort((a, b) => a - b)
  }
}

async function handleCreateCustom() {
  const cleanTitle = newTitle.value.trim()
  if (!cleanTitle) {
    errorMessage.value = '请填写计划名称'
    return
  }
  creating.value = true
  errorMessage.value = ''
  statusMessage.value = ''
  try {
    await submitPlanCreate({
      title: cleanTitle,
      days: [...newWeekdays.value],
      reminder_enabled: newReminderEnabled.value,
      reminder_time: newReminderEnabled.value ? newReminderTime.value : null,
    })
    newTitle.value = ''
    statusMessage.value = '已创建新的习惯计划'
    await loadAll()
  } catch (err) {
    errorMessage.value =
      err instanceof ApiClientError ? err.message : '创建计划失败，您的输入已保留，请重试'
  } finally {
    creating.value = false
  }
}

function startEdit(plan: PlanItem) {
  editingPlanId.value = plan.id
  editTitle.value = plan.title
  editWeekdays.value =
    Array.isArray(plan.weekdays) && plan.weekdays.length > 0
      ? [...plan.weekdays]
      : maskToWeekdays(plan.weekday_mask)
  editReminderEnabled.value = Boolean(plan.reminder_enabled)
  editReminderTime.value = plan.reminder_time || '20:30'
}

async function saveEdit(plan: PlanItem) {
  if (!editTitle.value.trim()) {
    errorMessage.value = '计划名称不能为空'
    return
  }
  savingEdit.value = true
  errorMessage.value = ''
  statusMessage.value = ''
  try {
    await submitPlanPatch(plan.id, {
      title: editTitle.value.trim(),
      days: [...editWeekdays.value],
      reminder_enabled: editReminderEnabled.value,
      reminder_time: editReminderEnabled.value ? editReminderTime.value : null,
    })
    editingPlanId.value = null
    statusMessage.value = '习惯计划已更新'
    await loadAll()
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '更新计划失败，请重试'
  } finally {
    savingEdit.value = false
  }
}

async function togglePlanActive(plan: PlanItem) {
  errorMessage.value = ''
  statusMessage.value = ''
  try {
    await submitPlanPatch(plan.id, { active: !plan.active })
    statusMessage.value = plan.active ? `已暂停「${plan.title}」` : `已恢复启用「${plan.title}」`
    await loadAll()
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '计划状态切换失败，请重试'
  }
}

onMounted(() => {
  loadAll()
})
</script>

<template>
  <div class="stack">
    <PageHeader
      title="习惯计划"
      subtitle="把散步、饮水、规律作息变成每天轻松完成的小目标。"
    >
      <template #actions>
        <HlBadge variant="brand" class="tabular">
          <CalendarCheck :size="16" aria-hidden="true" />
          <span>{{ todayDate }}</span>
        </HlBadge>
      </template>
    </PageHeader>

    <HlAlert v-if="errorMessage && !initialLoadFailed" variant="error">
      {{ errorMessage }}
    </HlAlert>

    <HlAlert v-if="statusMessage" variant="success">
      {{ statusMessage }}
    </HlAlert>

    <ErrorState
      v-if="initialLoadFailed"
      title="暂时无法加载，请重试"
      :message="errorMessage"
      @retry="loadAll"
    />

    <template v-else>
      <!-- Today's Check-in Section -->
      <section class="hl-card stack" aria-label="今日计划打卡">
        <SectionHeader title="今日计划">
          <template #action>
            <HlBadge
              :variant="todayItems.length > 0 ? 'brand' : 'neutral'"
              class="tabular"
            >
              {{ todayProgressBadge }}
            </HlBadge>
          </template>
        </SectionHeader>

        <LoadingState v-if="loading && todayItems.length === 0" :count="2" @retry="loadAll" />

        <EmptyState
          v-else-if="todayItems.length === 0"
          title="今天还没有待执行的计划"
          description="可以从下方推荐模板一键添加，或创建适合自己节奏的小习惯。"
        />

        <ul v-else class="hl-plan-list">
          <li
            v-for="item in todayItems"
            :key="getPlanId(item)"
            class="hl-today-row"
            :class="{ 'hl-today-row-done': item.completed }"
          >
            <div class="hl-today-main">
              <CheckCircle2
                v-if="item.completed"
                :size="24"
                class="hl-icon-done"
                aria-hidden="true"
              />
              <Circle
                v-else
                :size="24"
                class="hl-icon-todo"
                aria-hidden="true"
              />
              <div class="hl-today-info">
                <span class="hl-plan-name" :class="{ 'hl-plan-done': item.completed }">
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
                    <span>提醒 {{ item.reminder_time }}</span>
                  </HlBadge>
                </div>
              </div>
            </div>

            <button
              type="button"
              class="btn btn-sm"
              :class="item.completed ? 'btn-soft' : 'btn-primary'"
              :disabled="pendingCheckins.has(getPlanId(item))"
              @click="toggleCheckin(item)"
            >
              {{ item.completed ? '撤销打卡' : '完成打卡' }}
            </button>
          </li>
        </ul>
      </section>

      <!-- Recommended Templates & Custom Plan Form -->
      <div class="grid-2">
        <section class="hl-card stack" aria-label="推荐习惯模板">
          <SectionHeader title="推荐习惯模板" />
          <p class="text-sm hl-muted" style="margin: 0">
            点选常用生活习惯，一键添加到每日打卡列表。
          </p>

          <div class="stack-sm">
            <FeatureTile
              v-for="tpl in templates"
              :key="tpl.key || tpl.template_key || tpl.title"
              :title="tpl.title"
              :description="templateDescription(tpl)"
              :disabled="creating"
              @click="quickAddTemplate(tpl)"
            >
              <template #icon>
                <component :is="templateIcon(tpl)" :size="22" />
              </template>
            </FeatureTile>
          </div>
        </section>

        <section class="hl-card stack" aria-label="新建自定义计划">
          <SectionHeader title="新建自定义计划" />

          <form class="stack-sm" @submit.prevent="handleCreateCustom">
            <div class="field">
              <label for="plan-new-title" class="field-label">计划名称</label>
              <input
                id="plan-new-title"
                v-model="newTitle"
                type="text"
                class="input"
                maxlength="100"
                placeholder="例如：睡前平缓呼吸 5 分钟"
                required
              />
            </div>

            <div class="field">
              <span class="field-label">执行星期</span>
              <div class="row-wrap" role="group" aria-label="选择执行星期">
                <button
                  v-for="w in WEEKDAY_OPTIONS"
                  :key="w.day"
                  type="button"
                  class="pill tabular"
                  :class="{ 'pill-active': newWeekdays.includes(w.day) }"
                  :aria-pressed="newWeekdays.includes(w.day)"
                  @click="toggleDayInList(newWeekdays, w.day)"
                >
                  <Check v-if="newWeekdays.includes(w.day)" :size="15" aria-hidden="true" />
                  <span>周{{ w.short }}</span>
                </button>
              </div>
            </div>

            <div class="row-between">
              <label class="checkbox-label">
                <input v-model="newReminderEnabled" type="checkbox" />
                <span>开启站内时间提醒</span>
              </label>

              <div v-if="newReminderEnabled" class="row-wrap">
                <label for="plan-reminder-time" class="text-sm hl-muted">提醒时间</label>
                <input
                  id="plan-reminder-time"
                  v-model="newReminderTime"
                  type="time"
                  class="input tabular"
                  style="width: auto"
                />
              </div>
            </div>

            <div style="padding-top: 4px">
              <button type="submit" class="btn btn-primary" :disabled="creating">
                创建计划
              </button>
            </div>
          </form>
        </section>
      </div>

      <!-- All Plans Management -->
      <section class="hl-card stack" aria-label="我的全部计划">
        <SectionHeader title="我的全部计划" />

        <EmptyState
          v-if="!loading && plans.length === 0"
          title="还没有创建习惯计划"
          description="创建后可随时在这里调整执行星期、提醒时间或暂停计划。"
        />

        <ul v-else class="hl-plan-list">
          <li v-for="pl in plans" :key="pl.id" class="hl-manage-item stack-sm">
            <template v-if="editingPlanId === pl.id">
              <div class="field">
                <label :for="`edit-title-${pl.id}`" class="field-label">计划名称</label>
                <input
                  :id="`edit-title-${pl.id}`"
                  v-model="editTitle"
                  type="text"
                  class="input"
                  maxlength="100"
                />
              </div>

              <div class="field">
                <span class="field-label">执行星期</span>
                <div class="row-wrap" role="group" aria-label="编辑执行星期">
                  <button
                    v-for="w in WEEKDAY_OPTIONS"
                    :key="w.day"
                    type="button"
                    class="pill tabular"
                    :class="{ 'pill-active': editWeekdays.includes(w.day) }"
                    :aria-pressed="editWeekdays.includes(w.day)"
                    @click="toggleDayInList(editWeekdays, w.day)"
                  >
                    <Check v-if="editWeekdays.includes(w.day)" :size="15" aria-hidden="true" />
                    <span>周{{ w.short }}</span>
                  </button>
                </div>
              </div>

              <div class="row-between">
                <div class="row-wrap">
                  <label class="checkbox-label">
                    <input v-model="editReminderEnabled" type="checkbox" />
                    <span>站内提醒</span>
                  </label>
                  <input
                    v-if="editReminderEnabled"
                    v-model="editReminderTime"
                    type="time"
                    class="input tabular"
                    style="width: auto"
                    aria-label="编辑提醒时间"
                  />
                </div>

                <div class="row-wrap">
                  <button type="button" class="btn btn-secondary btn-sm" @click="editingPlanId = null">
                    取消
                  </button>
                  <button
                    type="button"
                    class="btn btn-primary btn-sm"
                    :disabled="savingEdit"
                    @click="saveEdit(pl)"
                  >
                    保存修改
                  </button>
                </div>
              </div>
            </template>

            <template v-else>
              <div class="row-between">
                <div class="stack-sm" style="flex: 1 1 220px">
                  <div class="row-wrap">
                    <strong class="hl-plan-name" :class="{ 'hl-muted': !pl.active }">
                      {{ pl.title }}
                    </strong>
                    <HlBadge :variant="pl.active ? 'brand' : 'neutral'">
                      {{ pl.active ? '进行中' : '已暂停' }}
                    </HlBadge>
                  </div>

                  <div class="row-wrap">
                    <HlBadge variant="neutral">
                      {{ formatWeekdaysLabel(pl.weekdays, pl.weekday_mask) }}
                    </HlBadge>
                    <HlBadge
                      v-if="pl.reminder_enabled && pl.reminder_time"
                      variant="neutral"
                      class="tabular"
                    >
                      <Clock :size="14" aria-hidden="true" />
                      <span>{{ pl.reminder_time }}</span>
                    </HlBadge>
                    <HlBadge variant="accent" class="tabular">
                      连续 {{ getStreak(pl) }} 天
                    </HlBadge>
                  </div>
                </div>

                <div class="row-wrap">
                  <button type="button" class="btn btn-ghost btn-sm" @click="startEdit(pl)">
                    <Pencil :size="17" aria-hidden="true" />
                    <span>编辑</span>
                  </button>
                  <button
                    type="button"
                    class="btn btn-secondary btn-sm"
                    @click="togglePlanActive(pl)"
                  >
                    {{ pl.active ? '暂停' : '启用' }}
                  </button>
                </div>
              </div>
            </template>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.hl-plan-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.hl-today-row,
.hl-manage-item {
  padding: 16px 18px;
  border-radius: var(--hl-radius-md);
  background: var(--hl-canvas);
  border: 1.5px solid var(--hl-border);
}

.hl-today-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  min-height: 64px;
}

.hl-today-row-done {
  background: var(--hl-surface-soft);
}

.hl-today-main {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1 1 200px;
  min-width: 0;
}

.hl-icon-done {
  color: var(--hl-brand);
  flex-shrink: 0;
}

.hl-icon-todo {
  color: var(--hl-control-border);
  flex-shrink: 0;
}

.hl-today-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.hl-plan-name {
  font-size: var(--hl-body);
  font-weight: 650;
  color: var(--hl-text);
  overflow-wrap: anywhere;
}

.hl-plan-done {
  color: var(--hl-text-muted);
  text-decoration: line-through;
}
</style>
