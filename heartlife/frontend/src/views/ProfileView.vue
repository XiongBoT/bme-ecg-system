<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  Bell,
  Bookmark,
  CalendarCheck,
  Download,
  HeartHandshake,
  History,
  LogOut,
  NotebookPen,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  UserRound,
} from 'lucide-vue-next'
import { api, ApiClientError } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { formatDateTimeShort } from '../utils/format'
import DisplaySettings from '../components/common/DisplaySettings.vue'
import ConfirmDialog from '../components/common/ConfirmDialog.vue'
import EmptyState from '../components/common/EmptyState.vue'
import FeatureTile from '../components/common/FeatureTile.vue'
import LoadingState from '../components/common/LoadingState.vue'
import HlAlert from '../components/ui/HlAlert.vue'
import HlAvatar from '../components/ui/HlAvatar.vue'
import HlBadge from '../components/ui/HlBadge.vue'
import type { ArticleSummary, FamilyGrantItem, PostSummary } from '../types/api'

const auth = useAuthStore()
const router = useRouter()

type ProfileTab = 'info' | 'display' | 'library' | 'family' | 'privacy'
const activeTab = ref<ProfileTab>('info')

const PROFILE_TABS: Array<{ key: ProfileTab; label: string }> = [
  { key: 'info', label: '个人资料' },
  { key: 'display', label: '显示设置' },
  { key: 'library', label: '收藏与历史' },
  { key: 'family', label: '家庭关怀' },
  { key: 'privacy', label: '数据与隐私' },
]

const TIMEZONE_OPTIONS = [
  'Asia/Shanghai',
  'Asia/Tokyo',
  'Asia/Singapore',
  'UTC',
  'Europe/London',
  'America/New_York',
  'America/Los_Angeles',
]

// Basic Profile
const nickname = ref(auth.user?.nickname || '')
const bio = ref(auth.user?.bio || '')
const timezone = ref(auth.user?.timezone || 'Asia/Shanghai')
const savingProfile = ref(false)

// Messages
const errorMessage = ref('')
const statusMessage = ref('')

// My Posts, Bookmarks & Reading History
const myPosts = ref<PostSummary[]>([])
const loadingPosts = ref(false)

interface BookmarkEntry {
  target_type: 'post' | 'article'
  target_id: string
  title: string
  category?: string
}
const myBookmarks = ref<BookmarkEntry[]>([])
const loadingBookmarks = ref(false)

interface HistoryEntry {
  article_id: string
  title: string
  category?: string
  last_read_at?: string
}
const readingHistory = ref<HistoryEntry[]>([])
const loadingHistory = ref(false)
const clearHistoryDialogOpen = ref(false)
const clearingHistory = ref(false)

// Family Care
const sharePlanSummary = ref(true)
const shareWeeklySleep = ref(false)
const shareWeeklyActivity = ref(false)
const generatedInviteCode = ref('')
const acceptCodeInput = ref('')
const outgoingGrants = ref<FamilyGrantItem[]>([])
const incomingGrants = ref<FamilyGrantItem[]>([])
const selectedSharedSummary = ref<Record<string, unknown> | null>(null)
const selectedSharedName = ref('')
const revokeDialogOpen = ref(false)
const pendingRevokeGrant = ref<FamilyGrantItem | null>(null)
const revokingGrant = ref(false)

// Privacy & Account Deletion
const exportingData = ref(false)
const deletePassword = ref('')
const deleteConfirmWord = ref('')
const deletingAccount = ref(false)

function resetAlerts() {
  errorMessage.value = ''
  statusMessage.value = ''
}

async function handleSaveProfile() {
  resetAlerts()
  if (!nickname.value.trim()) {
    errorMessage.value = '昵称不能为空'
    return
  }
  savingProfile.value = true
  try {
    await auth.updateProfile({
      nickname: nickname.value.trim(),
      bio: bio.value.trim(),
      timezone: timezone.value,
    })
    statusMessage.value = '个人资料已更新'
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '保存失败'
  } finally {
    savingProfile.value = false
  }
}

