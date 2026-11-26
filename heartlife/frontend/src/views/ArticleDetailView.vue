<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bookmark, ExternalLink, ShieldCheck, Square, Volume2 } from 'lucide-vue-next'
import { api, ApiClientError, toggleBookmarkApi } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { formatDateTimeShort, splitPlainParagraphs } from '../utils/format'
import PageHeader from '../components/common/PageHeader.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import HlAlert from '../components/ui/HlAlert.vue'
import HlBadge from '../components/ui/HlBadge.vue'
import type { ArticleDetail } from '../types/api'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const articleId = computed(() => String(route.params.id || ''))
const article = ref<ArticleDetail | null>(null)
const loading = ref(true)
const unavailable = ref(false)
const errorMessage = ref('')
const bookmarked = ref(false)
const bookmarkPending = ref(false)
const speaking = ref(false)

const ttsSupported =
  typeof window !== 'undefined' &&
  'speechSynthesis' in window &&
  Boolean(window.speechSynthesis) &&
  typeof window.SpeechSynthesisUtterance !== 'undefined'

const bodyParagraphs = computed(() => splitPlainParagraphs(article.value?.body))

function sanitizeExternalHttpsUrl(raw: string | null | undefined): string | null {
  if (!raw || typeof raw !== 'string') return null
  const trimmed = raw.trim()
  if (!trimmed.startsWith('https://')) return null
  try {
    const parsed = new URL(trimmed)
    if (parsed.protocol !== 'https:' || !parsed.hostname || parsed.username || parsed.password) {
      return null
    }
    return parsed.toString()
  } catch {
    return null
  }
}

function stopSpeech() {
  if (typeof window !== 'undefined' && 'speechSynthesis' in window && window.speechSynthesis) {
    try {
      window.speechSynthesis.cancel()
    } catch {
      // Ignore browser synthesis cancel errors
    }
  }
  speaking.value = false
}

function handleToggleSpeech() {
  if (!ttsSupported || !article.value) return
  if (speaking.value) {
    stopSpeech()
    return
  }

  window.speechSynthesis.cancel()
  const parts = [article.value.title, article.value.summary, article.value.body]
    .map((s) => (s || '').trim())
    .filter(Boolean)
  const utterance = new window.SpeechSynthesisUtterance(parts.join('。'))
  utterance.lang = 'zh-CN'
  utterance.rate = 0.95
  utterance.onend = () => {
    speaking.value = false
  }
  utterance.onerror = () => {
    speaking.value = false
  }
  speaking.value = true
  window.speechSynthesis.speak(utterance)
}

async function loadArticle() {
  if (!articleId.value) return
  loading.value = true
  unavailable.value = false
  errorMessage.value = ''

  try {
    const data = await api.get<ArticleDetail>(`/articles/${articleId.value}`)
    article.value = data
    bookmarked.value = Boolean(data.viewer_bookmarked ?? data.bookmarked)

    if (auth.isAuthenticated) {
      api.put(`/me/reading-history/${data.id}`).catch(() => {
        // Silent reading history tracking
      })
    }
  } catch (err) {
    if (err instanceof ApiClientError && (err.status === 404 || err.status === 410)) {
      unavailable.value = true
      article.value = null
    } else {
      errorMessage.value = err instanceof ApiClientError ? err.message : '暂时无法加载，请重试'
    }
  } finally {
    loading.value = false
  }
}

async function handleToggleBookmark() {
  if (!auth.isAuthenticated) {
    router.push({ path: '/login', query: { redirect: route.fullPath } })
    return
  }
  if (!article.value || bookmarkPending.value) return
  bookmarkPending.value = true
  try {
    bookmarked.value = await toggleBookmarkApi('article', article.value.id, !bookmarked.value)
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '收藏操作失败'
  } finally {
    bookmarkPending.value = false
  }
}

watch(articleId, () => {
  stopSpeech()
  loadArticle()
})

onMounted(() => {
  loadArticle()
})

onBeforeUnmount(() => {
  stopSpeech()
})
</script>

