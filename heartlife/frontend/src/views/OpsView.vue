<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { BookOpenCheck, RotateCcw, ShieldCheck } from 'lucide-vue-next'
import { api, ApiClientError } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { formatDateTimeShort, formatLocalDateToday } from '../utils/format'
import PageHeader from '../components/common/PageHeader.vue'
import EmptyState from '../components/common/EmptyState.vue'
import HlAlert from '../components/ui/HlAlert.vue'
import HlBadge from '../components/ui/HlBadge.vue'
import type { ArticleDetail, ArticleSummary, ModerationActionItem, ModerationReportItem } from '../types/api'

const auth = useAuthStore()

const activeSection = ref<'moderation' | 'editor'>(
  auth.isModerator ? 'moderation' : 'editor'
)

const errorMessage = ref('')
const statusMessage = ref('')

// Moderation State
const reportStatusFilter = ref<'pending' | 'actioned' | 'dismissed'>('pending')
const reports = ref<ModerationReportItem[]>([])
const actions = ref<ModerationActionItem[]>([])
const resolveReasonMap = ref<Record<string, string>>({})
const restoreTargetType = ref<'post' | 'comment'>('post')
const restoreTargetId = ref('')
const restoreReason = ref('人工复核恢复')

// Editor State
const editorStatusFilter = ref('')
const editorArticles = ref<ArticleSummary[]>([])
const editingArticleId = ref<string | null>(null)
const artTitle = ref('')
const artCategory = ref('日常健康')
const artSummary = ref('')
const artBody = ref('')
const artByline = ref('HeartLife 课程科普组')
const artScopeNote = ref('仅用于日常健康生活科普参考，不作为个体化临床诊断或用药建议。')
const artSourceTitle = ref('')
const artSourceUrl = ref('')
const artReviewer = ref('课程内容核验组')
const savingArticle = ref(false)

async function loadModeration() {
  if (!auth.isModerator) return
  errorMessage.value = ''
  try {
    const [repRes, actRes] = await Promise.all([
      api.get<{ items?: ModerationReportItem[] } | ModerationReportItem[]>('/moderation/reports', {
        status: reportStatusFilter.value,
      }),
      api
        .get<{ items?: ModerationActionItem[] } | ModerationActionItem[]>('/moderation/actions')
        .catch(() => []),
    ])
    reports.value = Array.isArray(repRes) ? repRes : repRes.items || []
    actions.value = Array.isArray(actRes) ? actRes : actRes.items || []
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '加载审核队列失败'
  }
}

async function resolveReport(rep: ModerationReportItem, decision: 'actioned' | 'dismissed') {
  errorMessage.value = ''
  statusMessage.value = ''
  const reason =
    (resolveReasonMap.value[rep.id] || '').trim() ||
    (decision === 'actioned' ? '违反社区规范已隐藏' : '经复核未违规')

  try {
    try {
      await api.post(`/moderation/reports/${rep.id}/resolve`, {
        decision,
        reason,
      })
    } catch (err) {
      if (err instanceof ApiClientError && err.status === 422) {
        await api.post(`/moderation/reports/${rep.id}/resolve`, {
          action: decision === 'actioned' ? 'hide' : 'dismiss',
          reason,
        })
      } else {
        throw err
      }
    }
    statusMessage.value = decision === 'actioned' ? '已处理并隐藏目标内容' : '已驳回该举报'
    await loadModeration()
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '处理失败'
  }
}

async function restoreContent(targetType: string, targetId: string, customReason?: string) {
  if (!targetId.trim()) return
  errorMessage.value = ''
  statusMessage.value = ''
  try {
    await api.post(`/moderation/content/${targetType}/${targetId.trim()}/restore`, {
      reason: customReason || restoreReason.value.trim() || '复核恢复可见',
    })
    statusMessage.value = '内容已恢复可见'
    restoreTargetId.value = ''
    await loadModeration()
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '恢复失败'
  }
}

