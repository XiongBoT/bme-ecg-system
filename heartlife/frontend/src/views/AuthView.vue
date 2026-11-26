<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Eye, EyeOff, HeartPulse, Sparkles } from 'lucide-vue-next'
import { useAuthStore } from '../stores/auth'
import { ApiClientError } from '../api/client'
import welcomeCompanionSvg from '../assets/heartlife/illustrations/welcome-companion.svg'
import HlAlert from '../components/ui/HlAlert.vue'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const mode = ref<'login' | 'register'>('login')
const account = ref('')
const password = ref('')
const nickname = ref('')
const timezone = ref('Asia/Shanghai')
const showPassword = ref(false)
const loading = ref(false)
const errorMessage = ref('')

const DEMO_ACCOUNTS = [
  { label: '林阿姨 demo_alice', account: 'demo_alice' },
  { label: '陈伯伯 demo_bob', account: 'demo_bob' },
  { label: '社区治理员 demo_mod', account: 'demo_mod' },
]

function switchMode(next: 'login' | 'register') {
  mode.value = next
  errorMessage.value = ''
}

function togglePasswordVisibility() {
  showPassword.value = !showPassword.value
}

function fillDemoAccount(demoAcc: string) {
  mode.value = 'login'
  errorMessage.value = ''
  account.value = demoAcc
  password.value = 'DemoPass123!'
}

function getSafeRedirect(): string {
  const raw = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
  if (raw.startsWith('/') && !raw.startsWith('//')) {
    return raw
  }
  return '/'
}

