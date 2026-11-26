# HeartLife 验收矩阵与实测报告 (Acceptance & Benchmark Evidence)

## 1. 原仓库零改动核验（T-0005 / T-0709）

- **原仓库路径**：`c:\Users\NickHu\Desktop\bme\bme-ecg-system`
- **开发前 HEAD SHA**：`91ad66e1ace19c213035ad92276ae5a56670a685`
- **开发后 HEAD SHA**：`91ad66e1ace19c213035ad92276ae5a56670a685`
- **原仓库 `git status`**：`nothing to commit, working tree clean`（源码、配置、数据库、分支与提交历史 100% 零改动）
- **新工程路径**：`c:\Users\NickHu\Desktop\bme\heartlife`（独立 Git 仓库、独立 `.venv`、独立 `node_modules`、独立 SQLite 数据库）

## 2. 自动化验收汇总

统一执行入口：`.\.venv\Scripts\python.exe scripts/check.py --suite all`

| 测试层级 | 工具与范围 | 用例数量 | 结果 | 耗时 |
|---|---|---:|---|---:|
| 后端单元与集成测试 | `pytest`（覆盖 `T-0001` ~ `T-1105` 全部自动化契约、权限、幂等与事务回滚） | 92 | **92 passed, 0 failed** | ~26.0s |
| 前端静态类型检查 | `vue-tsc -b --noEmit` | 全工程 | **0 errors** | ~1.2s |
| 前端组件与状态单测 | `vitest --run`（居中导航、空态防假零、周报分母、日记 null/0、防 XSS、CSRF） | 8 | **8 passed, 0 failed** | ~1.9s |
| 前端生产构建 | `vite build` | 84 modules | **PASS** | ~1.1s |
| 浏览器全链路 E2E | `playwright test`（真实 Chrome，跨账号社区审核、日记计划周报联动、375/390/1280px 居中与防溢出、家庭关怀与账号注销） | 6 | **6 passed, 0 failed** | ~26.2s |

## 3. 本地合成数据并发性能实测（PRD §9）

执行脚本：`.\.venv\Scripts\python.exe scripts/benchmark_perf.py`

- **测试机器环境**：Windows 11 · Python 3.12.0 · 16 逻辑核心 · SQLite WAL 模式
- **合成数据规模**：50 名合成用户、**1,000 篇社区帖子**、**5,000 条私密日记 + 5,000 条习惯打卡（共 10,000 条记录）**、12 篇已发布科普（数据生成耗时 `0.51s`）
- **并发负载组合**：**20 并发虚拟用户（VU）**，覆盖 `/api/v1/posts?limit=20`、`/api/v1/articles?limit=10`、`/api/v1/me/dashboard`、`/api/v1/me/weekly-report`，共 `240` 次请求（总耗时 `1.56s`）
- **实测结果**：
  - `2xx` 成功响应：`240 / 240`
  - `5xx` 错误数：**`0`**
  - 平均响应延迟：`125.83 ms`
  - `P50` 延迟：**`120.85 ms`**
  - `P95` 延迟：**`228.20 ms`**（满足课程建议目标 `P95 ≤ 500ms`）
  - `P99` 延迟：**`273.99 ms`**

## 4. 界面视觉与交互验收记录（T-0708 / T-0610）

通过内置浏览器对本地运行实例（`http://127.0.0.1:8010`）完成 `1280×820` 桌面端与 `375×812` 移动端实测巡检：
- **视觉居中**：顶栏采用三栏对称网格保证胶囊主导航严格水平居中，主内容区 `880px` 与详情阅读区 `740px` 左右留白完全对称，登录/注册卡片视口双向居中。
- **文案克制**：无冗余页面副标题或说明性废话，仅保留操作标签与必需的一句话隐私/非医疗提示。
- **响应式与无障碍**：`375px` 与 `390px` 下无任何横向滚动溢出，底部五项导航栏固定清晰；周报 SVG 趋势图同步配齐每日明细数值表，打印样式自动隐藏导航、操作按钮与私密备注。
