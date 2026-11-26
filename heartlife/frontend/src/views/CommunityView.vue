<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, type Component } from 'vue'
import { useRouter } from 'vue-router'
import {
  BookOpen,
  Footprints,
  HeartPulse,
  MoonStar,
  NotebookPen,
  Search,
  ShieldCheck,
  Smile,
  X,
} from 'lucide-vue-next'
import { api, apiRequest, ApiClientError } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { COMMUNITY_CATEGORIES, REPORT_REASON_OPTIONS } from '../utils/format'
import communityEmptySvg from '../assets/heartlife/illustrations/community-empty.svg'
import PageHeader from '../components/common/PageHeader.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import HlAlert from '../components/ui/HlAlert.vue'
import HlDialog from '../components/ui/HlDialog.vue'
import PostCard from '../components/community/PostCard.vue'
import type { PostSummary } from '../types/api'

const auth = useAuthStore()
const router = useRouter()

const CATEGORY_ICONS: Record<string, Component> = {
  日常健康: Smile,
  运动与习惯: Footprints,
  睡眠与休息: MoonStar,
  心脏健康科普交流: BookOpen,
  设备使用经验: HeartPulse,
}

const selectedCategory = ref('')
const followedOnly = ref(false)
const followedCategories = ref<string[]>([])
const searchQuery = ref('')
const appliedSearch = ref('')

const posts = ref<PostSummary[]>([])
const nextCursor = ref<string | null>(null)
const loading = ref(true)
const loadingMore = ref(false)
const slowLoading = ref(false)
const timedOutLoading = ref(false)
const errorMessage = ref('')
const bannerMessage = ref('')

// Monotonic sequence + AbortController to prevent stale out-of-order responses (UI-T14)
let latestRequestSeq = 0
let activeAbortController: AbortController | null = null
let slowTimerId: ReturnType<typeof setTimeout> | null = null
let timeoutTimerId: ReturnType<typeof setTimeout> | null = null

// Create Post Dialog
const createOpen = ref(false)
const newTitle = ref('')
const newCategory = ref<string>(COMMUNITY_CATEGORIES[0])
const newTagsRaw = ref('')
const newBody = ref('')
const creating = ref(false)
const createError = ref('')

// Report Post Dialog (triggered from PostCard menu)
const reportOpen = ref(false)
const reportTargetPost = ref<PostSummary | null>(null)
const reportReason = ref(REPORT_REASON_OPTIONS[0].value)
const reportDetail = ref('')
const submittingReport = ref(false)

const hasActiveFilter = computed(
  () => Boolean(selectedCategory.value || followedOnly.value || appliedSearch.value)
)

function clearLoadingTimers() {
  if (slowTimerId !== null) {
    clearTimeout(slowTimerId)
    slowTimerId = null
  }
  if (timeoutTimerId !== null) {
    clearTimeout(timeoutTimerId)
    timeoutTimerId = null
  }
}

async function loadFollows() {
  if (!auth.isAuthenticated) return
  try {
    const res = await api.get<{ categories?: string[]; items?: string[] }>('/me/follows/categories')
    followedCategories.value = res.categories || res.items || []
  } catch {
    // Keep silent if unauthenticated
  }
}

async function loadPosts(reset = true) {
  const seq = ++latestRequestSeq
  if (reset) {
    if (activeAbortController) {
      activeAbortController.abort()
    }
    activeAbortController = typeof AbortController !== 'undefined' ? new AbortController() : null
    loading.value = true
    slowLoading.value = false
    timedOutLoading.value = false
    nextCursor.value = null
    clearLoadingTimers()

    slowTimerId = setTimeout(() => {
      if (seq === latestRequestSeq && loading.value) {
        slowLoading.value = true
      }
    }, 10000)

    timeoutTimerId = setTimeout(() => {
      if (seq === latestRequestSeq && loading.value) {
        timedOutLoading.value = true
      }
    }, 15000)
  } else {
    loadingMore.value = true
  }

  errorMessage.value = ''
  const cleanSearch = searchQuery.value.trim()
  if (reset) {
    appliedSearch.value = cleanSearch
  }

  try {
    const res = await apiRequest<{ items: PostSummary[]; next_cursor?: string | null }>('/posts', {
      method: 'GET',
      signal: reset && activeAbortController ? activeAbortController.signal : undefined,
      params: {
        category: followedOnly.value ? undefined : selectedCategory.value || undefined,
        followed_only: followedOnly.value ? true : undefined,
        q: cleanSearch || undefined,
        cursor: reset ? undefined : nextCursor.value || undefined,
        limit: 15,
      },
    })

    // Discard out-of-order response if user already changed filters (UI-T14)
    if (seq !== latestRequestSeq) return

    if (reset) {
      posts.value = res.items || []
    } else {
      posts.value.push(...(res.items || []))
    }
    nextCursor.value = res.next_cursor ?? null
  } catch (err) {
    if (seq !== latestRequestSeq) return
    if (err instanceof DOMException && err.name === 'AbortError') return
    errorMessage.value = err instanceof ApiClientError ? err.message : '暂时无法加载，请重试'
  } finally {
    if (seq === latestRequestSeq) {
      clearLoadingTimers()
      loading.value = false
      loadingMore.value = false
      slowLoading.value = false
      timedOutLoading.value = false
    }
  }
}

