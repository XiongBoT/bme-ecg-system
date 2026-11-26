<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ArrowRight, BookOpen, Search, X } from 'lucide-vue-next'
import { api, apiRequest, ApiClientError } from '../api/client'
import heartCoverSvg from '../assets/heartlife/illustrations/article-cover-heart.svg'
import sleepCoverSvg from '../assets/heartlife/illustrations/article-cover-sleep.svg'
import walkCoverSvg from '../assets/heartlife/illustrations/article-cover-walk.svg'
import communityEmptySvg from '../assets/heartlife/illustrations/community-empty.svg'
import PageHeader from '../components/common/PageHeader.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import HlBadge from '../components/ui/HlBadge.vue'
import type { ArticleSummary } from '../types/api'

const DEFAULT_CATEGORIES = [
  '心脏基础知识',
  '设备与指标解读',
  '睡眠与休息',
  '运动与习惯',
  '日常健康',
  '日常记录方法',
  '就医与沟通',
  '隐私与安全',
]

type ArticleWithOptionalCover = ArticleSummary & {
  cover_url?: string | null
}

const categories = ref<string[]>(DEFAULT_CATEGORIES)
const selectedCategory = ref('')
const searchQuery = ref('')
const appliedSearch = ref('')
const articles = ref<ArticleWithOptionalCover[]>([])
const nextCursor = ref<string | null>(null)

const loading = ref(true)
const loadingMore = ref(false)
const slowLoading = ref(false)
const timedOutLoading = ref(false)
const errorMessage = ref('')
const failedCovers = ref<Record<string, boolean>>({})

let requestSeq = 0
let activeAbortController: AbortController | null = null
let slowTimerId: ReturnType<typeof setTimeout> | null = null
let timeoutTimerId: ReturnType<typeof setTimeout> | null = null

const hasActiveFilter = computed(() => Boolean(selectedCategory.value || appliedSearch.value))

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

function articlePath(art: ArticleSummary): string {
  return `/knowledge/${art.id}`
}

function resolveFallbackCover(art: ArticleSummary): string {
  const combined = `${art.category || ''} ${art.title || ''}`
  if (/睡眠|作息|休息/.test(combined)) {
    return sleepCoverSvg
  }
  if (/运动|活动|散步|步行|锻炼/.test(combined)) {
    return walkCoverSvg
  }
  return heartCoverSvg
}

function resolveCover(art: ArticleWithOptionalCover): string {
  if (failedCovers.value[art.id]) {
    return heartCoverSvg
  }
  const customCover = typeof art.cover_url === 'string' ? art.cover_url.trim() : ''
  if (customCover) {
    return customCover
  }
  return resolveFallbackCover(art)
}

function onCoverError(event: Event, artId: string) {
  failedCovers.value = { ...failedCovers.value, [artId]: true }
  const target = event.target as HTMLImageElement | null
  if (target && target.src !== heartCoverSvg) {
    target.src = heartCoverSvg
  }
}

async function loadCategories() {
  try {
    const res = await api.get<{ categories?: string[] }>('/articles/categories')
    if (Array.isArray(res.categories) && res.categories.length > 0) {
      categories.value = res.categories
    }
  } catch {
    // Keep local fallback categories
  }
}

