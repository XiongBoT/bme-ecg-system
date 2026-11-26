<script setup lang="ts">
import { RotateCcw, SlidersHorizontal } from 'lucide-vue-next'
import HlSwitch from '../ui/HlSwitch.vue'
import { usePreferencesStore } from '../../stores/preferences'

const prefs = usePreferencesStore()
</script>

<template>
  <section class="hl-card stack" aria-label="界面显示与适老化偏好">
    <div class="row-between">
      <div class="row-wrap">
        <SlidersHorizontal :size="22" style="color: var(--hl-brand)" aria-hidden="true" />
        <h2 class="section-title">显示与阅读设置</h2>
      </div>
      <button
        type="button"
        data-testid="pref-reset-defaults"
        class="btn btn-secondary btn-sm"
        @click="prefs.resetDefaults()"
      >
        <RotateCcw :size="18" aria-hidden="true" />
        <span>恢复默认显示</span>
      </button>
    </div>

    <p class="hl-muted text-sm" style="margin: 0">
      以下显示偏好仅保存在您当前的浏览器中，不会上传或保存任何个人健康数据。
    </p>

    <div class="stack-sm">
      <HlSwitch
        :model-value="prefs.fontSize === 'large'"
        label="大字阅读模式"
        description="放大全站文字与按钮尺寸，阅读更轻松"
        test-id="pref-large-font"
        @update:model-value="(v) => prefs.setFontSize(v ? 'large' : 'default')"
      />

      <HlSwitch
        :model-value="prefs.contrast === 'high'"
        label="高对比度模式"
        description="加深文字与输入框边框对比度，画面更清晰"
        test-id="pref-high-contrast"
        @update:model-value="(v) => prefs.setContrast(v ? 'high' : 'default')"
      />

      <HlSwitch
        :model-value="prefs.reducedMotion"
        label="减少界面动态效果"
        description="关闭过渡动画，减少视觉干扰"
        test-id="pref-reduced-motion"
        @update:model-value="(v) => prefs.setReducedMotion(v)"
      />
    </div>
  </section>
</template>