async function loadMyPosts() {
  loadingPosts.value = true
  try {
    const res = await api.get<{ items?: PostSummary[] } | PostSummary[]>('/me/posts')
    myPosts.value = Array.isArray(res) ? res : res.items || []
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '加载我的发布失败'
  } finally {
    loadingPosts.value = false
  }
}

async function loadBookmarks() {
  loadingBookmarks.value = true
  const combined: BookmarkEntry[] = []
  try {
    const res = await api
      .get<{
        items?: Array<{
          target_type?: 'post' | 'article'
          target_id?: string
          id?: string
          title?: string
          category?: string
        }>
        posts?: PostSummary[]
        articles?: ArticleSummary[]
      }>('/me/bookmarks')
      .catch(() => null)

    if (res) {
      if (Array.isArray(res.items)) {
        for (const it of res.items) {
          combined.push({
            target_type: it.target_type === 'article' ? 'article' : 'post',
            target_id: it.target_id || it.id || '',
            title: it.title || '收藏条目',
            category: it.category,
          })
        }
      }
      if (Array.isArray(res.posts)) {
        for (const p of res.posts) {
          combined.push({ target_type: 'post', target_id: p.id, title: p.title, category: p.category })
        }
      }
      if (Array.isArray(res.articles)) {
        for (const a of res.articles) {
          combined.push({ target_type: 'article', target_id: a.id, title: a.title, category: a.category })
        }
      }
    }

    const artRes = await api.get<{ items?: ArticleSummary[] }>('/me/article-bookmarks').catch(() => null)
    if (artRes?.items) {
      for (const a of artRes.items) {
        if (!combined.some((x) => x.target_type === 'article' && x.target_id === a.id)) {
          combined.push({ target_type: 'article', target_id: a.id, title: a.title, category: a.category })
        }
      }
    }
    myBookmarks.value = combined
  } finally {
    loadingBookmarks.value = false
  }
}

async function loadReadingHistory() {
  loadingHistory.value = true
  try {
    const res = await api.get<{
      items?: Array<{
        article_id?: string
        id?: string
        title?: string
        article?: { id: string; title: string; category?: string }
        category?: string
        last_read_at?: string
      }>
    }>('/me/reading-history')
    readingHistory.value = (res.items || []).map((x) => ({
      article_id: x.article_id || x.article?.id || x.id || '',
      title: x.title || x.article?.title || '科普文章',
      category: x.category || x.article?.category,
      last_read_at: x.last_read_at,
    }))
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '加载阅读历史失败'
  } finally {
    loadingHistory.value = false
  }
}

async function loadLibraryAll() {
  await Promise.all([loadMyPosts(), loadBookmarks(), loadReadingHistory()])
}

async function confirmClearReadingHistory() {
  resetAlerts()
  clearingHistory.value = true
  try {
    await api.delete('/me/reading-history')
    readingHistory.value = []
    clearHistoryDialogOpen.value = false
    statusMessage.value = '阅读历史已清空'
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '清空失败'
  } finally {
    clearingHistory.value = false
  }
}

async function loadFamilyGrants() {
  try {
    const res = await api.get<{
      granted_by_me?: FamilyGrantItem[]
      granted_to_me?: FamilyGrantItem[]
      outgoing?: FamilyGrantItem[]
      incoming?: FamilyGrantItem[]
      as_granter?: FamilyGrantItem[]
      as_viewer?: FamilyGrantItem[]
      items?: FamilyGrantItem[]
    }>('/me/family/grants')
    const uid = auth.user?.id
    if (res.granted_by_me || res.granted_to_me) {
      outgoingGrants.value = res.granted_by_me || []
      incomingGrants.value = res.granted_to_me || []
    } else if (res.outgoing || res.incoming) {
      outgoingGrants.value = res.outgoing || []
      incomingGrants.value = res.incoming || []
    } else if (res.as_granter || res.as_viewer) {
      outgoingGrants.value = res.as_granter || []
      incomingGrants.value = res.as_viewer || []
    } else if (Array.isArray(res.items)) {
      outgoingGrants.value = res.items.filter((g) => g.granter_id === uid)
      incomingGrants.value = res.items.filter((g) => g.viewer_id === uid)
    }
  } catch {
    // Keep empty if none
  }
}

