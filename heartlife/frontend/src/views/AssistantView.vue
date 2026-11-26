<script setup lang="ts">
import { computed, ref } from 'vue'
import { BookOpen, Bot, RefreshCw, Send, ShieldCheck, Sparkles } from 'lucide-vue-next'
import { api, ApiClientError } from '../api/client'
import { useAuthStore } from '../stores/auth'
import PageHeader from '../components/common/PageHeader.vue'
import EmptyState from '../components/common/EmptyState.vue'
import HlAlert from '../components/ui/HlAlert.vue'
import HlBadge from '../components/ui/HlBadge.vue'
import type { AssistantChatResponse } from '../types/api'

const auth = useAuthStore()

const query = ref('')
// Strictly unchecked by default per T-0903 & PRD §5.7!
const allowWeeklyReport = ref(false)
const allowPlans = ref(false)

const loading = ref(false)
const forceDisabled = ref(false)
const errorMessage = ref('')
const result = ref<AssistantChatResponse | null>(null)

const isEnabled = computed(() => auth.publicConfig.assistant_enabled && !forceDisabled.value)

const SAFE_EXAMPLE_PROMPTS = [
  '规律睡眠为什么重要？',
  '晚饭后散步有哪些温和建议？',
  '怎样养成每天喝水的小习惯？',
  '居家记录日常作息有什么帮助？',
]

const MODE_LABELS: Record<string, string> = {
  grounded: '已核验科普回答',
  verified_fallback: '确定性核验摘要',
  insufficient_evidence: '暂无匹配百科条目',
  provider_timeout: '检索回退摘要',
  emergency_guidance: '紧急就医提示',
  medical_refusal: '医疗安全边界提示',
  security_refusal: '安全规则拦截',
}

function formatModeLabel(mode: string): string {
  return MODE_LABELS[mode] || mode
}

function getModeVariant(mode: string): 'neutral' | 'brand' | 'accent' | 'danger' {
  if (mode === 'emergency_guidance') return 'danger'
  if (mode === 'medical_refusal' || mode === 'security_refusal') return 'accent'
  return 'brand'
}

function applyExamplePrompt(promptText: string) {
  query.value = promptText
  errorMessage.value = ''
}

