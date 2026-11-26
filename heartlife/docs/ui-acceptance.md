# HeartLife 适老化 UI/UX 改版验收报告 (`docs/ui-acceptance.md`)

## 1. 边界与铁律核验结论

- **原 ECG 仓库零改动（`UI-T02`）**：`c:\Users\NickHu\Desktop\bme\bme-ecg-system` 保持在原始提交 `91ad66e1ace19c213035ad92276ae5a56670a685`，`git status --short` 无任何工作区变更。
- **HeartLife 后端零改动（`UI-T32`）**：`git diff 29c9047bfbb37981ec8ad0ffa3b804db4eabda3f -- backend/` 为空，后端业务代码、数据库 Schema、迁移脚本、REST API 契约及鉴权逻辑未做任何修改；后端 `pytest -q`（`92 passed`）全量通过。
- **真实业务连接与医疗伦理**：所有页面均对接真实 `/api/v1/*` 接口，无静态假页面，无虚构“健康总分 / 心脏年龄 / 疾病风险”，缺失记录严格显示「尚未记录」而非 `0`。

---

## 2. 32 项验收矩阵状态（`UI-T01` ~ `UI-T32`）

| ID | 层级 | 验收内容摘要 | 状态 | 验证证据 |
|---|---|---|---|---|
| UI-T01 | R | 原 P0 业务流程与请求契约保持一致 | **PASS** | `e2e/heartlife.spec.ts` + `tests/heartlife-ui.spec.ts` + `pytest -q` |
| UI-T02 | R | 旧 ECG 仓库无任何新增或修改 | **PASS** | `git -C bme-ecg-system diff` 为空，HEAD 未变 |
| UI-T03 | E | 未登录访问私密路由跳转登录且无私密数据泄露 | **PASS** | `e2e/heartlife.spec.ts` & 路由守卫验证 |
| UI-T04 | E | 已登录切换主导航路由可用，当前项具备 `aria-current="page"` | **PASS** | `e2e/ui-redesign.spec.ts` (`UI-T04`) |
| UI-T05 | E | 375px、390px 浏览首页/社区等无横向溢出，底部导航不遮挡末行操作 | **PASS** | `e2e/ui-redesign.spec.ts` (`UI-T05`) + `docs/screenshots/after/mobile-*.png` |
| UI-T06 | E | 320px 窄屏与 200% 文本放大重排无溢出、表单提交按钮可达 | **PASS** | `e2e/ui-redesign.spec.ts` (`UI-T06`) |
| UI-T07 | U/E | 大字阅读模式（22px 正文 / 56px 热区）纯 rem 真实放大且刷新持久化 | **PASS** | `tests/redesign-system.spec.ts` + `e2e/ui-redesign.spec.ts` + `desktop-*-large-font.png` |
| UI-T08 | U/E | 高对比度模式加深文字与控件边框对比度、刷新持久化并支持一键恢复默认 | **PASS** | `tests/redesign-system.spec.ts` + `e2e/ui-redesign.spec.ts` + `desktop-*-high-contrast.png` |
| UI-T09 | E | 纯键盘打开「发布动态」Dialog、`Esc` 关闭后焦点准确回到触发按钮 | **PASS** | `e2e/ui-redesign.spec.ts` (`UI-T09`) |
| UI-T10 | U/E | 社区返回正常列表时真实展示帖子、48px 首字头像、分类与互动动作 | **PASS** | `tests/community-redesign.spec.ts` + `e2e/heartlife.spec.ts` |
| UI-T11 | U | 社区搜索无结果展示明确提示与「清除筛选」按钮 | **PASS** | `tests/community-redesign.spec.ts` (`UI-T11`) |
| UI-T12 | U | 社区真实空列表显示温暖空状态插画与发布引导，非报错或假数据 | **PASS** | `tests/community-redesign.spec.ts` (`UI-T12`) |
| UI-T13 | U | 读请求慢速/超时/失败显示结构化 Skeleton、提示与可执行重试 | **PASS** | `tests/community-redesign.spec.ts` (`UI-T13`) |
| UI-T14 | U | 连续快速切换分类/搜索词丢弃过期响应（`requestSeq` + `AbortController`） | **PASS** | `tests/community-redesign.spec.ts` (`UI-T14`) + `tests/ui04-knowledge-report.spec.ts` |
| UI-T15 | U/E | 发帖或评论提交失败保留用户输入草稿并展示可理解错误 | **PASS** | `tests/community-redesign.spec.ts` + `e2e/ui-redesign.spec.ts` (`UI-T15`) |
| UI-T16 | U | 服务端返回 `pending` 待审核状态时准确提示待审核，不假称已公开 | **PASS** | `tests/community-redesign.spec.ts` (`UI-T16`) |
| UI-T17 | E | 点赞、收藏、评论与服务端持久化一致，防重复提交 | **PASS** | `e2e/heartlife.spec.ts` (`T-0216`) |
| UI-T18 | U/E | 无日记/无计划时首页显示「尚未记录」与「无计划」，零虚构数值 | **PASS** | `tests/ui03-home-journal-plans.spec.ts` + `tests/heartlife-ui.spec.ts` |
| UI-T19 | U/E | 健康日记保留空白 `null` 与显式 `0` 区分，删除操作具备二次确认弹窗 | **PASS** | `tests/ui03-home-journal-plans.spec.ts` + `e2e/heartlife.spec.ts` |
| UI-T20 | U/E | 计划打卡仅成功后确认完成，接口失败自动回滚状态与连续天数 | **PASS** | `tests/ui03-home-journal-plans.spec.ts` (`UI-T20`) |
| UI-T21 | U/E | 百科详情完整保留课程审核记录、安全 HTTPS 来源外链、医疗边界说明与收藏 | **PASS** | `tests/ui04-knowledge-report.spec.ts` + `e2e/heartlife.spec.ts` (`T-0504`) |
| UI-T22 | U/E | 健康周报区分 `null`（尚未记录）与 `0 分钟`，ECharts SVG 趋势图附带完整数值表 | **PASS** | `tests/ui04-knowledge-report.spec.ts` + `ChartWithDataTable.vue` |
| UI-T23 | U | 百科封面图片 URL 加载失败时自动回退至本地暖调 SVG 封面，不破版 | **PASS** | `tests/ui04-knowledge-report.spec.ts` (`UI-T23`) |
| UI-T24 | U/E | 核心字体栈、Lucide 图标与 SVG 插画 100% 本地打包，零运行时外部 CDN 依赖 | **PASS** | `package.json` + `src/assets/heartlife/illustrations/` + 构建产物检查 |
| UI-T25 | E | 系统 `prefers-reduced-motion: reduce` 或用户开启减弱动效时停用过渡动画 | **PASS** | `e2e/ui-redesign.spec.ts` (`UI-T25`) |
| UI-T26 | E | 账号登出并切换至另一账号后无私密数据残留，`localStorage` 仅存纯显示偏好 | **PASS** | `e2e/ui-redesign.spec.ts` (`UI-T26`) |
| UI-T27 | E | `@axe-core/playwright` 扫描核心页面、弹窗及大字高对比模式，`serious/critical` 为 `0` | **PASS** | `e2e/ui-redesign.spec.ts` (`UI-T27`) |
| UI-T28 | M | 浏览器实机巡检与前后同视口截图对比（修复了 1280px 顶栏折行与首页窄列折行） | **PASS** | `docs/screenshots/before/` vs `docs/screenshots/after/` |
| UI-T29 | M | 5 名左右真实老年/成年志愿者线下可用性测试 | **DEFERRED** | 当前为本地软件开发交付环境，尚未组织线下真人志愿者实测，按规范如实标记未开展 |
| UI-T30 | M | 素材来源与演示数据合规审查（原创本地 SVG + Lucide ISC + `is_demo` 合成账号） | **PASS** | `docs/ui-assets.md`，零真人患者假头像、零未授权外链图片 |
| UI-T31 | U/E | 未配置外部 ECG URL 时隐藏入口，配置安全 HTTPS URL 时展示确认弹窗 | **PASS** | `tests/heartlife-ui.spec.ts` (`T-1001`, `T-1002`) + `e2e/heartlife.spec.ts` |
| UI-T32 | R | 后端零变更 diff 校验通过 | **PASS** | `git diff 29c9047bfbb37981ec8ad0ffa3b804db4eabda3f -- backend/` 为空 |

---

## 3. 视觉验收自检说明与已知限制

- **视觉验收维度说明（PRD §11）**：已完成信息层次统一、暖调米白+森林绿+暖陶橙适老令牌体系、48px 触控热区、大字/高对比/减弱动效三项持久化偏好、改版前后同视口截图留存及业务回归。依据 PRD 第 11 节约定，AI 不自行宣称最终主观总分，供项目负责人结合 `docs/screenshots/before/` 与 `docs/screenshots/after/` 及 `http://127.0.0.1:8010` 实机演示复核评分。
- **已知限制**：
  1. `UI-T29` 真人线下志愿者体验测试需由团队成员在课程汇报前邀请受试者补充记录。
  2. `@axe-core/playwright` 自动扫描通过代表消除了可自动检测的 WCAG 2.2 A/AA 严重违规，不等同于正式第三方无障碍认证；百科详情页「朗读全文」依赖宿主操作系统与浏览器内置的 `window.speechSynthesis` 中文语音引擎。
