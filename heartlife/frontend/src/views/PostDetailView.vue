<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Ban,
  Bookmark,
  Edit3,
  Flag,
  Heart,
  MessageCircle,
  Send,
  Trash2,
} from 'lucide-vue-next'
import { api, ApiClientError, toggleBookmarkApi } from '../api/client'
import { useAuthStore } from '../stores/auth'
import {
  COMMUNITY_CATEGORIES,
  formatDateTimeShort,
  makeRequestId,
  REPORT_REASON_OPTIONS,
  splitPlainParagraphs,
} from '../utils/format'
import PageHeader from '../components/common/PageHeader.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import ConfirmDialog from '../components/common/ConfirmDialog.vue'
import HlAlert from '../components/ui/HlAlert.vue'
import HlAvatar from '../components/ui/HlAvatar.vue'
import HlBadge from '../components/ui/HlBadge.vue'
import HlDialog from '../components/ui/HlDialog.vue'
import type { CommentItem, PostDetail } from '../types/api'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const postId = computed(() => String(route.params.id || ''))
const post = ref<PostDetail | null>(null)
const comments = ref<CommentItem[]>([])

const loading = ref(true)
const unavailable = ref(false)
const errorMessage = ref('')
const statusMessage = ref('')

// Like / Bookmark local state
const viewerLiked = ref(false)
const likeCount = ref(0)
const viewerBookmarked = ref(false)
const actionPending = ref(false)

// Edit Post Dialog
const editOpen = ref(false)
const editTitle = ref('')
const editCategory = ref<string>(COMMUNITY_CATEGORIES[0])
const editBody = ref('')
const savingEdit = ref(false)

// Delete Post Confirm Dialog
const deleteConfirmOpen = ref(false)

// Comment Form (preserves input + request_id on error per PRD §3 & UI-T15)
const commentBody = ref('')
const replyTo = ref<CommentItem | null>(null)
const pendingCommentRequestId = ref(makeRequestId())
const submittingComment = ref(false)
const commentError = ref('')

// Report Modal
const reportOpen = ref(false)
const reportTargetType = ref<'post' | 'comment'>('post')
const reportTargetId = ref('')
const reportReason = ref(REPORT_REASON_OPTIONS[0].value)
const reportDetail = ref('')
const submittingReport = ref(false)

const authorId = computed(() => post.value?.author?.id || post.value?.author_id || '')
const authorName = computed(() => post.value?.author?.nickname || post.value?.author_nickname || '社区成员')
const isAuthor = computed(() => Boolean(auth.user && authorId.value === auth.user.id))

const bodyParagraphs = computed(() => splitPlainParagraphs(post.value?.body))

interface GroupedComment extends CommentItem {
  childReplies: CommentItem[]
}

const groupedComments = computed<GroupedComment[]>(() => {
  const topMap = new Map<string, GroupedComment>()
  const topList: GroupedComment[] = []

  for (const item of comments.value) {
    if (!item.parent_id) {
      const node: GroupedComment = {
        ...item,
        childReplies: Array.isArray(item.replies) ? [...item.replies] : [],
      }
      topMap.set(item.id, node)
      topList.push(node)
    }
  }

  for (const item of comments.value) {
    if (item.parent_id) {
      const parent = topMap.get(item.parent_id)
      if (parent && !parent.childReplies.some((r) => r.id === item.id)) {
        parent.childReplies.push(item)
      } else if (!parent) {
        topList.push({ ...item, childReplies: [] })
      }
    }
  }
  return topList
})

function commentAuthorName(c: CommentItem): string {
  return c.author?.nickname || c.author_nickname || '社区成员'
}

function commentAuthorId(c: CommentItem): string {
  return c.author?.id || c.author_id || ''
}

function requireLogin(): boolean {
  if (!auth.isAuthenticated) {
    router.push({ path: '/login', query: { redirect: route.fullPath } })
    return false
  }
  return true
}