// Editor Methods
async function loadEditorArticles() {
  if (!auth.isEditor) return
  errorMessage.value = ''
  try {
    const res = await api.get<{ items?: ArticleSummary[] } | ArticleSummary[]>('/editor/articles', {
      status: editorStatusFilter.value || undefined,
    })
    editorArticles.value = Array.isArray(res) ? res : res.items || []
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '加载百科草稿失败'
  }
}

function resetArticleForm() {
  editingArticleId.value = null
  artTitle.value = ''
  artCategory.value = '日常健康'
  artSummary.value = ''
  artBody.value = ''
  artSourceTitle.value = ''
  artSourceUrl.value = ''
}

async function selectArticleForEdit(art: ArticleSummary) {
  errorMessage.value = ''
  try {
    const full = await api.get<ArticleDetail>(`/editor/articles/${art.id}`)
    editingArticleId.value = full.id
    artTitle.value = full.title
    artCategory.value = full.category
    artSummary.value = full.summary
    artBody.value = full.body
    artByline.value = full.author_byline || 'HeartLife 课程科普组'
    artScopeNote.value = full.scope_note || artScopeNote.value
    if (full.sources && full.sources.length > 0) {
      artSourceTitle.value = full.sources[0].title
      artSourceUrl.value = full.sources[0].url
    }
    if (full.review_record?.reviewer) {
      artReviewer.value = full.review_record.reviewer
    }
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '读取条目详情失败'
  }
}

function buildSourcesAndReview() {
  const today = formatLocalDateToday(auth.user?.timezone)
  const sources =
    artSourceTitle.value.trim() && artSourceUrl.value.trim()
      ? [
          {
            title: artSourceTitle.value.trim(),
            url: artSourceUrl.value.trim(),
            accessed_at: today,
          },
        ]
      : undefined
  const review_record = artReviewer.value.trim()
    ? {
        reviewer: artReviewer.value.trim(),
        review_type: '课程内容审核',
        reviewed_at: today,
        note: '课程内容来源核验',
      }
    : undefined
  return { sources, review_record }
}

async function saveDraft() {
  if (!artTitle.value.trim() || !artBody.value.trim()) {
    errorMessage.value = '请填写标题与正文'
    return
  }
  savingArticle.value = true
  errorMessage.value = ''
  statusMessage.value = ''
  const { sources, review_record } = buildSourcesAndReview()

  try {
    if (editingArticleId.value) {
      await api.patch(`/editor/articles/${editingArticleId.value}`, {
        title: artTitle.value.trim(),
        category: artCategory.value.trim(),
        summary: artSummary.value.trim(),
        body: artBody.value.trim(),
        author_byline: artByline.value.trim(),
        scope_note: artScopeNote.value.trim(),
        ...(sources ? { sources } : {}),
        ...(review_record ? { review_record } : {}),
      })
      statusMessage.value = '草稿修订已保存'
    } else {
      const created = await api.post<{ id: string }>('/editor/articles', {
        title: artTitle.value.trim(),
        category: artCategory.value.trim(),
        summary: artSummary.value.trim() || artTitle.value.trim(),
        body: artBody.value.trim(),
        author_byline: artByline.value.trim(),
        scope_note: artScopeNote.value.trim(),
        ...(sources ? { sources } : {}),
        ...(review_record ? { review_record } : {}),
      })
      editingArticleId.value = created.id
      statusMessage.value = '新草稿已创建'
    }
    await loadEditorArticles()
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '保存失败'
  } finally {
    savingArticle.value = false
  }
}

async function publishArticle(id: string) {
  errorMessage.value = ''
  statusMessage.value = ''
  const { sources, review_record } = buildSourcesAndReview()
  try {
    await api.post(`/editor/articles/${id}/publish`, {
      ...(sources ? { sources } : {}),
      ...(review_record ? { review_record } : {}),
    })
    statusMessage.value = '科普文章已发布'
    await loadEditorArticles()
  } catch (err) {
    errorMessage.value =
      err instanceof ApiClientError ? err.message : '发布校验未通过，请确认来源链接与审核记录'
  }
}

