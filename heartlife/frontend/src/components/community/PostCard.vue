<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Bookmark, Heart, MessageCircle } from 'lucide-vue-next'
import { api, toggleBookmarkApi } from '../../api/client'
import { useAuthStore } from '../../stores/auth'
import { formatDateTimeShort } from '../../utils/format'
import HlAvatar from '../ui/HlAvatar.vue'
import HlBadge from '../ui/HlBadge.vue'
import HlDropdownMenu, { type DropdownActionItem } from '../ui/HlDropdownMenu.vue'
import type { PostSummary } from '../../types/api'

const props = defineProps<{
  post: PostSummary
}>()

const emit = defineEmits<{
  (e: 'report', post: PostSummary): void
  (e: 'error', message: string): void
}>()

const auth = useAuthStore()
const router = useRouter()

const liked = ref(Boolean(props.post.viewer_liked ?? props.post.liked))
const likeCount = ref(props.post.like_count ?? props.post.likes_count ?? 0)
const bookmarked = ref(Boolean(props.post.viewer_bookmarked ?? props.post.bookmarked))
const pending = ref(false)

watch(
  () => props.post,
  (next) => {
    liked.value = Boolean(next.viewer_liked ?? next.liked)
    likeCount.value = next.like_count ?? next.likes_count ?? 0
    bookmarked.value = Boolean(next.viewer_bookmarked ?? next.bookmarked)
  }
)

const authorId = computed(() => props.post.author?.id || props.post.author_id || '')
const authorName = computed(() => props.post.author?.nickname || props.post.author_nickname || '社区成员')
const commentCount = computed(() => props.post.comment_count ?? props.post.comments_count ?? 0)

const excerpt = computed(() => {
  if (props.post.excerpt) return props.post.excerpt
  const raw = props.post.body || ''
  return raw.length > 150 ? `${raw.slice(0, 150)}…` : raw
})

const menuItems = computed<DropdownActionItem[]>(() => {
  const base: DropdownActionItem[] = [{ key: 'open', label: '查看完整内容' }]
  if (!auth.user || auth.user.id !== authorId.value) {
    base.push({ key: 'report', label: '举报不当内容', danger: true })
  }
  return base
})

function ensureAuth(): boolean {
  if (!auth.isAuthenticated) {
    router.push({ path: '/login', query: { redirect: '/community' } })
    return false
  }
  return true
}

async function handleToggleLike() {
  if (!ensureAuth() || pending.value) return
  pending.value = true
  const prevLiked = liked.value
  const prevCount = likeCount.value
  const targetLiked = !prevLiked

  liked.value = targetLiked
  likeCount.value = targetLiked ? prevCount + 1 : Math.max(0, prevCount - 1)

  try {
    if (targetLiked) {
      const res = await api.put<{ liked?: boolean; like_count?: number }>(`/posts/${props.post.id}/like`)
      if (typeof res?.like_count === 'number') likeCount.value = res.like_count
    } else {
      const res = await api.delete<{ liked?: boolean; like_count?: number }>(`/posts/${props.post.id}/like`)
      if (typeof res?.like_count === 'number') likeCount.value = res.like_count
    }
  } catch {
    liked.value = prevLiked
    likeCount.value = prevCount
    emit('error', '点赞操作暂时未成功，请稍后再试')
  } finally {
    pending.value = false
  }
}

async function handleToggleBookmark() {
  if (!ensureAuth() || pending.value) return
  pending.value = true
  const prev = bookmarked.value
  bookmarked.value = !prev
  try {
    bookmarked.value = await toggleBookmarkApi('post', props.post.id, !prev)
  } catch {
    bookmarked.value = prev
    emit('error', '收藏操作暂时未成功，请稍后再试')
  } finally {
    pending.value = false
  }
}

function handleMenuSelect(key: string) {
  if (key === 'open') {
    router.push(`/community/${props.post.id}`)
  } else if (key === 'report') {
    if (ensureAuth()) {
      emit('report', props.post)
    }
  }
}
</script>