async function handleAsk() {
  const cleanQuery = query.value.trim()
  if (!cleanQuery) {
    errorMessage.value = '请先输入或点选您想了解的生活习惯问题'
    return
  }
  loading.value = true
  errorMessage.value = ''

  try {
    const res = await api.post<AssistantChatResponse>('/assistant/chat', {
      query: cleanQuery,
      allow_weekly_report: allowWeeklyReport.value,
      allow_plans: allowPlans.value,
    })
    result.value = res
  } catch (err) {
    if (err instanceof ApiClientError && (err.status === 503 || err.code === 'ASSISTANT_DISABLED')) {
      forceDisabled.value = true
      result.value = null
    } else {
      // Preserve query so the user can retry without retyping
      errorMessage.value = err instanceof ApiClientError ? err.message : '提问暂时未成功，您的输入已保留，请重试'
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="narrow-container hl-assistant-wrap stack">
    <PageHeader
      title="健康生活助手"
      subtitle="基于已审核的健康百科内容，为您解答日常作息、散步与习惯养成问题。"
    >
      <template #actions>
        <RouterLink to="/knowledge" class="btn btn-secondary btn-sm">
          <BookOpen :size="18" aria-hidden="true" />
          <span>健康百科</span>
        </RouterLink>
      </template>
    </PageHeader>

    <!-- Disabled / Unavailable Clean State (T-0901) -->
    <EmptyState
      v-if="!isEnabled"
      title="生活助手当前未启用"
      description="您仍然可以随时查阅经核验的健康百科文章，了解睡眠、散步与健康作息知识。"
    >
      <template #actions>
        <RouterLink to="/knowledge" class="btn btn-primary">前往健康百科</RouterLink>
      </template>
    </EmptyState>

    <template v-else>
      <!-- Explicit Capability & Medical Boundary Notice -->
      <HlAlert variant="info" class="alert-brand" role="note">
        <div class="stack-sm" style="gap: 4px">
          <strong>温和科普参考 · 医疗安全边界说明</strong>
          <span class="text-sm">
            本助手仅依据已审核的健康百科提供生活作息与习惯参考，<strong>不作为个体医疗诊断</strong>、不解读心电图波形、不开具处方或用药建议。若出现胸痛、呼吸困难、晕厥等紧急不适，请立即前往医院急诊或拨打急救电话。
          </span>
        </div>
      </HlAlert>

      <!-- Safe Example Prompts -->
      <section class="hl-card stack-sm" aria-label="常见问题示例">
        <div class="row-wrap">
          <Sparkles :size="20" style="color: var(--hl-brand)" aria-hidden="true" />
          <h2 class="card-title">您可以点选一个常见生活问题试试：</h2>
        </div>
        <div class="row-wrap">
          <button
            v-for="promptText in SAFE_EXAMPLE_PROMPTS"
            :key="promptText"
            type="button"
            data-testid="assistant-example-prompt"
            class="pill"
            @click="applyExamplePrompt(promptText)"
          >
            {{ promptText }}
          </button>
        </div>
      </section>

      <!-- Question Form & Single-Turn Explicit Consent Checkboxes -->
      <form class="hl-card stack" @submit.prevent="handleAsk">
        <div class="field">
          <label for="assistant-query" class="field-label">您的生活与习惯咨询</label>
          <textarea
            id="assistant-query"
            v-model="query"
            class="textarea"
            rows="3"
            maxlength="500"
            placeholder="例如：晚饭后散步有哪些温和建议？"
            required
          ></textarea>
        </div>

        <div class="hl-card-soft card-subtle stack-sm">
          <div class="row-wrap">
            <ShieldCheck :size="18" style="color: var(--hl-brand)" aria-hidden="true" />
            <strong class="text-sm">单次数据读取授权（默认不读取，仅对本次提问生效）</strong>
          </div>
          <label class="checkbox-label">
            <input v-model="allowWeeklyReport" type="checkbox" />
            <span>允许本次读取我的本周统计摘要（不含日记备注原文）</span>
          </label>
          <label class="checkbox-label">
            <input v-model="allowPlans" type="checkbox" />
            <span>允许本次读取我的习惯计划列表</span>
          </label>
        </div>

        <HlAlert v-if="errorMessage" variant="error" role="alert">
          <div class="row-between">
            <span>{{ errorMessage }}</span>
            <button
              type="button"
              class="btn btn-secondary btn-sm"
              :disabled="loading"
              @click="handleAsk"
            >
              <RefreshCw :size="17" aria-hidden="true" />
              <span>重试</span>
            </button>
          </div>
        </HlAlert>

        <div class="row-between">
          <span v-if="loading" role="status" class="text-sm hl-muted">
            正在从健康百科为您检索核验内容，请稍候...
          </span>
          <span v-else class="text-sm hl-muted">请勿在提问中输入身份证号、手机号等敏感隐私。</span>

          <button type="submit" class="btn btn-primary" :disabled="loading">
            <Send :size="18" aria-hidden="true" />
            <span>{{ loading ? '正在检索...' : '发送提问' }}</span>
          </button>
        </div>
      </form>

      <!-- Structured Grounded Answer & Clickable Citations -->
      <section v-if="result" class="hl-card stack" aria-label="健康生活助手回答">
        <div class="row-between">
          <div class="row-wrap">
            <Bot :size="22" style="color: var(--hl-brand)" aria-hidden="true" />
            <HlBadge :variant="getModeVariant(result.mode)">
              {{ formatModeLabel(result.mode) }}
            </HlBadge>
          </div>
          <RouterLink :to="result.fallback_url || '/knowledge'" class="btn btn-ghost btn-sm">
            查阅健康百科
          </RouterLink>
        </div>

        <div class="plain-body">{{ result.answer }}</div>

        <div v-if="result.citations && result.citations.length > 0" class="hl-card-soft stack-sm">
          <strong class="text-sm">参考健康百科条目（点击可阅读原文）：</strong>
          <div class="hl-citation-grid">
            <RouterLink
              v-for="cit in result.citations"
              :key="cit.id"
              :to="`/knowledge/${cit.id}`"
              class="hl-citation-card"
            >
              <BookOpen :size="18" style="color: var(--hl-brand); flex-shrink: 0" aria-hidden="true" />
              <span>{{ cit.title }}</span>
            </RouterLink>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.hl-assistant-wrap {
  max-width: 820px;
}

.hl-citation-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.hl-citation-card {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: var(--hl-target);
  padding: 10px 14px;
  border-radius: var(--hl-radius-sm);
  background: var(--hl-surface);
  border: 1px solid var(--hl-border);
  color: var(--hl-text);
  font-weight: 600;
  transition: border-color 0.15s ease, color 0.15s ease;
}

.hl-citation-card:hover {
  border-color: var(--hl-brand);
  color: var(--hl-brand);
}
</style>