async function createFamilyInvite() {
  resetAlerts()
  try {
    const res = await api.post<{ invite_code?: string; code?: string }>('/me/family/invites', {
      share_plan_summary: sharePlanSummary.value,
      share_weekly_sleep: shareWeeklySleep.value,
      share_weekly_activity: shareWeeklyActivity.value,
    })
    generatedInviteCode.value = res.invite_code || res.code || ''
    statusMessage.value = '已生成单次授权邀请码'
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '生成邀请码失败'
  }
}

async function acceptFamilyInvite() {
  resetAlerts()
  const code = acceptCodeInput.value.trim()
  if (!code) return
  try {
    await api.post('/me/family/accept', { invite_code: code })
    acceptCodeInput.value = ''
    statusMessage.value = '已建立家庭关怀关联'
    await loadFamilyGrants()
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '接受邀请失败'
  }
}

async function updateGrantToggle(
  grant: FamilyGrantItem,
  field: 'share_plan_summary' | 'share_weekly_sleep' | 'share_weekly_activity'
) {
  resetAlerts()
  const nextVal = !grant[field]
  try {
    await api.patch(`/me/family/grants/${grant.id}`, {
      [field]: nextVal,
    })
    grant[field] = nextVal
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '更新权限失败'
  }
}

function promptRevokeGrant(grant: FamilyGrantItem) {
  pendingRevokeGrant.value = grant
  revokeDialogOpen.value = true
}

async function confirmRevokeGrant() {
  if (!pendingRevokeGrant.value) return
  resetAlerts()
  revokingGrant.value = true
  try {
    await api.delete(`/me/family/grants/${pendingRevokeGrant.value.id}`)
    revokeDialogOpen.value = false
    pendingRevokeGrant.value = null
    selectedSharedSummary.value = null
    statusMessage.value = '已撤销共享授权'
    await loadFamilyGrants()
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '撤销失败'
  } finally {
    revokingGrant.value = false
  }
}

async function viewSharedSummary(grant: FamilyGrantItem) {
  resetAlerts()
  try {
    const data = await api.get<Record<string, unknown>>(`/family/shared/${grant.granter_id}`)
    selectedSharedSummary.value = data
    selectedSharedName.value = grant.granter_nickname || grant.granter_id
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '无法读取共享摘要'
  }
}