<template>
  <article class="hl-card hl-post-card">
    <!-- Author & Meta Row -->
    <div class="hl-post-meta">
      <div class="hl-post-author-wrap">
        <HlAvatar :name="authorName" size="md" />
        <div class="hl-post-author-text">
          <div class="row-wrap" style="gap: 8px">
            <RouterLink
              v-if="authorId"
              :to="`/users/${authorId}`"
              class="hl-post-author-name"
            >
              {{ authorName }}
            </RouterLink>
            <span v-else class="hl-post-author-name">{{ authorName }}</span>
            <HlBadge variant="brand">{{ post.category }}</HlBadge>
            <HlBadge v-if="post.is_demo" variant="neutral">演示</HlBadge>
          </div>
          <time class="hl-post-time tabular" :datetime="post.created_at">
            {{ formatDateTimeShort(post.created_at) }}
          </time>
        </div>
      </div>
    </div>

    <!-- Title & Plain Text Excerpt -->
    <div class="hl-post-content">
      <h2 class="hl-post-title">
        <RouterLink :to="`/community/${post.id}`" class="hl-post-title-link user-content">
          {{ post.title }}
        </RouterLink>
      </h2>

      <p v-if="excerpt" class="hl-post-excerpt user-content">
        {{ excerpt }}
      </p>

      <div v-if="post.tags && post.tags.length > 0" class="row-wrap" style="margin-top: 4px">
        <span v-for="tag in post.tags" :key="tag" class="hl-topic-tag">
          #{{ tag }}
        </span>
      </div>
    </div>

    <!-- Accessible 48px Action Bar -->
    <div class="hl-post-actions">
      <div class="row-wrap" style="gap: 8px">
        <button
          type="button"
          :data-testid="`post-like-${post.id}`"
          class="btn btn-sm"
          :class="liked ? 'btn-soft' : 'btn-secondary'"
          :aria-pressed="liked ? 'true' : 'false'"
          :disabled="pending"
          @click="handleToggleLike"
        >
          <Heart :size="19" :fill="liked ? 'currentColor' : 'none'" aria-hidden="true" />
          <span>{{ liked ? '已赞' : '点赞' }}</span>
          <span class="tabular">{{ likeCount }}</span>
        </button>

        <RouterLink
          :to="`/community/${post.id}`"
          class="btn btn-secondary btn-sm"
        >
          <MessageCircle :size="19" aria-hidden="true" />
          <span>评论</span>
          <span class="tabular">{{ commentCount }}</span>
        </RouterLink>

        <button
          type="button"
          :data-testid="`post-bookmark-${post.id}`"
          class="btn btn-sm"
          :class="bookmarked ? 'btn-soft' : 'btn-secondary'"
          :aria-pressed="bookmarked ? 'true' : 'false'"
          :disabled="pending"
          @click="handleToggleBookmark"
        >
          <Bookmark :size="19" :fill="bookmarked ? 'currentColor' : 'none'" aria-hidden="true" />
          <span>{{ bookmarked ? '已收藏' : '收藏' }}</span>
        </button>
      </div>

      <HlDropdownMenu
        :items="menuItems"
        :label="`更多操作：${post.title}`"
        @select="handleMenuSelect"
      />
    </div>
  </article>
</template>

<style scoped>
.hl-post-card {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.hl-post-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.hl-post-author-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.hl-post-author-text {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.hl-post-author-name {
  font-size: 1.0625rem; /* 17px */
  font-weight: 700;
  color: var(--hl-text);
}

.hl-post-author-name:hover {
  color: var(--hl-brand);
}

.hl-post-time {
  font-size: 0.9375rem; /* 15px */
  color: var(--hl-text-muted);
}

.hl-post-content {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.hl-post-title {
  margin: 0;
  font-size: var(--hl-card-title); /* 20px default, 24px large */
  line-height: 1.45;
  font-weight: 700;
}

.hl-post-title-link {
  color: var(--hl-text);
}

.hl-post-title-link:hover {
  color: var(--hl-brand);
}

.hl-post-excerpt {
  margin: 0;
  font-size: var(--hl-body);
  line-height: 1.65;
  color: var(--hl-text);
}

.hl-topic-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: 8px;
  background: var(--hl-canvas);
  border: 1px solid var(--hl-border);
  font-size: var(--hl-caption);
  color: var(--hl-text-muted);
}

.hl-post-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  padding-top: 14px;
  border-top: 1px solid var(--hl-border);
}
</style>
