<script setup lang="ts">
import { computed, type Component } from 'vue'
import { useRoute } from 'vue-router'
import {
  Bell,
  BookOpen,
  CalendarCheck,
  HeartPulse,
  Home,
  MessageCircle,
  NotebookPen,
  ShieldCheck,
  Trophy,
  Type,
  UserRound,
  Users,
} from 'lucide-vue-next'
import { useAuthStore } from '../stores/auth'
import { usePreferencesStore } from '../stores/preferences'

const auth = useAuthStore()
const prefs = usePreferencesStore()
const route = useRoute()

interface NavItem {
  label: string
  to: string
  icon: Component
  matchPrefix?: string
}

const desktopNavItems = computed<NavItem[]>(() => {
  const base: NavItem[] = [
    { label: '首页', to: '/', icon: Home },
    { label: '社区', to: '/community', icon: Users, matchPrefix: '/community' },
    { label: '计划', to: '/plans', icon: CalendarCheck, matchPrefix: '/plans' },
    { label: '百科', to: '/knowledge', icon: BookOpen, matchPrefix: '/knowledge' },
    { label: '挑战', to: '/challenges', icon: Trophy, matchPrefix: '/challenges' },
  ]
  if (auth.publicConfig.assistant_enabled) {
    base.push({ label: '助手', to: '/assistant', icon: MessageCircle, matchPrefix: '/assistant' })
  }
  if (auth.isOps) {
    base.push({ label: '运营', to: '/ops', icon: ShieldCheck, matchPrefix: '/ops' })
  }
  return base
})

const mobileNavItems: NavItem[] = [
  { label: '首页', to: '/', icon: Home },
  { label: '社区', to: '/community', icon: Users, matchPrefix: '/community' },
  { label: '计划', to: '/plans', icon: CalendarCheck, matchPrefix: '/plans' },
  { label: '百科', to: '/knowledge', icon: BookOpen, matchPrefix: '/knowledge' },
  { label: '我的', to: '/me', icon: UserRound, matchPrefix: '/me' },
]

function isNavActive(item: NavItem): boolean {
  if (item.to === '/') {
    return route.path === '/'
  }
  return item.matchPrefix ? route.path.startsWith(item.matchPrefix) : route.path === item.to
}
</script>

<template>
  <div class="hl-shell">
    <header class="hl-topbar no-print">
      <div class="hl-topbar-inner">
        <!-- Brand Left -->
        <div class="hl-brand-cluster">
          <RouterLink to="/" class="hl-brand-link" aria-label="心伴 HeartLife 首页">
            <span class="hl-brand-mark" aria-hidden="true">
              <HeartPulse :size="24" />
            </span>
            <span class="hl-brand-text">心伴</span>
          </RouterLink>
          <span v-if="auth.publicConfig.demo_mode" class="badge" title="当前为合成演示环境">
            演示
          </span>
        </div>

        <!-- Flat Horizontal Navigation Center (Desktop >= 1024px) -->
        <nav class="hl-desktop-nav" aria-label="主导航">
          <RouterLink
            v-for="item in desktopNavItems"
            :key="item.to"
            :to="item.to"
            class="hl-nav-link"
            :class="{ 'hl-nav-link-active': isNavActive(item) }"
            :aria-current="isNavActive(item) ? 'page' : undefined"
          >
            <component :is="item.icon" :size="20" aria-hidden="true" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </nav>

        <!-- Right Elderly-Friendly Actions -->
        <div class="hl-right-actions">
          <button
            type="button"
            class="hl-font-btn"
            :class="{ 'hl-font-btn-active': prefs.fontSize === 'large' }"
            :aria-pressed="prefs.fontSize === 'large'"
            @click="prefs.toggleFontSize()"
          >
            <Type :size="19" aria-hidden="true" />
            <span>{{ prefs.fontSize === 'large' ? '标准字' : '大字' }}</span>
            <span class="sr-only">阅读模式</span>
          </button>

          <template v-if="auth.isAuthenticated && auth.user">
            <RouterLink to="/journal" class="btn btn-primary hl-record-cta">
              <NotebookPen :size="20" aria-hidden="true" />
              <span>记录今日</span>
            </RouterLink>

            <RouterLink
              to="/notifications"
              class="hl-icon-action"
              :class="{ 'hl-icon-action-active': route.path.startsWith('/notifications') }"
              :aria-current="route.path.startsWith('/notifications') ? 'page' : undefined"
            >
              <Bell :size="21" aria-hidden="true" />
              <span class="hl-action-text">消息</span>
              <span v-if="auth.unreadCount > 0" class="hl-unread-pill tabular">
                {{ auth.unreadCount > 99 ? '99+' : auth.unreadCount }}
              </span>
              <span v-if="auth.unreadCount > 0" class="sr-only">条未读</span>
            </RouterLink>

            <RouterLink
              to="/me"
              class="hl-user-entry"
              :class="{ 'hl-icon-action-active': route.path.startsWith('/me') }"
              :aria-current="route.path.startsWith('/me') ? 'page' : undefined"
            >
              <UserRound :size="20" aria-hidden="true" />
              <span class="hl-user-name">{{ auth.user.nickname }}</span>
            </RouterLink>
          </template>

          <template v-else>
            <RouterLink to="/login" class="btn btn-primary">登录 / 注册</RouterLink>
          </template>
        </div>
      </div>
    </header>

    <main class="main-container">
      <slot />
    </main>

    <footer class="hl-footer no-print">
      <p style="margin: 0">
        健康生活记录与科普参考 · 不作为医疗诊断建议
      </p>
    </footer>

    <!-- Mobile Fixed 5-Item Bottom Navigation (<= 1023px / <= 767px) -->
    <nav class="hl-mobile-nav no-print" aria-label="底部主导航">
      <RouterLink
        v-for="item in mobileNavItems"
        :key="item.to"
        :to="item.to"
        class="hl-mobile-nav-item"
        :class="{ 'hl-mobile-nav-item-active': isNavActive(item) }"
        :aria-current="isNavActive(item) ? 'page' : undefined"
      >
        <component :is="item.icon" :size="22" aria-hidden="true" />
        <span class="hl-mobile-nav-label">{{ item.label }}</span>
      </RouterLink>
    </nav>
  </div>