async function unpublishArticle(id: string) {
  errorMessage.value = ''
  statusMessage.value = ''
  try {
    await api.post(`/editor/articles/${id}/unpublish`)
    statusMessage.value = '文章已下架'
    await loadEditorArticles()
  } catch (err) {
    errorMessage.value = err instanceof ApiClientError ? err.message : '下架失败'
  }
}

watch(reportStatusFilter, () => {
  loadModeration()
})

watch(editorStatusFilter, () => {
  loadEditorArticles()
})

watch(activeSection, (sec) => {
  if (sec === 'moderation') loadModeration()
  if (sec === 'editor') loadEditorArticles()
})

onMounted(() => {
  if (activeSection.value === 'moderation') loadModeration()
  else loadEditorArticles()
})
</script>

<template>
  <div class="stack">
    <PageHeader
      title="内容与社区运营"
      subtitle="守护友善安全的同伴社区环境，严格核验健康百科引用来源。"
    >
      <template #actions>
        <div class="row-wrap" role="tablist" aria-label="运营工作台切换">
          <button
            v-if="auth.isModerator"
            type="button"
            role="tab"
            :aria-selected="activeSection === 'moderation'"
            class="pill"
            :class="{ 'pill-active': activeSection === 'moderation' }"
            @click="activeSection = 'moderation'"
          >
            <ShieldCheck :size="18" aria-hidden="true" />
            <span>社区举报审核</span>
          </button>
          <button
            v-if="auth.isEditor"
            type="button"
            role="tab"
            :aria-selected="activeSection === 'editor'"
            class="pill"
            :class="{ 'pill-active': activeSection === 'editor' }"
            @click="activeSection = 'editor'"
          >
            <BookOpenCheck :size="18" aria-hidden="true" />
            <span>百科内容编审</span>
          </button>
        </div>
      </template>
    </PageHeader>

    <HlAlert v-if="errorMessage" variant="error" role="alert">
      {{ errorMessage }}
    </HlAlert>
    <HlAlert v-if="statusMessage" variant="success" role="status">
      {{ statusMessage }}
    </HlAlert>

    <!-- Moderator Workbench -->
    <template v-if="activeSection === 'moderation' && auth.isModerator">
      <section class="hl-card stack">
        <div class="row-between">
          <h2 class="section-title">社区举报队列</h2>
          <div class="row-wrap" role="group" aria-label="举报处理状态筛选">
            <button
              v-for="st in ([
                { val: 'pending', label: '待处理' },
                { val: 'actioned', label: '已处理' },
                { val: 'dismissed', label: '已驳回' },
              ] as const)"
              :key="st.val"
              type="button"
              class="pill"
              :class="{ 'pill-active': reportStatusFilter === st.val }"
              :aria-pressed="reportStatusFilter === st.val"
              @click="reportStatusFilter = st.val"
            >
              {{ st.label }}
            </button>
          </div>
        </div>

        <EmptyState
          v-if="reports.length === 0"
          title="当前队列为空"
          description="没有符合当前筛选状态的社区举报记录。"
        />

        <ul v-else class="hl-ops-list">
          <li v-for="rep in reports" :key="rep.id" class="hl-ops-item stack-sm">
            <div class="row-between text-sm hl-muted">
              <div class="row-wrap">
                <HlBadge variant="brand">{{ rep.target_type === 'post' ? '帖子' : '评论' }}</HlBadge>
                <HlBadge variant="accent">{{ rep.reason }}</HlBadge>
                <span class="tabular">ID: {{ rep.target_id }}</span>
              </div>
              <span class="tabular">{{ formatDateTimeShort(rep.created_at) }}</span>
            </div>

            <div
              v-if="rep.target_title || rep.target_preview || rep.target_body"
              class="user-content hl-ops-preview"
            >
              {{ rep.target_title || rep.target_preview || rep.target_body }}
            </div>
            <div v-if="rep.detail" class="text-sm hl-muted user-content">
              举报补充说明：{{ rep.detail }}
            </div>

            <div v-if="rep.status === 'pending'" class="row-between" style="padding-top: 4px">
              <input
                v-model="resolveReasonMap[rep.id]"
                type="text"
                class="input"
                style="max-width: 360px; flex: 1 1 220px"
                placeholder="填写处理或复核说明（可选）"
                aria-label="处理说明"
              />
              <div class="row-wrap">
                <button
                  type="button"
                  class="btn btn-secondary btn-sm"
                  @click="resolveReport(rep, 'dismissed')"
                >
                  驳回举报
                </button>
                <button
                  type="button"
                  class="btn btn-danger btn-sm"
                  @click="resolveReport(rep, 'actioned')"
                >
                  隐藏内容
                </button>
              </div>
            </div>
            <div v-else-if="rep.status === 'actioned'" class="row-between">
              <span class="text-sm hl-muted">处理说明：{{ rep.resolution_note || '-' }}</span>
              <button
                type="button"
                class="btn btn-soft btn-sm"
                @click="restoreContent(rep.target_type, rep.target_id, '审核复核恢复')"
              >
                <RotateCcw :size="17" aria-hidden="true" />
                <span>恢复可见</span>
              </button>
            </div>
          </li>
        </ul>
      </section>

      <div class="grid-2">
        <section class="hl-card stack-sm">
          <h2 class="section-title">按 ID 恢复内容可见</h2>
          <div class="row-wrap">
            <select
              v-model="restoreTargetType"
              class="select"
              style="width: auto; flex: 0 0 auto"
              aria-label="内容类型"
            >
              <option value="post">帖子 (post)</option>
              <option value="comment">评论 (comment)</option>
            </select>
            <input
              v-model="restoreTargetId"
              type="text"
              class="input tabular"
              style="flex: 1 1 180px"
              placeholder="输入目标 ID"
              aria-label="目标 ID"
            />
          </div>
          <input
            v-model="restoreReason"
            type="text"
            class="input"
            placeholder="填写恢复原因"
            aria-label="恢复原因"
          />
          <div>
            <button
              type="button"
              class="btn btn-secondary btn-sm"
              @click="restoreContent(restoreTargetType, restoreTargetId)"
            >
              执行恢复
            </button>
          </div>
        </section>

        <section class="hl-card stack-sm">
          <h2 class="section-title">近期审核审计记录</h2>
          <div v-if="actions.length === 0" class="hl-muted text-sm">暂无审计记录</div>
          <ul v-else class="hl-ops-list">
            <li
              v-for="act in actions.slice(0, 6)"
              :key="act.id"
              class="hl-audit-row row-between text-sm"
            >
              <span>{{ act.action }} · {{ act.target_type }} · {{ act.reason }}</span>
              <span class="hl-muted tabular">{{ formatDateTimeShort(act.created_at) }}</span>
            </li>
          </ul>
        </section>
      </div>
    </template>

    <!-- Encyclopedia Editor Workbench -->
    <template v-if="activeSection === 'editor' && auth.isEditor">
      <div class="grid-2">
        <section class="hl-card stack">
          <div class="row-between">
            <h2 class="section-title">
              {{ editingArticleId ? '编辑百科条目' : '新建百科草稿' }}
            </h2>
            <button
              v-if="editingArticleId"
              type="button"
              class="btn btn-secondary btn-sm"
              @click="resetArticleForm"
            >
              新建空白草稿
            </button>
          </div>

          <form class="stack-sm" @submit.prevent="saveDraft">
            <div class="field">
              <label for="ed-title" class="field-label">文章标题</label>
              <input id="ed-title" v-model="artTitle" type="text" class="input" required />
            </div>

            <div class="grid-2">
              <div class="field">
                <label for="ed-cat" class="field-label">所属分类</label>
                <input id="ed-cat" v-model="artCategory" type="text" class="input" required />
              </div>
              <div class="field">
                <label for="ed-reviewer" class="field-label">课程内容审核人</label>
                <input id="ed-reviewer" v-model="artReviewer" type="text" class="input" />
              </div>
            </div>

            <div class="field">
              <label for="ed-summary" class="field-label">核心摘要</label>
              <input id="ed-summary" v-model="artSummary" type="text" class="input" />
            </div>

            <div class="field">
              <label for="ed-body" class="field-label">科普正文</label>
              <textarea id="ed-body" v-model="artBody" class="textarea" rows="6" required></textarea>
            </div>

            <div class="field">
              <label for="ed-src-title" class="field-label">权威参考来源标题</label>
              <input
                id="ed-src-title"
                v-model="artSourceTitle"
                type="text"
                class="input"
                placeholder="例如：WHO - Physical Activity Fact Sheet"
              />
            </div>

            <div class="field">
              <label for="ed-src-url" class="field-label">参考来源 HTTPS 链接</label>
              <input
                id="ed-src-url"
                v-model="artSourceUrl"
                type="url"
                class="input"
                placeholder="https://www.who.int/..."
              />
            </div>

            <div class="row-wrap" style="padding-top: 4px">
              <button type="submit" class="btn btn-primary btn-sm" :disabled="savingArticle">
                {{ savingArticle ? '正在保存...' : '保存草稿' }}
              </button>
              <button
                v-if="editingArticleId"
                type="button"
                class="btn btn-soft btn-sm"
                @click="publishArticle(editingArticleId)"
              >
                核验并发布
              </button>
            </div>
          </form>
        </section>

        <section class="hl-card stack">
          <div class="row-between">
            <h2 class="section-title">百科条目列表</h2>
            <select
              v-model="editorStatusFilter"
              class="select"
              style="width: auto"
              aria-label="状态筛选"
            >
              <option value="">全部状态</option>
              <option value="published">已发布</option>
              <option value="draft">草稿</option>
              <option value="unpublished">已下架</option>
            </select>
          </div>

          <EmptyState
            v-if="editorArticles.length === 0"
            title="暂无百科条目"
            description="可在左侧创建新的健康生活科普草稿。"
          />
          <ul v-else class="hl-ops-list">
            <li v-for="art in editorArticles" :key="art.id" class="hl-ops-item stack-sm">
              <div class="row-between">
                <strong class="card-title">{{ art.title }}</strong>
                <HlBadge :variant="art.status === 'published' ? 'brand' : 'neutral'">
                  {{ art.status }} · v{{ art.revision ?? 1 }}
                </HlBadge>
              </div>
              <div class="row-wrap">
                <button
                  type="button"
                  class="btn btn-secondary btn-sm"
                  @click="selectArticleForEdit(art)"
                >
                  编辑
                </button>
                <button
                  v-if="art.status !== 'published'"
                  type="button"
                  class="btn btn-soft btn-sm"
                  @click="publishArticle(art.id)"
                >
                  发布
                </button>
                <button
                  v-else
                  type="button"
                  class="btn btn-danger btn-sm"
                  @click="unpublishArticle(art.id)"
                >
                  下架
                </button>
              </div>
            </li>
          </ul>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.hl-ops-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.hl-ops-item {
  padding: 16px;
  border-radius: var(--hl-radius-sm);
  background: var(--hl-canvas);
  border: 1px solid var(--hl-border);
}

.hl-ops-preview {
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--hl-surface);
  border: 1px solid var(--hl-border);
  font-size: var(--hl-caption);
}

.hl-audit-row {
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--hl-canvas);
  border: 1px solid var(--hl-border);
}
</style>
