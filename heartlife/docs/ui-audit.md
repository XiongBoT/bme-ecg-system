# HeartLife 适老化 UI/UX 改版基线审计报告 (UI-00 Audit)

## 1. 版本与代码边界快照

- **审计时间**：2026-11-26T15:15+08:00
- **HeartLife 独立仓库路径**：`c:\Users\NickHu\Desktop\bme\heartlife`
- **改版前 Git HEAD**：`29c9047bfbb37981ec8ad0ffa3b804db4eabda3f`（工作区干净）
- **原 ECG 仓库路径**：`c:\Users\NickHu\Desktop\bme\bme-ecg-system`
- **原 ECG 仓库 HEAD**：`91ad66e1ace19c213035ad92276ae5a56670a685`（零源码改动，严禁触碰）
- **后端冻结门禁**：`heartlife/backend/app/` 与 `heartlife/backend/migrations/` 保持零修改，所有业务逻辑、数据库表结构、会话/CSRF 机制与医疗边界规则原样保留。

## 2. 现有前端技术栈与依赖基线

- **核心运行时**：`vue@^3.5.13`、`vue-router@^4.5.0`、`pinia@^2.3.0`
- **构建与测试**：`vite@^6.0.5`、`typescript@~5.6.3`、`vue-tsc@^2.2.0`、`vitest@^2.1.8`、`@vue/test-utils@^2.4.6`、`jsdom@^25.0.1`、`@playwright/test@^1.49.1`
- **本轮新增 UI/适老化组件栈（按 PRD §2 接入）**：
  - `tailwindcss` + `@tailwindcss/vite`：设计系统原子化与流式响应式排版
  - `reka-ui` + `class-variance-authority` + `clsx` + `tailwind-merge`：shadcn-vue 体系无障碍交互原语（焦点陷阱、Esc 关闭、焦点恢复、ARIA 状态）
  - `lucide-vue-next`：统一 24px 线性语义图标（搭配中文标签）
  - `echarts` + `vue-echarts`：SVG 矢量健康周报趋势图（配数字明细表）
  - `@axe-core/playwright`：WCAG 2.2 AA 自动无障碍扫描

## 3. 实际页面路由清单（共 15 条，改版前后路径保持 100% 兼容）

| 路由路径 | 路由名称 | 组件文件 | 鉴权要求 | 本轮改版重点 |
|---|---|---|---|---|
| `/login` | `login` | `AuthView.vue` | 匿名访问 | 460px 暖调欢迎卡、48px 输入、密码显隐可访问按钮 |
| `/` | `home` | `HomeView.vue` | 需登录 | 时区问候 Hero + 轻量陪伴插画、首屏记录/打卡双栏主区 |
| `/community` | `community` | `CommunityView.vue` | 公开读 / 登录写 | **UI-02 第一样板**：68%/32% 阅读流+友善公约侧栏、本地首字头像、防竞态与完整状态机 |
| `/community/:id` | `post-detail` | `PostDetailView.vue` | 公开读 / 登录互动 | 760px 舒适阅读列、统一 48px 图标动作条、Reka UI 举报/编辑/删除弹窗 |
| `/journal` | `journal` | `JournalView.vue` | 需登录 | 日期选择→分组填写→保存单页流、未记录温暖提示、二次确认删除 |
| `/plans` | `plans` | `PlansView.vue` | 需登录 | 今日计划真实完成比、48px 可勾选任务卡、失败回滚与模板磁贴 |
| `/knowledge` | `knowledge` | `KnowledgeView.vue` | 公开读 | 桌面 2–3 列卡片、16:9 本地暖调主题封面与容错占位 |
| `/knowledge/:id` | `article-detail` | `ArticleDetailView.vue` | 公开读 | 19px 舒适阅读、收藏、可选浏览器本地语音朗读、底部来源审核卡 |
| `/weekly-report` | `weekly-report` | `WeeklyReportView.vue` | 需登录 | 4 项清晰 KPI 卡、ECharts 2.5px 断线趋势图 + 每日数值明细表 |
| `/me` | `profile` | `ProfileView.vue` | 需登录 | 五大分组（个人资料/健康发布/收藏历史/显示设置/账号隐私与家庭关怀） |
| `/notifications` | `notifications` | `NotificationsView.vue` | 需登录 | 文字+底色双重区分「未读/已读」、目标下架安全拦截 |
| `/challenges` | `challenges` | `ChallengesView.vue` | 需登录 | P1 暖陶橙/淡草木绿任务卡、真实 `progressbar`、无排行榜 |
| `/assistant` | `assistant` | `AssistantView.vue` | 需登录 | P1 820px 对话框、能力边界、非诊疗示例提问、单次数据授权 |
| `/users/:id` | `public-user` | `PublicUserView.vue` | 公开读 | 暖调首字头像 + 公开简介与近期分享，零私密泄露 |
| `/ops` | `ops` | `OpsView.vue` | `moderator`/`editor` | 保留既有举报审核与科普发布流程，统一暖调表单控件 |