async function loadPostAndComments() {
  if (!postId.value) return
  loading.value = true
  unavailable.value = false
  errorMessage.value = ''

  try {
    const detail = await api.get<PostDetail>(`/posts/${postId.value}`)
    post.value = detail
    viewerLiked.value = Boolean(detail.viewer_liked ?? detail.liked)
    likeCount.value = detail.like_count ?? detail.likes_count ?? 0
    viewerBookmarked.value = Boolean(detail.viewer_bookmarked ?? detail.bookmarked)

    const cRes = await api.get<{ items?: CommentItem[] } | CommentItem[]>(
      `/posts/${postId.value}/comments`
    )
    comments.value = Array.isArray(cRes) ? cRes : cRes.items || []
  } catch (err) {
    if (err instanceof ApiClientError && (err.status === 404 || err.status === 410)) {
      unavailable.value = true
      post.value = null
    } else {
      errorMessage.value = err instanceof ApiClientError ? err.message : '暂时无法加载，请重试'
    }
  } finally {
    loading.value = false
  }
}

async function handleToggleLike() {
  if (!requireLogin() || !post.value || actionPending.value) return
  actionPending.value = true
  const next = !viewerLiked.value
  try {
    if (next) {
      const res = await api.put<{ like_count?: number }>(`/posts/${post.value.id}/like`)
      viewerLiked.value = true
      likeCount.value = typeof res?.like_count === 'number' ? res.like_count : likeCount.value + 1
    } else {
      const res = await api.delete<{ like_count?: number }>(`/posts/${post.value.id}/like`)
      viewerLiked.value = false
      likeCount.value =
        typeof res?.like_count === 'number' ? res.like_count : Math.max(0, likeCount.value - 1)
    }
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '操作失败，请重试'
  } finally {
    actionPending.value = false
  }
}

async function handleToggleBookmark() {
  if (!requireLogin() || !post.value || actionPending.value) return
  actionPending.value = true
  const next = !viewerBookmarked.value
  try {
    viewerBookmarked.value = await toggleBookmarkApi('post', post.value.id, next)
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '收藏操作失败'
  } finally {
    actionPending.value = false
  }
}

function openEditModal() {
  if (!post.value) return
  editTitle.value = post.value.title
  editCategory.value = post.value.category
  editBody.value = post.value.body
  editOpen.value = true
}

async function handleSaveEdit() {
  if (!post.value || !editTitle.value.trim() || !editBody.value.trim()) return
  savingEdit.value = true
  errorMessage.value = ''
  try {
    await api.patch(`/posts/${post.value.id}`, {
      title: editTitle.value.trim(),
      category: editCategory.value,
      body: editBody.value.trim(),
    })
    editOpen.value = false
    statusMessage.value = '内容已更新'
    await loadPostAndComments()
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '更新失败'
  } finally {
    savingEdit.value = false
  }
}

async function handleConfirmDeletePost() {
  if (!post.value) return
  actionPending.value = true
  try {
    await api.delete(`/posts/${post.value.id}`)
    deleteConfirmOpen.value = false
    await router.push('/community')
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '删除失败'
  } finally {
    actionPending.value = false
  }
}

async function handleBlockAuthor() {
  if (!requireLogin() || !authorId.value) return
  try {
    await api.put(`/me/blocks/${authorId.value}`)
    statusMessage.value = '已屏蔽该作者，后续将自动过滤其公开内容'
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '屏蔽失败'
  }
}

function openReport(targetType: 'post' | 'comment', targetId: string) {
  if (!requireLogin()) return
  reportTargetType.value = targetType
  reportTargetId.value = targetId
  reportReason.value = REPORT_REASON_OPTIONS[0].value
  reportDetail.value = ''
  reportOpen.value = true
}

async function handleSubmitReport() {
  submittingReport.value = true
  try {
    await api.post('/reports', {
      target_type: reportTargetType.value,
      target_id: reportTargetId.value,
      reason: reportReason.value,
      detail: reportDetail.value.trim(),
    })
    reportOpen.value = false
    statusMessage.value = '举报已提交，感谢共同维护社区环境'
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '举报提交失败'
  } finally {
    submittingReport.value = false
  }
}

async function handleSubmitComment() {
  if (!requireLogin() || !post.value) return
  const cleanBody = commentBody.value.trim()
  if (!cleanBody) {
    commentError.value = '请输入评论内容'
    return
  }

  submittingComment.value = true
  commentError.value = ''
  try {
    await api.post(`/posts/${post.value.id}/comments`, {
      body: cleanBody,
      parent_id: replyTo.value ? replyTo.value.id : null,
      request_id: pendingCommentRequestId.value,
    })
    // Only clear input on real server success!
    commentBody.value = ''
    replyTo.value = null
    pendingCommentRequestId.value = makeRequestId()
    await loadPostAndComments()
  } catch (err) {
    commentError.value = err instanceof ApiClientError ? err.message : '评论发送失败，内容已为您保留'
  } finally {
    submittingComment.value = false
  }
}