async function handleSubmit() {
  errorMessage.value = ''
  const cleanAccount = account.value.trim()
  if (!cleanAccount || !password.value) {
    errorMessage.value = '请填写账号与密码'
    return
  }
  if (mode.value === 'register' && !nickname.value.trim()) {
    errorMessage.value = '请填写昵称'
    return
  }

  loading.value = true
  try {
    if (mode.value === 'register') {
      await auth.register({
        account: cleanAccount,
        password: password.value,
        nickname: nickname.value.trim(),
        timezone: timezone.value || 'Asia/Shanghai',
      })
    }
    await auth.login({
      account: cleanAccount,
      password: password.value,
    })
    await router.push(getSafeRedirect())
  } catch (err) {
    if (err instanceof ApiClientError) {
      errorMessage.value = err.message
    } else {
      errorMessage.value = '网络异常，请稍后重试'
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="hl-auth-shell">
    <section class="hl-card stack" aria-labelledby="auth-welcome-heading">
      <!-- Welcoming Reassuring Brand Header -->
      <header class="hl-auth-header">
        <div class="hl-auth-badge" aria-hidden="true">
          <HeartPulse :size="28" />
        </div>
        <h1 id="auth-welcome-heading" class="hl-auth-heading">欢迎来到心伴 HeartLife</h1>
        <p class="hl-auth-subtitle">温暖记录每一天的睡眠、散步与好心情</p>
        <img
          :src="welcomeCompanionSvg"
          alt=""
          aria-hidden="true"
          width="240"
          height="120"
          class="hl-auth-illustration"
        />
      </header>

      <!-- Flat Segmented Login / Register Tabs (>=48px, 10px radius) -->
      <div class="hl-auth-tablist" role="tablist" aria-label="认证方式切换">
        <button
          type="button"
          role="tab"
          :aria-selected="mode === 'login'"
          class="hl-auth-tab"
          :class="{ 'hl-auth-tab-active': mode === 'login' }"
          @click="switchMode('login')"
        >
          登录
        </button>
        <button
          type="button"
          role="tab"
          :aria-selected="mode === 'register'"
          class="hl-auth-tab"
          :class="{ 'hl-auth-tab-active': mode === 'register' }"
          @click="switchMode('register')"
        >
          注册
        </button>
      </div>

      <form class="stack" @submit.prevent="handleSubmit">
        <div class="field">
          <label for="auth-account" class="field-label">账号</label>
          <input
            id="auth-account"
            v-model="account"
            type="text"
            class="input"
            autocomplete="username"
            placeholder="请输入您的登录账号"
            maxlength="32"
            required
          />
        </div>

        <div v-if="mode === 'register'" class="field">
          <label for="auth-nickname" class="field-label">您的称呼（昵称）</label>
          <input
            id="auth-nickname"
            v-model="nickname"
            type="text"
            class="input"
            autocomplete="nickname"
            placeholder="例如：林阿姨、老陈"
            maxlength="32"
            required
          />
        </div>

        <div class="field">
          <label for="auth-password" class="field-label">密码</label>
          <div class="hl-password-row">
            <input
              id="auth-password"
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              class="input hl-password-input"
              :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
              placeholder="请输入至少 8 位密码"
              minlength="8"
              maxlength="128"
              required
            />
            <button
              type="button"
              data-testid="auth-password-toggle"
              class="btn btn-secondary hl-password-toggle"
              :aria-pressed="showPassword ? 'true' : 'false'"
              :aria-label="showPassword ? '隐藏密码' : '显示密码'"
              @click="togglePasswordVisibility"
            >
              <EyeOff v-if="showPassword" :size="20" aria-hidden="true" />
              <Eye v-else :size="20" aria-hidden="true" />
              <span>{{ showPassword ? '隐藏' : '显示' }}</span>
            </button>
          </div>
        </div>

        <HlAlert v-if="errorMessage" variant="error" role="alert">
          {{ errorMessage }}
        </HlAlert>

        <button type="submit" class="btn btn-primary" style="width: 100%" :disabled="loading">
          {{ loading ? '正在处理，请稍候...' : mode === 'login' ? '登录' : '注册并进入' }}
        </button>
      </form>

      <!-- Demo Quick-Fill Helper Box (Strictly conditional on publicConfig.demo_mode) -->
      <section
        v-if="auth.publicConfig.demo_mode"
        class="hl-card-soft stack-sm"
        aria-label="演示体验账号快捷填入"
      >
        <div class="row-wrap">
          <Sparkles :size="18" style="color: var(--hl-brand)" aria-hidden="true" />
          <strong class="text-sm">演示模式快捷体验（合成演示数据）</strong>
        </div>
        <div class="hl-demo-grid">
          <button
            v-for="item in DEMO_ACCOUNTS"
            :key="item.account"
            type="button"
            class="pill hl-demo-chip"
            @click="fillDemoAccount(item.account)"
          >
            {{ item.label }}
          </button>
        </div>
      </section>

      <nav class="hl-auth-links" aria-label="公开内容浏览">
        <RouterLink to="/knowledge" class="hl-auth-link">浏览健康百科</RouterLink>
        <span class="hl-muted" aria-hidden="true">·</span>
        <RouterLink to="/community" class="hl-auth-link">浏览社区交流</RouterLink>
      </nav>
    </section>

    <p class="hl-auth-disclaimer">健康生活记录与科普参考 · 不作为医疗诊断建议</p>
  </div>
</template>

<style scoped>
.hl-auth-shell {
  max-width: 460px;
  width: 100%;
  margin: 36px auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.hl-auth-header {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 8px;
}

.hl-auth-badge {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  background: var(--hl-surface-soft);
  border: 1px solid var(--hl-border);
  color: var(--hl-brand);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.hl-auth-heading {
  margin: 4px 0 0;
  font-size: 1.65rem;
  line-height: 1.35;
  font-weight: 700;
  color: var(--hl-text);
}

.hl-auth-subtitle {
  margin: 0;
  font-size: var(--hl-caption);
  color: var(--hl-text-muted);
}

.hl-auth-illustration {
  margin-top: 6px;
  max-width: 220px;
  width: 100%;
  height: auto;
  border-radius: 14px;
}

.hl-auth-tablist {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 6px;
  background: var(--hl-canvas);
  border: 1px solid var(--hl-border);
  border-radius: var(--hl-radius-btn);
}

.hl-auth-tab {
  min-height: var(--hl-target);
  padding: 8px 14px;
  border-radius: var(--hl-radius-sm);
  border: 1.5px solid transparent;
  background: transparent;
  color: var(--hl-text-muted);
  font-family: inherit;
  font-size: var(--hl-body);
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.hl-auth-tab:hover {
  color: var(--hl-brand);
  background: var(--hl-surface-soft);
}

.hl-auth-tab-active {
  background: var(--hl-surface);
  border-color: var(--hl-brand);
  color: var(--hl-brand);
  font-weight: 700;
  box-shadow: 0 2px 6px rgb(36 55 47 / 0.06);
}

.hl-password-row {
  display: flex;
  align-items: stretch;
  gap: 8px;
}

.hl-password-input {
  flex: 1 1 auto;
}

.hl-password-toggle {
  flex-shrink: 0;
  padding: 8px 14px;
  min-width: 92px;
}

.hl-demo-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.hl-demo-chip {
  flex: 1 1 auto;
  justify-content: center;
}

.hl-auth-links {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 4px;
}

.hl-auth-link {
  display: inline-flex;
  align-items: center;
  min-height: 44px;
  font-size: var(--hl-caption);
  font-weight: 600;
}

.hl-auth-disclaimer {
  margin: 0;
  text-align: center;
  font-size: var(--hl-caption);
  color: var(--hl-text-muted);
}

@media (max-width: 480px) {
  .hl-auth-shell {
    margin: 20px auto;
  }

  .hl-password-row {
    flex-wrap: wrap;
  }

  .hl-password-toggle {
    width: 100%;
  }
}
</style>