function selectCategory(cat: string) {
  followedOnly.value = false
  selectedCategory.value = cat
  loadPosts(true)
}

function selectFollowedFeed() {
  selectedCategory.value = ''
  followedOnly.value = true
  loadPosts(true)
}

function clearAllFilters() {
  selectedCategory.value = ''
  followedOnly.value = false
  searchQuery.value = ''
  appliedSearch.value = ''
  loadPosts(true)
}

async function toggleCategoryFollow(cat: string) {
  if (!auth.isAuthenticated) {
    router.push({ path: '/login', query: { redirect: '/community' } })
    return
  }
  const isFollowed = followedCategories.value.includes(cat)
  try {
    const encoded = encodeURIComponent(cat)
    if (isFollowed) {
      await api.delete(`/me/follows/categories/${encoded}`)
      followedCategories.value = followedCategories.value.filter((c) => c !== cat)
    } else {
      await api.put(`/me/follows/categories/${encoded}`)
      followedCategories.value.push(cat)
    }
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '更新关注状态失败'
  }
}

function openCreateModal() {
  if (!auth.isAuthenticated) {
    router.push({ path: '/login', query: { redirect: '/community' } })
    return
  }
  createError.value = ''
  createOpen.value = true
}

async function submitPost() {
  createError.value = ''
  const title = newTitle.value.trim()
  const body = newBody.value.trim()
  if (!title || !body) {
    createError.value = '请填写分享标题与内容正文'
    return
  }
  const tags = newTagsRaw.value
    .split(/[,，\s]+/)
    .map((t) => t.trim())
    .filter(Boolean)
    .slice(0, 5)

  creating.value = true
  try {
    const created = await api.post<{ id?: string; status?: string }>('/posts', {
      title,
      category: newCategory.value,
      tags,
      body,
    })
    createOpen.value = false
    newTitle.value = ''
    newTagsRaw.value = ''
    newBody.value = ''

    // UI-T16: Never claim public publication if server indicates pending moderation
    if (created?.status && created.status !== 'visible') {
      bannerMessage.value = '内容已提交，当前处于待审核状态，审核通过后将公开展示。'
      await loadPosts(true)
    } else if (created?.id) {
      await router.push(`/community/${created.id}`)
    } else {
      bannerMessage.value = '动态已发布'
      await loadPosts(true)
    }
  } catch (err) {
    // UI-T15: Preserve user draft input on error!
    createError.value = err instanceof ApiClientError ? err.message : '发布暂时失败，您的输入内容已保留，请重试'
  } finally {
    creating.value = false
  }
}

function openCardReport(post: PostSummary) {
  reportTargetPost.value = post
  reportReason.value = REPORT_REASON_OPTIONS[0].value
  reportDetail.value = ''
  reportOpen.value = true
}

async function handleSubmitReport() {
  if (!reportTargetPost.value) return
  submittingReport.value = true
  try {
    await api.post('/reports', {
      target_type: 'post',
      target_id: reportTargetPost.value.id,
      reason: reportReason.value,
      detail: reportDetail.value.trim(),
    })
    reportOpen.value = false
    bannerMessage.value = '举报已提交，社区审核员将尽快核查处理。'
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '举报提交失败，请稍后重试'
  } finally {
    submittingReport.value = false
  }
}