</template>

<style scoped>
.hl-topbar {
  position: sticky;
  top: 0;
  z-index: 120;
  min-height: 76px;
  background: var(--hl-surface);
  border-bottom: 1.5px solid var(--hl-border);
}

.hl-topbar-inner {
  max-width: var(--hl-max-width);
  min-height: 76px;
  margin: 0 auto;
  padding: 8px 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.hl-brand-cluster {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.hl-brand-link {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-height: var(--hl-target);
  color: var(--hl-text);
  font-weight: 750;
  font-size: 1.375rem;
}

.hl-brand-mark {
  width: 40px;
  height: 40px;
  border-radius: 11px;
  background: var(--hl-brand);
  color: var(--hl-on-brand);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.hl-brand-text {
  letter-spacing: 0.01em;
}

.hl-desktop-nav {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-wrap: wrap;
}

.hl-nav-link {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: var(--hl-target);
  padding: 8px 11px;
  border-radius: var(--hl-radius-sm);
  color: var(--hl-text-muted);
  font-size: var(--hl-caption);
  font-weight: 600;
  transition: background-color 0.15s ease, color 0.15s ease;
  white-space: nowrap;
}

.hl-nav-link:hover {
  background: var(--hl-surface-soft);
  color: var(--hl-brand);
}

.hl-nav-link-active {
  background: var(--hl-surface-soft);
  color: var(--hl-brand);
  font-weight: 700;
}

.hl-nav-link-active::after {
  content: "";
  position: absolute;
  left: 14px;
  right: 14px;
  bottom: 3px;
  height: 3px;
  border-radius: 2px;
  background: var(--hl-brand);
}

.hl-right-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.hl-font-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: var(--hl-target);
  padding: 8px 12px;
  border-radius: var(--hl-radius-sm);
  border: 1.5px solid var(--hl-border);
  background: var(--hl-surface);
  color: var(--hl-text);
  font-family: inherit;
  font-size: var(--hl-caption);
  font-weight: 600;
  cursor: pointer;
}

.hl-font-btn:hover {
  border-color: var(--hl-brand);
  background: var(--hl-surface-soft);
}

.hl-font-btn-active {
  background: var(--hl-surface-soft);
  border-color: var(--hl-brand);
  color: var(--hl-brand);
}

.hl-icon-action,
.hl-user-entry {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: var(--hl-target);
  padding: 8px 12px;
  border-radius: var(--hl-radius-sm);
  border: 1.5px solid var(--hl-border);
  background: var(--hl-surface);
  color: var(--hl-text);
  font-size: var(--hl-caption);
  font-weight: 600;
}

.hl-icon-action:hover,
.hl-user-entry:hover {
  border-color: var(--hl-brand);
  background: var(--hl-surface-soft);
  color: var(--hl-brand);
}

.hl-icon-action-active {
  background: var(--hl-surface-soft);
  border-color: var(--hl-brand);
  color: var(--hl-brand);
}

.hl-unread-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 22px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--hl-accent);
  color: #ffffff;
  font-size: 0.8125rem;
  font-weight: 700;
}

.hl-user-name {
  max-width: 112px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hl-footer {
  text-align: center;
  padding: 20px 16px 36px;
  border-top: 1px solid var(--hl-border);
  background: var(--hl-canvas);
  color: var(--hl-text-muted);
  font-size: var(--hl-caption);
}

.hl-mobile-nav {
  display: none;
}

@media (max-width: 1340px) {
  .hl-action-text {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }

  .hl-record-cta {
    padding: 8px 14px;
    font-size: var(--hl-caption);
  }
}

@media (max-width: 1160px) {
  .hl-user-name {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
}

@media (max-width: 960px) {
  .hl-topbar {
    min-height: 64px;
  }

  .hl-topbar-inner {
    min-height: 64px;
    padding: 6px 16px;
  }

  .hl-desktop-nav,
  .hl-user-entry,
  .hl-record-cta {
    display: none;
  }

  .hl-footer {
    padding-bottom: 100px;
  }

  .hl-mobile-nav {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 140;
    min-height: 66px;
    padding-top: 6px;
    padding-bottom: calc(6px + env(safe-area-inset-bottom, 0px));
    background: var(--hl-surface);
    border-top: 1.5px solid var(--hl-border);
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    align-items: center;
    box-shadow: 0 -4px 16px rgb(36 55 47 / 0.05);
  }

  .hl-mobile-nav-item {
    min-height: 52px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    color: var(--hl-text-muted);
    font-size: 0.875rem;
    font-weight: 600;
    border-radius: 10px;
    margin: 0 3px;
  }

  .hl-mobile-nav-item-active {
    color: var(--hl-brand);
    background: var(--hl-surface-soft);
    font-weight: 750;
  }
}

@media (max-width: 360px) {
  .hl-brand-text {
    font-size: 1.15rem;
  }

  .hl-font-btn span {
    display: none;
  }
}
</style>