## 4. 既有 `/api/v1` 接口契约清单（保持零改动）

- 系统与配置：`GET /health`、`GET /public-config`
- 认证与个人：`POST /auth/register`、`POST /auth/login`、`POST /auth/logout`、`GET/PATCH /me`、`POST /me/revoke-sessions`、`GET /users/{user_id}`
- 社区与治理：`GET /community/categories`、`GET/POST /posts`、`GET/PATCH/DELETE /posts/{id}`、`GET /me/posts`、`PUT/DELETE /posts/{id}/like`、`PUT/DELETE /bookmarks/{type}/{id}`、`GET /me/bookmarks`、`GET/POST /posts/{id}/comments`、`DELETE /comments/{id}`、`PUT/DELETE /me/blocks/{id}`、`PUT/DELETE /me/follows/categories/{cat}`、`POST /reports`、`GET /moderation/reports`、`POST /moderation/reports/{id}/resolve`、`POST /moderation/content/{type}/{id}/hide|restore`、`GET /moderation/actions`
- 日记与计划：`GET /me/journals`、`GET/PUT/DELETE /me/journals/{date}`、`GET /plan-templates`、`GET/POST /me/plans`、`PATCH /me/plans/{id}`、`GET /me/today`、`PUT/DELETE /me/plans/{id}/checkins/{date}`、`POST /me/reminders/poll`
- 百科与编审：`GET /articles/categories`、`GET /articles`、`GET /articles/{id}`、`PUT /me/reading-history/{id}`、`GET/DELETE /me/reading-history`、`GET/POST/PATCH /editor/articles`、`POST /editor/articles/{id}/publish|unpublish`
- 首页、周报、消息与隐私：`GET /me/dashboard`、`GET /me/weekly-report`、`GET /me/notifications`、`POST /me/notifications/{id}/read`、`POST /me/notifications/read-all`、`GET /me/export`、`POST /me/delete`
- P1/P2 扩展：`GET /challenges`、`PUT/DELETE /challenges/{id}/membership`、`GET /me/challenges`、`POST /me/challenges/{id}/share`、`POST /assistant/chat`、`POST /me/family/invites`、`POST /me/family/accept`、`GET/PATCH/DELETE /me/family/grants`、`GET /family/shared/{granter_id}`

## 5. 现状视觉与适老化差距诊断

1. **视觉气质偏冷且胶囊化过度**：原背景 `#f4f7f6` 与主色 `#087f71` 偏冷工具感，按钮、筛选、导航大量使用 `999px` 全胶囊圆角，缺少消费级健康生活产品的温暖纸感与卡片呼吸层次。
2. **适老化字号与触控尺寸不足**：原全局正文字号仅 `15px`、按钮最小高度 `32–38px`，未达到中老年用户舒适阅读（正文 `18px`、可交互高度 `≥48px`）标准，且缺少持久化的「大字模式」「高对比度模式」和「减少动态」显示偏好。
3. **社区页单薄且缺少状态韧性**：缺少头像视觉锚点、列表直接互动反馈与右侧友善公约/话题导览；连续切换分类或网络较慢时缺少请求竞态保护（`AbortController` + 序号校验）及 10s/15s 分级等待与重试引导。
4. **缺少无障碍弹窗焦点管理与自动扫描**：原手写 `div.modal-backdrop` 未实现完整的键盘 Tab 焦点环锁定与关闭后焦点恢复，尚未纳入 `@axe-core/playwright` WCAG 2.2 AA 自动扫描。