onMounted(() => {
  loadFollows()
  loadPosts(true)
})

onUnmounted(() => {
  clearLoadingTimers()
  if (activeAbortController) {
    activeAbortController.abort()
  }
})
</script>

<template>
  <div class="stack">
    <PageHeader
      title="同伴社区"
      subtitle="分享健康生活中的小事，互相鼓励、共同坚持。"
    >
      <template #actions>
        <button
          type="button"
          data-testid="community-open-publish"
          class="btn btn-primary"
          @click="openCreateModal"
        >
          <NotebookPen :size="20" aria-hidden="true" />
          <span>发布动态</span>
        </button>
      </template>
    </PageHeader>

    <HlAlert v-if="bannerMessage" variant="success">
      {{ bannerMessage }}
    </HlAlert>

    <!-- Search & Flat Topic Filter Bar -->
    <section class="hl-card stack-sm" aria-label="搜索与话题筛选">
      <form role="search" class="hl-search-bar" @submit.prevent="loadPosts(true)">
        <label for="community-search" class="sr-only">搜索社区内容</label>
        <div class="hl-search-input-wrap">
          <Search :size="20" class="hl-search-icon" aria-hidden="true" />
          <input
            id="community-search"
            v-model="searchQuery"
            type="search"
            class="input hl-search-input"
            placeholder="搜索生活经验、散步、睡眠话题..."
          />
        </div>
        <button type="submit" class="btn btn-secondary">搜索</button>
        <button
          v-if="hasActiveFilter"
          type="button"
          data-testid="community-clear-filters"
          class="btn btn-ghost"
          @click="clearAllFilters"
        >
          <X :size="18" aria-hidden="true" />
          <span>清除筛选</span>
        </button>
      </form>

      <div class="row-between" style="padding-top: 4px">
        <div class="row-wrap" role="group" aria-label="话题分类">
          <button
            type="button"
            class="pill"
            :class="{ 'pill-active': !followedOnly && selectedCategory === '' }"
            :aria-pressed="!followedOnly && selectedCategory === ''"
            @click="selectCategory('')"
          >
            全部
          </button>

          <button
            v-if="auth.isAuthenticated"
            type="button"
            class="pill"
            :class="{ 'pill-active': followedOnly }"
            :aria-pressed="followedOnly"
            @click="selectFollowedFeed"
          >
            关注
          </button>

          <button
            v-for="cat in COMMUNITY_CATEGORIES"
            :key="cat"
            type="button"
            class="pill"
            :class="{ 'pill-active': !followedOnly && selectedCategory === cat }"
            :aria-pressed="!followedOnly && selectedCategory === cat"
            @click="selectCategory(cat)"
          >
            {{ cat }}
          </button>
        </div>

        <button
          v-if="auth.isAuthenticated && selectedCategory"
          type="button"
          class="btn btn-soft btn-sm"
          @click="toggleCategoryFollow(selectedCategory)"
        >
          {{ followedCategories.includes(selectedCategory) ? '已关注该分类' : '+ 关注该分类' }}
        </button>
      </div>
    </section>

    <!-- Mobile Compact Guidelines Disclosure -->
    <details class="hl-mobile-guidelines hl-card-soft">
      <summary class="hl-guidelines-summary">
        <ShieldCheck :size="20" style="color: var(--hl-brand)" aria-hidden="true" />
        <span>查看社区友善公约与隐私提醒</span>
      </summary>
      <ul class="hl-rule-list" style="margin-top: 10px">
        <li>保护个人隐私，请勿发布手机号、住址或未脱敏病历。</li>
        <li>日常经验仅供参考，不替代医院检查、诊断或处方建议。</li>
      </ul>
    </details>

    <!-- Two-Column Community Layout (68% Main Feed / 32% Companion Sidebar on Desktop >=1024px) -->
    <div class="hl-community-grid">
      <!-- Left Main Reading Stream -->
      <div class="stack">
        <LoadingState
          v-if="loading"
          :count="3"
          :slow="slowLoading"
          :timed-out="timedOutLoading"
          @retry="loadPosts(true)"
        />

        <ErrorState
          v-else-if="errorMessage"
          title="暂时无法加载，请重试"
          :message="errorMessage"
          show-home-link
          @retry="loadPosts(true)"
        />

        <!-- UI-T11: Empty Search / Filter Result -->
        <EmptyState
          v-else-if="posts.length === 0 && hasActiveFilter"
          title="没有找到相关内容"
          description="可以换个关键词试试，或清除筛选条件浏览全部社区分享。"
        >
          <template #actions>
            <button
              type="button"
              data-testid="community-clear-filters"
              class="btn btn-primary"
              @click="clearAllFilters"
            >
              清除筛选
            </button>
          </template>
        </EmptyState>

        <!-- UI-T12: True Empty Community -->
        <EmptyState
          v-else-if="posts.length === 0"
          :illustration="communityEmptySvg"
          title="还没有内容"
          description="这里用来记录和分享散步、规律作息、清淡饮食等温暖日常。"
        >
          <template #actions>
            <button type="button" class="btn btn-primary" @click="openCreateModal">
              <NotebookPen :size="19" aria-hidden="true" />
              <span>发布动态</span>
            </button>
          </template>
        </EmptyState>

        <!-- Real Post Feed -->
        <template v-else>
          <PostCard
            v-for="post in posts"
            :key="post.id"
            :post="post"
            @report="openCardReport"
            @error="(m) => (errorMessage = m)"
          />

          <div v-if="nextCursor" style="text-align: center; padding-top: 8px">
            <button
              type="button"
              class="btn btn-secondary"
              :disabled="loadingMore"
              @click="loadPosts(false)"
            >
              {{ loadingMore ? '正在加载更多...' : '加载更多分享' }}
            </button>
          </div>
        </template>
      </div>

      <!-- Right 32% Companion Sidebar (Desktop >= 1024px) -->
      <aside class="hl-community-sidebar stack" aria-label="社区指南与话题导览">
        <section class="hl-card-soft stack-sm">
          <div class="row-wrap">
            <ShieldCheck :size="22" style="color: var(--hl-brand)" aria-hidden="true" />
            <h2 class="card-title">社区友善公约</h2>
          </div>
          <ul class="hl-rule-list">
            <li><strong>保护个人隐私：</strong>请勿在帖子或评论中公开电话、微信号或详细病历单。</li>
            <li><strong>不以经验替代诊疗：</strong>不推荐具体药物与剂量；身体不适请及时就医。</li>
            <li><strong>温和倾听鼓励：</strong>尊重每个人的生活节奏，友善交流。</li>
          </ul>
        </section>

        <section class="hl-card stack-sm">
          <h2 class="card-title">浏览话题</h2>
          <div class="hl-topic-nav-list">
            <button
              v-for="cat in COMMUNITY_CATEGORIES"
              :key="cat"
              type="button"
              class="hl-topic-nav-btn"
              :class="{ 'hl-topic-nav-btn-active': !followedOnly && selectedCategory === cat }"
              @click="selectCategory(cat)"
            >
              <component
                :is="CATEGORY_ICONS[cat] || Smile"
                :size="20"
                style="color: var(--hl-brand); flex-shrink: 0"
                aria-hidden="true"
              />
              <span>{{ cat }}</span>
            </button>
          </div>
        </section>

        <section class="hl-card-accent stack-sm">
          <h2 class="card-title" style="color: var(--hl-accent-ink)">交流提示</h2>
          <p class="text-sm" style="margin: 0; color: var(--hl-text)">
            今天完成了散步或早睡打卡？不妨写两句话记录下来，给同行的朋友一点温暖鼓励。
          </p>
          <div>
            <button type="button" class="btn btn-primary btn-sm" @click="openCreateModal">
              <NotebookPen :size="18" aria-hidden="true" />
              <span>写一条动态</span>
            </button>
          </div>
        </section>
      </aside>
    </div>

    <!-- Accessible Create Post Dialog (Reka UI Focus Trap & Esc Restoration) -->
    <HlDialog
      v-model:open="createOpen"
      title="发布社区动态"
      description="分享日常作息、温和运动或科普学习体会。"
      max-width="580px"
    >
      <HlAlert v-if="createError" variant="error">
        {{ createError }}
      </HlAlert>

      <form data-testid="create-post-form" class="stack-sm" @submit.prevent="submitPost">
        <div class="field">
          <label for="post-title-input" class="field-label">标题</label>
          <input
            id="post-title-input"
            v-model="newTitle"
            type="text"
            class="input"
            maxlength="80"
            placeholder="用一句话概括您的分享（1-80字）"
            required
          />
        </div>

        <div class="grid-2">
          <div class="field">
            <label for="post-cat-select" class="field-label">所属话题</label>
            <select id="post-cat-select" v-model="newCategory" class="select">
              <option v-for="c in COMMUNITY_CATEGORIES" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>

          <div class="field">
            <label for="post-tags-input" class="field-label">标签（可选，最多5个）</label>
            <input
              id="post-tags-input"
              v-model="newTagsRaw"
              type="text"
              class="input"
              placeholder="例如：散步 规律作息"
            />
          </div>
        </div>

        <div class="field">
          <label for="post-body-input" class="field-label">正文内容</label>
          <textarea
            id="post-body-input"
            v-model="newBody"
            class="textarea"
            rows="5"
            maxlength="3000"
            placeholder="写下您的日常经验或感受..."
            required
          ></textarea>
          <span class="hl-muted text-sm">请勿公开个人联系方式或详细病历，社区交流不替代医生诊疗。</span>
        </div>

        <div class="row-wrap" style="justify-content: flex-end; padding-top: 6px">
          <button type="button" class="btn btn-secondary" @click="createOpen = false">
            取消
          </button>
          <button type="submit" class="btn btn-primary" :disabled="creating">
            {{ creating ? '正在发布...' : '确认发布' }}
          </button>
        </div>
      </form>
    </HlDialog>

    <!-- Accessible Report Dialog -->
    <HlDialog
      v-model:open="reportOpen"
      title="举报不当内容"
      description="感谢您协助维护温暖、安全的交流环境，审核员将核实处理。"
      max-width="480px"
    >
      <form class="stack-sm" @submit.prevent="handleSubmitReport">
        <div class="field">
          <label for="community-report-reason" class="field-label">举报原因</label>
          <select id="community-report-reason" v-model="reportReason" class="select">
            <option v-for="r in REPORT_REASON_OPTIONS" :key="r.value" :value="r.value">
              {{ r.label }}
            </option>
          </select>
        </div>

        <div class="field">
          <label for="community-report-detail" class="field-label">补充说明（可选）</label>
          <textarea
            id="community-report-detail"
            v-model="reportDetail"
            class="textarea"
            rows="3"
            maxlength="500"
          ></textarea>
        </div>

        <div class="row-wrap" style="justify-content: flex-end">
          <button type="button" class="btn btn-secondary" @click="reportOpen = false">取消</button>
          <button type="submit" class="btn btn-danger" :disabled="submittingReport">
            {{ submittingReport ? '提交中...' : '提交举报' }}
          </button>
        </div>
      </form>
    </HlDialog>
  </div>