watch(postId, () => {
  loadPostAndComments()
})

onMounted(() => {
  loadPostAndComments()
})
</script>

<template>
  <div class="reading-container stack">
    <PageHeader title="" back-to="/community" back-label="返回同伴社区" style="margin-bottom: 0" />

    <HlAlert v-if="statusMessage" variant="success">
      {{ statusMessage }}
    </HlAlert>

    <LoadingState v-if="loading" :count="1" />

    <EmptyState
      v-else-if="unavailable || (!post && !errorMessage)"
      title="该内容当前不可用"
      description="可能已被作者删除或正在由社区管理员复核。"
    >
      <template #actions>
        <RouterLink to="/community" class="btn btn-primary">返回社区列表</RouterLink>
      </template>
    </EmptyState>

    <ErrorState
      v-else-if="errorMessage && !post"
      title="暂时无法加载，请重试"
      :message="errorMessage"
      show-home-link
      @retry="loadPostAndComments"
    />

    <template v-else-if="post">
      <HlAlert v-if="errorMessage" variant="error">
        {{ errorMessage }}
      </HlAlert>

      <article class="hl-card stack">
        <!-- Author Header -->
        <div class="row-between">
          <div class="row-wrap" style="gap: 12px">
            <HlAvatar :name="authorName" size="md" />
            <div>
              <div class="row-wrap" style="gap: 8px">
                <RouterLink v-if="authorId" :to="`/users/${authorId}`" class="hl-detail-author">
                  {{ authorName }}
                </RouterLink>
                <span v-else class="hl-detail-author">{{ authorName }}</span>
                <HlBadge variant="brand">{{ post.category }}</HlBadge>
                <HlBadge v-if="post.is_demo" variant="neutral">演示</HlBadge>
              </div>
              <time class="hl-muted text-sm tabular" :datetime="post.created_at">
                {{ formatDateTimeShort(post.created_at) }}
              </time>
            </div>
          </div>
        </div>

        <h1 class="page-title user-content">{{ post.title }}</h1>

        <div v-if="post.tags && post.tags.length > 0" class="row-wrap">
          <HlBadge v-for="t in post.tags" :key="t" variant="neutral">#{{ t }}</HlBadge>
        </div>

        <HlAlert v-if="post.safety_notice" variant="warning" role="note">
          {{ post.safety_notice }}
        </HlAlert>

        <!-- Strictly Safe Plain-Text Paragraph Rendering (Zero v-html!) -->
        <div class="hl-detail-body">
          <p v-for="(para, idx) in bodyParagraphs" :key="idx" class="plain-paragraph">
            {{ para }}
          </p>
        </div>

        <!-- Unified Bordered 48px Action Buttons -->
        <div class="row-between hl-detail-actions">
          <div class="row-wrap">
            <button
              type="button"
              class="btn btn-sm"
              :class="viewerLiked ? 'btn-soft' : 'btn-secondary'"
              :aria-pressed="viewerLiked ? 'true' : 'false'"
              :disabled="actionPending"
              @click="handleToggleLike"
            >
              <Heart :size="19" :fill="viewerLiked ? 'currentColor' : 'none'" aria-hidden="true" />
              <span>{{ viewerLiked ? '已赞' : '点赞' }}</span>
              <span class="tabular">({{ likeCount }})</span>
            </button>

            <button
              type="button"
              class="btn btn-sm"
              :class="viewerBookmarked ? 'btn-soft' : 'btn-secondary'"
              :aria-pressed="viewerBookmarked ? 'true' : 'false'"
              :disabled="actionPending"
              @click="handleToggleBookmark"
            >
              <Bookmark
                :size="19"
                :fill="viewerBookmarked ? 'currentColor' : 'none'"
                aria-hidden="true"
              />
              <span>{{ viewerBookmarked ? '已收藏' : '收藏' }}</span>
            </button>
          </div>

          <div class="row-wrap">
            <template v-if="isAuthor">
              <button type="button" class="btn btn-secondary btn-sm" @click="openEditModal">
                <Edit3 :size="18" aria-hidden="true" />
                <span>编辑</span>
              </button>
              <button
                type="button"
                class="btn btn-danger btn-sm"
                :disabled="actionPending"
                @click="deleteConfirmOpen = true"
              >
                <Trash2 :size="18" aria-hidden="true" />
                <span>删除</span>
              </button>
            </template>
            <template v-else-if="auth.isAuthenticated">
              <button type="button" class="btn btn-secondary btn-sm" @click="handleBlockAuthor">
                <Ban :size="18" aria-hidden="true" />
                <span>屏蔽作者</span>
              </button>
              <button
                type="button"
                class="btn btn-secondary btn-sm"
                @click="openReport('post', post.id)"
              >
                <Flag :size="18" aria-hidden="true" />
                <span>举报</span>
              </button>
            </template>
          </div>
        </div>
      </article>

      <!-- Comments Section -->
      <section id="comments" class="hl-card stack">
        <div class="row-wrap">
          <MessageCircle :size="22" style="color: var(--hl-brand)" aria-hidden="true" />
          <h2 class="section-title tabular">全部评论 ({{ comments.length }})</h2>
        </div>

        <form class="stack-sm" @submit.prevent="handleSubmitComment">
          <div v-if="replyTo" class="row-between hl-card-soft">
            <span>正在回复：<strong>{{ commentAuthorName(replyTo) }}</strong></span>
            <button type="button" class="btn btn-secondary btn-sm" @click="replyTo = null">
              取消回复
            </button>
          </div>

          <HlAlert v-if="commentError" variant="error">
            {{ commentError }}
          </HlAlert>

          <div class="field">
            <label for="comment-textarea" class="field-label">写下您的鼓励或交流</label>
            <textarea
              id="comment-textarea"
              v-model="commentBody"
              class="textarea"
              rows="3"
              maxlength="500"
              placeholder="友善分享生活点滴，最多 500 字..."
            ></textarea>
          </div>

          <div style="display: flex; justify-content: flex-end">
            <button type="submit" class="btn btn-primary" :disabled="submittingComment">
              <Send :size="18" aria-hidden="true" />
              <span>{{ submittingComment ? '正在发送...' : '发送评论' }}</span>
            </button>
          </div>
        </form>

        <div v-if="groupedComments.length === 0" class="hl-muted text-sm" style="padding: 8px 0">
          还没有评论，来写下第一句温暖鼓励吧。
        </div>

        <ul v-else class="hl-comment-list">
          <li v-for="c in groupedComments" :key="c.id" class="hl-comment-item stack-sm">
            <div class="row-between">
              <div class="row-wrap" style="gap: 10px">
                <HlAvatar :name="commentAuthorName(c)" size="sm" />
                <RouterLink
                  v-if="commentAuthorId(c)"
                  :to="`/users/${commentAuthorId(c)}`"
                  style="font-weight: 700; color: var(--hl-text)"
                >
                  {{ commentAuthorName(c) }}
                </RouterLink>
                <strong v-else>{{ commentAuthorName(c) }}</strong>
              </div>
              <span class="hl-muted text-sm tabular">{{ formatDateTimeShort(c.created_at) }}</span>
            </div>

            <div class="user-content">{{ c.body }}</div>

            <div class="row-wrap">
              <button type="button" class="btn btn-ghost btn-sm" @click="replyTo = c">
                回复
              </button>
              <button
                v-if="auth.isAuthenticated && commentAuthorId(c) !== auth.user?.id"
                type="button"
                class="btn btn-ghost btn-sm"
                @click="openReport('comment', c.id)"
              >
                <Flag :size="16" aria-hidden="true" />
                <span>举报</span>
              </button>
            </div>

            <!-- 1-Level Replies -->
            <ul v-if="c.childReplies.length > 0" class="hl-reply-list">
              <li v-for="rep in c.childReplies" :key="rep.id" class="hl-reply-item stack-sm">
                <div class="row-between">
                  <div class="row-wrap" style="gap: 8px">
                    <HlAvatar :name="commentAuthorName(rep)" size="sm" />
                    <RouterLink
                      v-if="commentAuthorId(rep)"
                      :to="`/users/${commentAuthorId(rep)}`"
                      style="font-weight: 700; color: var(--hl-text)"
                    >
                      {{ commentAuthorName(rep) }}
                    </RouterLink>
                    <strong v-else>{{ commentAuthorName(rep) }}</strong>
                  </div>
                  <span class="hl-muted text-sm tabular">
                    {{ formatDateTimeShort(rep.created_at) }}
                  </span>
                </div>
                <div class="user-content">{{ rep.body }}</div>
                <div v-if="auth.isAuthenticated && commentAuthorId(rep) !== auth.user?.id">
                  <button
                    type="button"
                    class="btn btn-ghost btn-sm"
                    @click="openReport('comment', rep.id)"
                  >
                    <Flag :size="16" aria-hidden="true" />
                    <span>举报</span>
                  </button>
                </div>
              </li>
            </ul>
          </li>
        </ul>
      </section>
    </template>

    <!-- Accessible Edit Dialog -->
    <HlDialog v-model:open="editOpen" title="编辑分享内容" max-width="560px">
      <div class="field">
        <label for="edit-post-title" class="field-label">标题</label>
        <input id="edit-post-title" v-model="editTitle" type="text" class="input" maxlength="80" />
      </div>
      <div class="field">
        <label for="edit-post-cat" class="field-label">所属话题</label>
        <select id="edit-post-cat" v-model="editCategory" class="select">
          <option v-for="c in COMMUNITY_CATEGORIES" :key="c" :value="c">{{ c }}</option>
        </select>
      </div>
      <div class="field">
        <label for="edit-post-body" class="field-label">正文内容</label>
        <textarea id="edit-post-body" v-model="editBody" class="textarea" rows="5"></textarea>
      </div>
      <div class="row-wrap" style="justify-content: flex-end">
        <button type="button" class="btn btn-secondary" @click="editOpen = false">取消</button>
        <button
          type="button"
          class="btn btn-primary"
          :disabled="savingEdit"
          @click="handleSaveEdit"
        >
          {{ savingEdit ? '保存中...' : '保存修改' }}
        </button>
      </div>
    </HlDialog>

    <!-- Accessible Delete Post Confirmation -->
    <ConfirmDialog
      v-model:open="deleteConfirmOpen"
      title="确认删除这条动态？"
      description="删除后该动态将不再显示在社区列表中。"
      confirm-label="确认删除"
      danger
      :loading="actionPending"
      @confirm="handleConfirmDeletePost"
    />

    <!-- Accessible Report Modal -->
    <HlDialog
      v-model:open="reportOpen"
      title="举报反馈"
      description="请选择举报原因，社区审核员将尽快核实。"
      max-width="480px"
    >
      <div class="field">
        <label for="report-reason" class="field-label">原因</label>
        <select id="report-reason" v-model="reportReason" class="select">
          <option v-for="r in REPORT_REASON_OPTIONS" :key="r.value" :value="r.value">
            {{ r.label }}
          </option>
        </select>
      </div>
      <div class="field">
        <label for="report-detail" class="field-label">补充说明（可选）</label>
        <textarea
          id="report-detail"
          v-model="reportDetail"
          class="textarea"
          rows="3"
          maxlength="500"
        ></textarea>
      </div>
      <div class="row-wrap" style="justify-content: flex-end">
        <button type="button" class="btn btn-secondary" @click="reportOpen = false">取消</button>
        <button
          type="button"
          class="btn btn-danger"
          :disabled="submittingReport"
          @click="handleSubmitReport"
        >
          {{ submittingReport ? '提交中...' : '提交举报' }}
        </button>
      </div>
    </HlDialog>
  </div>
</template>

<style scoped>
.hl-detail-author {
  font-size: 1.0625rem;
  font-weight: 700;
  color: var(--hl-text);
}

.hl-detail-author:hover {
  color: var(--hl-brand);
}

.hl-detail-body {
  padding: 6px 0;
}

.hl-detail-actions {
  padding-top: 16px;
  border-top: 1px solid var(--hl-border);
}

.hl-comment-list,
.hl-reply-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.hl-comment-item {
  padding: 16px;
  border-radius: var(--hl-radius-md);
  background: var(--hl-canvas);
  border: 1px solid var(--hl-border);
}

.hl-reply-list {
  margin-top: 8px;
  padding-left: 16px;
  border-left: 3px solid var(--hl-brand);
}

.hl-reply-item {
  padding: 12px 14px;
  background: var(--hl-surface);
  border-radius: var(--hl-radius-sm);
  border: 1px solid var(--hl-border);
}
</style>