<template>
  <div class="reading-container stack">
    <PageHeader
      title="科普阅读"
      back-to="/knowledge"
      back-label="返回健康百科"
      style="margin-bottom: 0"
    />

    <LoadingState v-if="loading" :count="1" />

    <EmptyState
      v-else-if="unavailable || (!article && !errorMessage)"
      title="该内容当前不可用"
      description="该科普文章可能正在修订或已下架，您可以浏览其他健康百科内容。"
    >
      <template #actions>
        <RouterLink to="/knowledge" class="btn btn-primary">浏览其他科普</RouterLink>
      </template>
    </EmptyState>

    <ErrorState
      v-else-if="errorMessage && !article"
      title="暂时无法加载，请重试"
      :message="errorMessage"
      show-home-link
      @retry="loadArticle"
    />

    <template v-else-if="article">
      <HlAlert v-if="errorMessage" variant="error">
        {{ errorMessage }}
      </HlAlert>

      <!-- Main Reading Card -->
      <article class="hl-card stack">
        <div class="row-between">
          <div class="row-wrap">
            <HlBadge variant="brand">{{ article.category }}</HlBadge>
            <HlBadge v-if="article.is_demo" variant="neutral">演示</HlBadge>
            <HlBadge variant="neutral" class="tabular">修订 v{{ article.revision }}</HlBadge>
          </div>
        </div>

        <h1 class="page-title user-content">{{ article.title }}</h1>

        <div class="row-between hl-article-meta tabular">
          <span>{{ article.author_byline || 'HeartLife 科普组' }}</span>
          <span v-if="article.updated_at">
            更新于 {{ formatDateTimeShort(article.updated_at) }}
          </span>
          <span v-else-if="article.published_at">
            发布于 {{ formatDateTimeShort(article.published_at) }}
          </span>
        </div>

        <!-- >=48px Accessible Action Toolbar (Bookmark + Optional Local Speech Synthesis) -->
        <div class="hl-action-toolbar row-wrap" role="toolbar" aria-label="文章操作工具栏">
          <button
            type="button"
            class="btn"
            :class="bookmarked ? 'btn-soft' : 'btn-secondary'"
            :aria-pressed="bookmarked ? 'true' : 'false'"
            :disabled="bookmarkPending"
            @click="handleToggleBookmark"
          >
            <Bookmark :size="20" :fill="bookmarked ? 'currentColor' : 'none'" aria-hidden="true" />
            <span>{{ bookmarked ? '已收藏' : '收藏文章' }}</span>
          </button>

          <button
            v-if="ttsSupported"
            type="button"
            class="btn"
            :class="speaking ? 'btn-accent' : 'btn-secondary'"
            :aria-pressed="speaking ? 'true' : 'false'"
            @click="handleToggleSpeech"
          >
            <Square v-if="speaking" :size="20" aria-hidden="true" />
            <Volume2 v-else :size="20" aria-hidden="true" />
            <span>{{ speaking ? '停止朗读' : '朗读全文' }}</span>
          </button>
        </div>

        <p v-if="article.summary" class="hl-article-lead user-content">
          {{ article.summary }}
        </p>

        <!-- Senior-Friendly 19px / 1.8 Line-Height Plain-Text Reading Body -->
        <div class="hl-reading-body">
          <p v-for="(para, idx) in bodyParagraphs" :key="idx" class="plain-paragraph">
            {{ para }}
          </p>
        </div>
      </article>

      <!-- Bottom Transparency & Medical Boundary Card (UI-T21 & T-0504) -->
      <section class="hl-card-soft stack" aria-label="课程内容审核与参考来源">
        <div class="stack-sm">
          <div class="row-wrap">
            <ShieldCheck :size="22" style="color: var(--hl-brand)" aria-hidden="true" />
            <h2 class="card-title">课程内容审核</h2>
            <HlBadge v-if="article.review_record?.review_type" variant="brand">
              {{ article.review_record.review_type }}
            </HlBadge>
          </div>

          <div v-if="article.review_record" class="hl-review-box stack-sm">
            <div class="row-wrap text-sm tabular">
              <span><strong>核验人：</strong>{{ article.review_record.reviewer }}</span>
              <span v-if="article.review_record.reviewed_at">
                · <strong>核验日期：</strong>{{ article.review_record.reviewed_at }}
              </span>
            </div>
            <p v-if="article.review_record.note" class="text-sm hl-muted" style="margin: 0">
              审核说明：{{ article.review_record.note }}
            </p>
          </div>
        </div>

        <div v-if="article.sources && article.sources.length > 0" class="stack-sm">
          <h3 class="card-title">参考来源</h3>
          <ul class="hl-source-list">
            <li v-for="(src, idx) in article.sources" :key="idx" class="hl-source-item">
              <template v-if="sanitizeExternalHttpsUrl(src.url)">
                <a
                  :href="sanitizeExternalHttpsUrl(src.url)!"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="hl-source-link"
                >
                  <span>{{ src.title || src.url }}</span>
                  <ExternalLink :size="16" aria-hidden="true" />
                </a>
              </template>
              <span v-else>{{ src.title || src.url }}</span>
              <span v-if="src.accessed_at" class="hl-muted text-sm tabular">
                （访问日期：{{ src.accessed_at }}）
              </span>
            </li>
          </ul>
        </div>

        <HlAlert v-if="article.scope_note" variant="warning" role="note">
          {{ article.scope_note }}
        </HlAlert>
      </section>
    </template>
  </div>
</template>

<style scoped>
.hl-article-meta {
  font-size: var(--hl-caption);
  color: var(--hl-text-muted);
}

.hl-action-toolbar {
  padding: 14px 0;
  border-top: 1px solid var(--hl-border);
  border-bottom: 1px solid var(--hl-border);
}

.hl-article-lead {
  margin: 0;
  padding: 14px 18px;
  border-radius: var(--hl-radius-sm);
  background: var(--hl-canvas);
  border-left: 4px solid var(--hl-brand);
  color: var(--hl-text);
  font-size: var(--hl-body);
  line-height: 1.7;
}

.hl-reading-body {
  padding: 6px 0;
}

.hl-reading-body :deep(.plain-paragraph),
.hl-reading-body .plain-paragraph {
  font-size: var(--hl-reading, 1.1875rem);
  line-height: 1.8;
  margin: 0 0 22px;
  color: var(--hl-text);
}

.hl-reading-body .plain-paragraph:last-child {
  margin-bottom: 0;
}

.hl-review-box {
  padding: 12px 16px;
  background: var(--hl-surface);
  border: 1px solid var(--hl-border);
  border-radius: var(--hl-radius-sm);
}

.hl-source-list {
  margin: 0;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  font-size: var(--hl-caption);
  line-height: 1.6;
}

.hl-source-item {
  color: var(--hl-text);
}

.hl-source-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-weight: 600;
  color: var(--hl-brand);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.hl-source-link:hover {
  color: var(--hl-brand-hover);
}
</style>