</template>

<style scoped>
.hl-search-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.hl-search-input-wrap {
  position: relative;
  flex: 1 1 240px;
  min-width: 0;
}

.hl-search-icon {
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--hl-text-muted);
  pointer-events: none;
}

.hl-search-input {
  padding-left: 44px;
}

.hl-community-grid {
  display: grid;
  grid-template-columns: minmax(0, 2.1fr) minmax(280px, 1fr);
  gap: 24px;
  align-items: start;
}

.hl-rule-list {
  margin: 0;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  font-size: var(--hl-caption);
  color: var(--hl-text);
  line-height: 1.6;
}

.hl-topic-nav-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.hl-topic-nav-btn {
  width: 100%;
  min-height: var(--hl-target);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 14px;
  border-radius: var(--hl-radius-sm);
  border: 1px solid transparent;
  background: var(--hl-canvas);
  color: var(--hl-text);
  font-family: inherit;
  font-size: var(--hl-caption);
  font-weight: 600;
  text-align: left;
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}

.hl-topic-nav-btn:hover {
  background: var(--hl-surface-soft);
  border-color: var(--hl-brand);
}

.hl-topic-nav-btn-active {
  background: var(--hl-surface-soft);
  border-color: var(--hl-brand);
  color: var(--hl-brand);
  font-weight: 700;
}

.hl-mobile-guidelines {
  display: none;
}

.hl-guidelines-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 44px;
  font-weight: 650;
  cursor: pointer;
}

@media (max-width: 1023px) {
  .hl-community-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .hl-community-sidebar {
    display: none;
  }

  .hl-mobile-guidelines {
    display: block;
  }
}
</style>