async function loadArticles(reset = true) {
  const seq = ++requestSeq
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
      if (seq === requestSeq && loading.value) {
        slowLoading.value = true
      }
    }, 10000)

    timeoutTimerId = setTimeout(() => {
      if (seq === requestSeq && loading.value) {
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
    const res = await apiRequest<{
      items: ArticleWithOptionalCover[]
      next_cursor?: string | null
    }>('/articles', {
      method: 'GET',
      signal: reset && activeAbortController ? activeAbortController.signal : undefined,
      params: {
        category: selectedCategory.value || undefined,
        q: cleanSearch || undefined,
        cursor: reset ? undefined : nextCursor.value || undefined,
        limit: 12,
      },
    })

    if (seq !== requestSeq) return

    if (reset) {
      articles.value = res.items || []
    } else {
      articles.value.push(...(res.items || []))
    }
    nextCursor.value = res.next_cursor ?? null
  } catch (err) {
    if (seq !== requestSeq) return
    if (err instanceof DOMException && err.name === 'AbortError') return
    errorMessage.value = err instanceof ApiClientError ? err.message : '暂时无法加载，请重试'
  } finally {
    if (seq === requestSeq) {
      clearLoadingTimers()
      loading.value = false
      loadingMore.value = false
      slowLoading.value = false
      timedOutLoading.value = false
    }
  }
}

function selectCategory(cat: string) {
  selectedCategory.value = cat
  loadArticles(true)
}

function clearFilters() {
  selectedCategory.value = ''
  searchQuery.value = ''
  appliedSearch.value = ''
  loadArticles(true)
}

onMounted(() => {
  loadCategories()
  loadArticles(true)
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
      title="健康百科"
      subtitle="经课程内容审核的权威健康科普，陪您安心了解睡眠、运动与日常养护。"
    />

    <!-- Search & Flat Category Filter Toolbar -->
    <section class="hl-card stack-sm" aria-label="百科搜索与分类筛选">
      <form role="search" class="hl-search-bar" @submit.prevent="loadArticles(true)">
        <label for="knowledge-search" class="sr-only">搜索百科</label>
        <div class="hl-search-input-wrap">
          <Search :size="20" class="hl-search-icon" aria-hidden="true" />
          <input
            id="knowledge-search"
            v-model="searchQuery"
            type="search"
            class="input hl-search-input"
            placeholder="搜索睡眠、散步、心率记录等科普关键词..."
          />
        </div>
        <button type="submit" class="btn btn-secondary">搜索</button>
        <button
          v-if="hasActiveFilter"
          type="button"
          data-testid="knowledge-clear-filters"
          class="btn btn-ghost"
          @click="clearFilters"
        >
          <X :size="18" aria-hidden="true" />
          <span>清除筛选</span>
        </button>
      </form>

      <div class="row-wrap" role="group" aria-label="百科分类" style="padding-top: 4px">
        <button
          type="button"
          class="pill"
          :class="{ 'pill-active': selectedCategory === '' }"
          :aria-pressed="selectedCategory === ''"
          @click="selectCategory('')"
        >
          全部
        </button>
        <button
          v-for="cat in categories"
          :key="cat"
          type="button"
          class="pill"
          :class="{ 'pill-active': selectedCategory === cat }"
          :aria-pressed="selectedCategory === cat"
          @click="selectCategory(cat)"
        >
          {{ cat }}
        </button>
      </div>
    </section>

    <LoadingState
      v-if="loading"
      :count="3"
      :slow="slowLoading"
      :timed-out="timedOutLoading"
      @retry="loadArticles(true)"
    />

    <ErrorState
      v-else-if="errorMessage"
      title="暂时无法加载，请重试"
      :message="errorMessage"
      show-home-link
      @retry="loadArticles(true)"
    />

    <EmptyState
      v-else-if="articles.length === 0 && hasActiveFilter"
      title="没有找到相关内容"
      description="可以换个关键词试试，或清除筛选条件浏览全部健康科普。"
    >
      <template #actions>
        <button type="button" class="btn btn-primary" @click="clearFilters">
          清除筛选
        </button>
      </template>
    </EmptyState>

    <EmptyState
      v-else-if="articles.length === 0"
      :illustration="communityEmptySvg"
      title="还没有内容"
      description="科普文章正在整理更新中，稍后再来看看吧。"
    />

    <div v-else class="stack">
      <div class="grid-3">
        <article
          v-for="art in articles"
          :key="art.id"
          class="hl-card hl-article-card"
        >
          <RouterLink
            :to="articlePath(art)"
            tabindex="-1"
            aria-hidden="true"
            class="hl-article-cover-link"
          >
            <img
              :src="resolveCover(art)"
              alt=""
              aria-hidden="true"
              width="480"
              height="270"
              loading="lazy"
              class="hl-article-cover"
              @error="onCoverError($event, art.id)"
            />
          </RouterLink>

          <div class="hl-article-content stack-sm">
            <div class="row-between">
              <HlBadge variant="brand">{{ art.category }}</HlBadge>
              <HlBadge v-if="art.is_demo" variant="neutral">演示</HlBadge>
            </div>

            <h2 class="hl-article-title">
              <RouterLink :to="articlePath(art)" class="hl-article-title-link">
                {{ art.title }}
              </RouterLink>
            </h2>

            <p class="hl-article-summary user-content">
              {{ art.summary }}
            </p>

            <div class="hl-article-footer row-between">
              <span class="hl-muted text-sm">{{ art.author_byline || 'HeartLife 科普组' }}</span>
              <RouterLink :to="articlePath(art)" class="hl-read-more">
                <BookOpen :size="18" aria-hidden="true" />
                <span>阅读全文</span>
                <ArrowRight :size="17" aria-hidden="true" />
              </RouterLink>
            </div>
          </div>
        </article>
      </div>

      <div v-if="nextCursor" style="text-align: center; padding-top: 8px">
        <button
          type="button"
          class="btn btn-secondary"
          :disabled="loadingMore"
          @click="loadArticles(false)"
        >
          {{ loadingMore ? '正在加载更多...' : '加载更多科普' }}
        </button>
      </div>
    </div>
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

.hl-article-card {
  padding: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  height: 100%;
  transition: border-color 0.15s ease, transform 0.15s ease;
}

.hl-article-card:hover {
  border-color: var(--hl-brand);
}

.hl-article-cover-link {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: var(--hl-surface-soft);
  border-bottom: 1px solid var(--hl-border);
  overflow: hidden;
}

.hl-article-cover {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.hl-article-content {
  padding: var(--hl-space-5);
  flex: 1;
  display: flex;
  flex-direction: column;
}

.hl-article-title {
  margin: 0;
  font-size: var(--hl-card-title);
  line-height: 1.45;
  font-weight: 700;
}

.hl-article-title-link {
  color: var(--hl-text);
  overflow-wrap: anywhere;
}

.hl-article-title-link:hover {
  color: var(--hl-brand);
}

.hl-article-summary {
  margin: 0;
  flex: 1;
  font-size: var(--hl-caption);
  color: var(--hl-text-muted);
  line-height: 1.65;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.hl-article-footer {
  padding-top: 12px;
  margin-top: 4px;
  border-top: 1px solid var(--hl-border);
}

.hl-read-more {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 44px;
  font-size: var(--hl-caption);
  font-weight: 650;
  color: var(--hl-brand);
}

.hl-read-more:hover {
  color: var(--hl-brand-hover);
}
</style>