async function handleExportJson() {
  resetAlerts()
  exportingData.value = true
  try {
    const data = await api.get<unknown>('/me/export')
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `heartlife-export-${new Date().toISOString().slice(0, 10)}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    statusMessage.value = '个人数据 JSON 已导出'
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '导出失败'
  } finally {
    exportingData.value = false
  }
}

async function handleLogout() {
  await auth.logout()
  await router.push('/login')
}

async function handleRevokeAllSessions() {
  try {
    await auth.revokeAllSessions()
    await router.push('/login')
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '操作失败'
  }
}

async function handleDeleteAccount() {
  resetAlerts()
  if (deleteConfirmWord.value !== 'DELETE') {
    errorMessage.value = '请输入大写确认词 DELETE'
    return
  }
  if (!deletePassword.value) {
    errorMessage.value = '请输入当前登录密码'
    return
  }
  deletingAccount.value = true
  try {
    await api.post('/me/delete', {
      password: deletePassword.value,
      confirm_text: 'DELETE',
    })
    auth.clearSession()
    await router.push('/login')
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '注销失败'
  } finally {
    deletingAccount.value = false
  }
}

watch(activeTab, (tab) => {
  resetAlerts()
  if (tab === 'library') loadLibraryAll()
  if (tab === 'family') loadFamilyGrants()
})

onMounted(() => {
  if (auth.user) {
    nickname.value = auth.user.nickname
    bio.value = auth.user.bio || ''
    timezone.value = auth.user.timezone || 'Asia/Shanghai'
  }
})
</script>

<template>
  <div class="stack">
    <!-- Warm Profile Summary Header Card -->
    <section class="hl-card hl-profile-hero" aria-label="个人账号概览">
      <div class="hl-profile-identity">
        <HlAvatar :name="auth.user?.nickname" size="lg" />
        <div class="stack-sm" style="flex: 1; min-width: 0">
          <div class="row-wrap">
            <h1 class="page-title">{{ auth.user?.nickname || '我的空间' }}</h1>
            <HlBadge v-if="auth.user?.account" class="tabular">@{{ auth.user.account }}</HlBadge>
            <HlBadge v-if="auth.user?.is_demo" variant="brand">演示账号</HlBadge>
            <HlBadge v-if="auth.isOps" variant="accent">
              {{ auth.isModerator && auth.isEditor ? '审核 · 编辑' : auth.isModerator ? '社区审核' : '科普编辑' }}
            </HlBadge>
          </div>
          <p v-if="auth.user?.bio" class="hl-muted text-sm user-content" style="margin: 0">
            {{ auth.user.bio }}
          </p>
          <p v-else class="hl-muted text-sm" style="margin: 0">
            在这里管理您的个人资料、字号对比度偏好、亲友关怀授权与账号安全。
          </p>
        </div>
      </div>

      <div class="row-wrap">
        <RouterLink
          v-if="auth.user?.id"
          :to="`/users/${auth.user.id}`"
          class="btn btn-secondary btn-sm"
        >
          <UserRound :size="18" aria-hidden="true" />
          <span>查看公开主页</span>
        </RouterLink>

        <RouterLink to="/notifications" class="btn btn-secondary btn-sm">
          <Bell :size="18" aria-hidden="true" />
          <span>消息通知</span>
          <HlBadge v-if="auth.unreadCount > 0" variant="accent" class="tabular">
            {{ auth.unreadCount }}
          </HlBadge>
        </RouterLink>

        <RouterLink v-if="auth.isOps" to="/ops" class="btn btn-soft btn-sm">
          <ShieldCheck :size="18" aria-hidden="true" />
          <span>进入运营台</span>
        </RouterLink>
      </div>
    </section>

    <!-- Accessible Flat Wrapping Tablist (>=48px targets, zero mobile horizontal overflow) -->
    <div class="hl-profile-tabs" role="tablist" aria-label="个人中心栏目">
      <button
        v-for="t in PROFILE_TABS"
        :key="t.key"
        type="button"
        role="tab"
        :aria-selected="activeTab === t.key"
        class="pill"
        :class="{ 'pill-active': activeTab === t.key }"
        @click="activeTab = t.key"
      >
        {{ t.label }}
      </button>
    </div>

    <HlAlert v-if="errorMessage" variant="error" role="alert">
      {{ errorMessage }}
    </HlAlert>
    <HlAlert v-if="statusMessage" variant="success" role="status">
      {{ statusMessage }}
    </HlAlert>

    <!-- Tab 1: Personal Profile & Health Record Shortcuts -->
    <div v-if="activeTab === 'info'" class="stack">
      <form class="hl-card stack" @submit.prevent="handleSaveProfile">
        <div class="row-wrap">
          <UserRound :size="22" style="color: var(--hl-brand)" aria-hidden="true" />
          <h2 class="section-title">个人基本资料</h2>
        </div>

        <div class="grid-2">
          <div class="field">
            <label for="prof-nickname" class="field-label">昵称</label>
            <input
              id="prof-nickname"
              v-model="nickname"
              type="text"
              class="input"
              maxlength="32"
              required
            />
          </div>
          <div class="field">
            <label for="prof-timezone" class="field-label">所在时区</label>
            <select id="prof-timezone" v-model="timezone" class="select">
              <option v-for="tz in TIMEZONE_OPTIONS" :key="tz" :value="tz">{{ tz }}</option>
            </select>
          </div>
        </div>

        <div class="field">
          <label for="prof-bio" class="field-label">个人简介（公开主页可见）</label>
          <textarea
            id="prof-bio"
            v-model="bio"
            class="textarea"
            rows="3"
            maxlength="200"
            placeholder="简单介绍一下您的日常健康小习惯（请勿填写手机号或住址）"
          ></textarea>
        </div>

        <div class="row-wrap" style="justify-content: flex-end">
          <button type="submit" class="btn btn-primary" :disabled="savingProfile">
            {{ savingProfile ? '正在保存...' : '保存修改' }}
          </button>
        </div>
      </form>

      <section class="hl-card stack-sm" aria-label="健康记录与功能快捷入口">
        <h2 class="section-title">日常健康与陪伴入口</h2>
        <div class="grid-2">
          <FeatureTile
            to="/journal"
            title="今日健康日记"
            description="温和记录睡眠、散步活动与心情感受"
          >
            <template #icon><NotebookPen :size="22" /></template>
          </FeatureTile>

          <FeatureTile
            to="/plans"
            title="日常习惯计划"
            description="查看并打卡您设定的每日健康小目标"
          >
            <template #icon><CalendarCheck :size="22" /></template>
          </FeatureTile>

          <FeatureTile
            title="大字与高对比度设置"
            description="随时放大字号或开启高对比度模式"
            @click="activeTab = 'display'"
          >
            <template #icon><SlidersHorizontal :size="22" /></template>
          </FeatureTile>

          <FeatureTile
            title="亲友家庭关怀"
            description="按需授权家人查看打卡或睡眠周摘要"
            @click="activeTab = 'family'"
          >
            <template #icon><HeartHandshake :size="22" /></template>
          </FeatureTile>
        </div>
      </section>
    </div>

    <!-- Tab 2: Display & Accessibility Settings -->
    <div v-else-if="activeTab === 'display'" class="stack">
      <DisplaySettings />
    </div>

    <!-- Tab 3: Bookmarks, Posts & Reading History -->
    <div v-else-if="activeTab === 'library'" class="stack">
      <section class="hl-card stack">
        <div class="row-wrap">
          <Bookmark :size="22" style="color: var(--hl-brand)" aria-hidden="true" />
          <h2 class="section-title">我的收藏</h2>
        </div>

        <LoadingState v-if="loadingBookmarks" :count="2" />
        <EmptyState
          v-else-if="myBookmarks.length === 0"
          title="还没有收藏内容"
          description="浏览同伴社区或健康百科时点击「收藏」，方便日后随时翻阅。"
        >
          <template #actions>
            <RouterLink to="/knowledge" class="btn btn-secondary btn-sm">逛逛健康百科</RouterLink>
            <RouterLink to="/community" class="btn btn-soft btn-sm">看看同伴社区</RouterLink>
          </template>
        </EmptyState>
        <ul v-else class="hl-item-list">
          <li
            v-for="b in myBookmarks"
            :key="`${b.target_type}-${b.target_id}`"
            class="hl-item-row row-between"
          >
            <RouterLink
              :to="b.target_type === 'article' ? `/knowledge/${b.target_id}` : `/community/${b.target_id}`"
              class="user-content hl-item-link"
            >
              {{ b.title }}
            </RouterLink>
            <HlBadge :variant="b.target_type === 'article' ? 'brand' : 'neutral'">
              {{ b.target_type === 'article' ? '健康百科' : '社区分享' }}
            </HlBadge>
          </li>
        </ul>
      </section>

      <section class="hl-card stack">
        <div class="row-between">
          <div class="row-wrap">
            <History :size="22" style="color: var(--hl-brand)" aria-hidden="true" />
            <h2 class="section-title">百科阅读历史</h2>
          </div>
          <button
            v-if="readingHistory.length > 0"
            type="button"
            class="btn btn-secondary btn-sm"
            @click="clearHistoryDialogOpen = true"
          >
            <Trash2 :size="18" aria-hidden="true" />
            <span>清空阅读历史</span>
          </button>
        </div>

        <LoadingState v-if="loadingHistory" :count="2" />
        <EmptyState
          v-else-if="readingHistory.length === 0"
          title="还没有阅读记录"
          description="阅读过的健康百科文章会记录在这里，方便您回顾。"
        />
        <ul v-else class="hl-item-list">
          <li v-for="h in readingHistory" :key="h.article_id" class="hl-item-row row-between">
            <RouterLink :to="`/knowledge/${h.article_id}`" class="hl-item-link">
              {{ h.title }}
            </RouterLink>
            <span v-if="h.last_read_at" class="text-sm hl-muted tabular">
              {{ formatDateTimeShort(h.last_read_at) }}
            </span>
          </li>
        </ul>
      </section>

      <section class="hl-card stack">
        <div class="row-wrap">
          <NotebookPen :size="22" style="color: var(--hl-brand)" aria-hidden="true" />
          <h2 class="section-title">我的社区发布</h2>
        </div>

        <LoadingState v-if="loadingPosts" :count="2" />
        <EmptyState
          v-else-if="myPosts.length === 0"
          title="还没有发布动态"
          description="在同伴社区分享您的散步或作息心得，与大家互相鼓励。"
        >
          <template #actions>
            <RouterLink to="/community" class="btn btn-primary btn-sm">前往同伴社区</RouterLink>
          </template>
        </EmptyState>
        <ul v-else class="hl-item-list">
          <li v-for="p in myPosts" :key="p.id" class="hl-item-row stack-sm">
            <div class="row-between">
              <RouterLink :to="`/community/${p.id}`" class="user-content hl-item-link">
                {{ p.title }}
              </RouterLink>
              <HlBadge :variant="p.status === 'hidden' ? 'accent' : 'brand'">
                {{ p.status === 'hidden' ? '已隐藏' : '公开可见' }}
              </HlBadge>
            </div>
            <div v-if="p.status === 'hidden' && p.moderation_reason" class="text-sm hl-muted">
              处理说明：{{ p.moderation_reason }}
            </div>
            <span class="text-sm hl-muted tabular">{{ formatDateTimeShort(p.created_at) }}</span>
          </li>
        </ul>
      </section>
    </div>

    <!-- Tab 4: Family Care -->
    <div v-else-if="activeTab === 'family'" class="stack">
      <HlAlert variant="info" class="alert-brand" role="note">
        家庭关怀遵循最小必要共享原则：仅在您主动勾选的范围向指定亲友展示统计摘要，绝不公开您的私密日记备注原文，且可随时撤销。
      </HlAlert>

      <div class="grid-2">
        <section class="hl-card stack-sm">
          <h2 class="section-title">创建亲友邀请码</h2>
          <p class="text-sm hl-muted" style="margin: 0">
            请先勾选允许家人查看的内容范围，再生成单次有效的邀请码：
          </p>

          <label class="checkbox-label">
            <input v-model="sharePlanSummary" type="checkbox" />
            <span>共享今日习惯打卡进度</span>
          </label>
          <label class="checkbox-label">
            <input v-model="shareWeeklySleep" type="checkbox" />
            <span>共享本周平均睡眠分钟</span>
          </label>
          <label class="checkbox-label">
            <input v-model="shareWeeklyActivity" type="checkbox" />
            <span>共享本周累计活动分钟</span>
          </label>

          <div>
            <button type="button" class="btn btn-primary btn-sm" @click="createFamilyInvite">
              生成邀请码
            </button>
          </div>

          <div v-if="generatedInviteCode" class="hl-card-soft card-subtle text-sm tabular">
            邀请码：<strong data-testid="family-invite-code">{{ generatedInviteCode }}</strong>
          </div>
        </section>

        <section class="hl-card stack-sm">
          <h2 class="section-title">输入亲友邀请码</h2>
          <p class="text-sm hl-muted" style="margin: 0">
            收到家人发送的单次邀请码后，在此输入即可建立关怀关联：
          </p>
          <form class="stack-sm" @submit.prevent="acceptFamilyInvite">
            <div class="field">
              <label for="family-accept-code" class="field-label">单次邀请码</label>
              <input
                id="family-accept-code"
                v-model="acceptCodeInput"
                type="text"
                class="input tabular"
                placeholder="请输入亲友提供的邀请码"
                required
              />
            </div>
            <div>
              <button type="submit" class="btn btn-secondary btn-sm">确认关联</button>
            </div>
          </form>
        </section>
      </div>

      <section class="hl-card stack-sm">
        <h2 class="section-title">我授权的亲友</h2>
        <p class="text-sm hl-muted" style="margin: 0">
          点击下方开关按钮可随时调整共享项；点击「撤销授权」并确认后将立即停止一切数据共享。
        </p>

        <div v-if="outgoingGrants.length === 0" class="hl-muted text-sm">暂无已授权的亲友记录</div>
        <ul v-else class="hl-item-list">
          <li v-for="g in outgoingGrants" :key="g.id" class="hl-item-row stack-sm">
            <div class="row-between">
              <strong class="card-title">{{ g.viewer_nickname || g.viewer_id }}</strong>
              <button type="button" class="btn btn-danger btn-sm" @click="promptRevokeGrant(g)">
                撤销授权
              </button>
            </div>
            <div class="row-wrap" role="group" :aria-label="`${g.viewer_nickname || '亲友'}共享范围开关`">
              <button
                type="button"
                class="pill"
                :class="{ 'pill-active': g.share_plan_summary }"
                :aria-pressed="g.share_plan_summary"
                @click="updateGrantToggle(g, 'share_plan_summary')"
              >
                {{ g.share_plan_summary ? '已开启：打卡进度' : '未开启：打卡进度' }}
              </button>
              <button
                type="button"
                class="pill"
                :class="{ 'pill-active': g.share_weekly_sleep }"
                :aria-pressed="g.share_weekly_sleep"
                @click="updateGrantToggle(g, 'share_weekly_sleep')"
              >
                {{ g.share_weekly_sleep ? '已开启：睡眠均值' : '未开启：睡眠均值' }}
              </button>
              <button
                type="button"
                class="pill"
                :class="{ 'pill-active': g.share_weekly_activity }"
                :aria-pressed="g.share_weekly_activity"
                @click="updateGrantToggle(g, 'share_weekly_activity')"
              >
                {{ g.share_weekly_activity ? '已开启：活动总计' : '未开启：活动总计' }}
              </button>
            </div>
          </li>
        </ul>
      </section>

      <section class="hl-card stack-sm">
        <h2 class="section-title">亲友共享给我</h2>
        <div v-if="incomingGrants.length === 0" class="hl-muted text-sm">暂无亲友共享给您的记录</div>
        <ul v-else class="hl-item-list">
          <li v-for="g in incomingGrants" :key="g.id" class="hl-item-row row-between">
            <strong>{{ g.granter_nickname || g.granter_id }}</strong>
            <button type="button" class="btn btn-soft btn-sm" @click="viewSharedSummary(g)">
              查看摘要
            </button>
          </li>
        </ul>

        <div v-if="selectedSharedSummary" class="hl-card-soft card-subtle stack-sm tabular">
          <strong>{{ selectedSharedName }} 的授权摘要</strong>
          <div class="row-wrap text-sm">
            <span v-if="'plan_summary' in selectedSharedSummary && selectedSharedSummary.plan_summary">
              打卡：{{
                (selectedSharedSummary.plan_summary as Record<string, unknown>).completed ??
                (selectedSharedSummary.plan_summary as Record<string, unknown>).completed_count ??
                0
              }}/{{
                (selectedSharedSummary.plan_summary as Record<string, unknown>).due ??
                (selectedSharedSummary.plan_summary as Record<string, unknown>).due_count ??
                0
              }}
            </span>
            <span v-if="'weekly_sleep' in selectedSharedSummary && selectedSharedSummary.weekly_sleep">
              本周平均睡眠：{{
                (selectedSharedSummary.weekly_sleep as Record<string, unknown>).mean_minutes ?? '尚未记录'
              }}
            </span>
            <span v-if="'weekly_activity' in selectedSharedSummary && selectedSharedSummary.weekly_activity">
              本周累计活动：{{
                (selectedSharedSummary.weekly_activity as Record<string, unknown>).total_minutes ?? '尚未记录'
              }}
            </span>
          </div>
        </div>
      </section>
    </div>

    <!-- Tab 5: Account & Data Privacy -->
    <div v-else-if="activeTab === 'privacy'" class="stack">
      <section class="hl-card stack-sm">
        <div class="row-wrap">
          <ShieldCheck :size="22" style="color: var(--hl-brand)" aria-hidden="true" />
          <h2 class="section-title">账号与数据隐私</h2>
        </div>
        <p class="text-sm hl-muted" style="margin: 0">
          您可以随时导出自己在心伴记录的完整 JSON 数据，或管理当前登录设备会话。
        </p>

        <div class="row-wrap" style="padding-top: 4px">
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            :disabled="exportingData"
            @click="handleExportJson"
          >
            <Download :size="18" aria-hidden="true" />
            <span>{{ exportingData ? '正在导出...' : '导出个人数据 JSON' }}</span>
          </button>

          <button type="button" class="btn btn-secondary btn-sm" @click="handleRevokeAllSessions">
            <span>退出其他设备会话</span>
          </button>

          <button type="button" class="btn btn-soft btn-sm" @click="handleLogout">
            <LogOut :size="18" aria-hidden="true" />
            <span>退出当前登录</span>
          </button>
        </div>
      </section>

      <section class="hl-card hl-danger-zone stack-sm">
        <div class="row-wrap">
          <ShieldAlert :size="22" style="color: var(--hl-danger)" aria-hidden="true" />
          <h2 class="section-title" style="color: var(--hl-danger)">永久注销账号</h2>
        </div>
        <p class="text-sm hl-muted" style="margin: 0">
          注销后将永久删除您的个人资料、健康日记、习惯计划及家庭关怀授权，操作不可恢复。请输入当前密码并填写大写
          <strong class="tabular">DELETE</strong> 进行二次核验。
        </p>

        <form class="stack-sm" @submit.prevent="handleDeleteAccount">
          <div class="grid-2">
            <div class="field">
              <label for="del-password" class="field-label">当前登录密码</label>
              <input
                id="del-password"
                v-model="deletePassword"
                type="password"
                class="input"
                autocomplete="current-password"
                required
              />
            </div>
            <div class="field">
              <label for="del-confirm" class="field-label">输入 DELETE 确认注销</label>
              <input
                id="del-confirm"
                v-model="deleteConfirmWord"
                type="text"
                class="input tabular"
                placeholder="DELETE"
                required
              />
            </div>
          </div>
          <div>
            <button
              type="submit"
              class="btn btn-danger btn-sm"
              :disabled="deletingAccount || deleteConfirmWord !== 'DELETE'"
            >
              {{ deletingAccount ? '正在注销...' : '确认永久注销' }}
            </button>
          </div>
        </form>
      </section>
    </div>

    <!-- Confirm Dialog: Clear Reading History -->
    <ConfirmDialog
      v-model:open="clearHistoryDialogOpen"
      title="确认清空阅读历史"
      description="清空后将移除您在健康百科的阅读足迹记录，已收藏的文章不会受影响。"
      confirm-label="确认清空"
      danger
      :loading="clearingHistory"
      @confirm="confirmClearReadingHistory"
    />

    <!-- Confirm Dialog: Revoke Family Grant (PRD §5.6 Mandatory Two-Step Confirmation) -->
    <ConfirmDialog
      v-model:open="revokeDialogOpen"
      title="确认撤销家庭关怀授权"
      :description="`撤销后，「${pendingRevokeGrant?.viewer_nickname || pendingRevokeGrant?.viewer_id || '该亲友'}」将立即无法查看您的任何健康打卡与周报摘要。`"
      confirm-label="确认撤销"
      danger
      :loading="revokingGrant"
      @confirm="confirmRevokeGrant"
    />
  </div>
</template>

<style scoped>
.hl-profile-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}

.hl-profile-identity {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1 1 320px;
  min-width: 0;
}

.hl-profile-tabs {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.hl-item-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.hl-item-row {
  padding: 14px 16px;
  border-radius: var(--hl-radius-sm);
  background: var(--hl-canvas);
  border: 1px solid var(--hl-border);
}

.hl-item-link {
  font-weight: 650;
  color: var(--hl-text);
}

.hl-item-link:hover {
  color: var(--hl-brand);
}

.hl-danger-zone {
  border: 1.5px solid var(--hl-danger);
}

@media (max-width: 600px) {
  .hl-profile-identity {
    align-items: flex-start;
  }
}
</style>
