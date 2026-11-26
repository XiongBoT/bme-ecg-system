# 心伴 HeartLife｜适老化健康生活与同伴互助平台

**心伴（HeartLife）** 是面向中老年友好阅读与日常健康管理的独立 Web 应用，涵盖温暖陪伴式首页、同伴互助社区、单页流健康日记、习惯计划打卡、经课程审核的健康百科（支持本地语音朗读）、健康周报趋势图、微习惯挑战、家庭极简关怀与有边界的健康生活助手。

> **服务与数据边界**：本模块保留独立账号、会话、SQLite 数据库和 Python/Node 依赖，默认监听 `127.0.0.1:8010`。与原心电平台（`127.0.0.1:8766`）通过可选的本人只读授权接口连接，默认关闭；不直接读取其数据库。仅配置 `ECG_EXTERNAL_URL` 时仍保留独立工具跳转。绑定、部署和验收见[心电集成](docs/心电集成.md)。
>
> **非医疗声明**：本平台仅用于健康生活记录与科普参考，不提供疾病诊断、处方剂量建议、心电波形临床判读或急症监护。

---

## 目录结构

```text
heartlife/
├── backend/                  # FastAPI + SQLAlchemy 2 + Alembic + SQLite + FTS5
│   ├── app/                  # 模块化单体业务服务
│   ├── migrations/           # Alembic 数据库迁移脚本
│   └── tests/                # Pytest 后端单元与集成测试 (92 项)
├── frontend/                 # Vue 3 + TypeScript + Vite + Reka UI + Tailwind CSS v4 + ECharts
│   ├── src/                  # 适老化暖调设计系统 (theme.css)、无障碍原语与全部页面
│   ├── tests/                # Vitest 组件与适老化交互单测 (30 项)
│   └── e2e/                  # Playwright 多视口、200% 缩放与 @axe-core WCAG 2.2 AA 验收测试
├── deploy/
│   └── tencent-cloud/        # 腾讯云 Ubuntu 24.04 一键构建脚本、systemd 服务与 Nginx HTTPS 模板
├── scripts/                  # 数据库迁移、合成演示数据生成、统一检查与压测脚本
└── docs/                     # 腾讯云部署指南、架构、API、适老化改版审计与验收文档
```

---

## 核心适老化与产品特性

1. **温暖医疗关怀视觉与适老规格**：暖米白纸感画布（`#F8F6F0`）+ 沉稳森林绿主色（`#28664F`）+ 暖陶橙点缀（`#AD6235`），默认正文 `18px`（行高 `1.65`），所有交互控件最小触控高度 `≥ 48px`。
2. **三项持久化无障碍显示偏好**：顶栏支持一键切换 **大字阅读模式**（`22px` 正文 / `56px` 热区，纯 `rem` 变量缩放），「我的 → 显示设置」支持 **高对比度模式** 与 **减少界面动态效果**，仅存本地浏览器显示偏好，零隐私泄露。
3. **严谨的数据真实性与防竞态韧性**：未记录的睡眠/活动严格显示「尚未记录」而非 `0 分钟`；社区与百科具备 `AbortController` + 请求序号防竞态保护、结构化骨架屏及失败草稿保留；高风险删除/撤销均具备二次确认弹窗。

---

## 本地快速启动（Windows PowerShell / Linux）

### 1. 安装依赖与初始化数据库

在 `heartlife` 目录下执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe scripts/migrate.py

cd frontend
npm install
```

### 2. （可选）生成丰富的合成演示内容

默认不创建固定弱口令账号。本地体验演示时显式开启 `DEMO_MODE=1`：

```powershell
$env:APP_ENV="local"
$env:DEMO_MODE="1"
.\.venv\Scripts\python.exe scripts/populate_rich_demo.py
```

预置演示账号（统一密码 `DemoPass123!`，登录页支持一键填入）：
- 普通成员：`demo_alice`（林晓禾）、`demo_bob`（陈远山）、`demo_wang`、`demo_zhang`
- 社区治理员：`demo_mod`（可进入顶栏「运营」工作台）
- 科普编辑：`demo_editor`

### 3. 构建并启动同源服务（推荐）

```powershell
cd frontend
npm run build
cd ../backend
$env:APP_ENV="local"
$env:DEMO_MODE="1"
$env:ASSISTANT_ENABLED="true"
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

浏览器访问 `http://127.0.0.1:8010` 即可体验完整前后端功能（开发调试亦可单独在 `frontend/` 运行 `npm run dev` 访问 `5174` 端口）。

---

## 腾讯云生产部署

针对腾讯云 Ubuntu 24.04 云主机（含与原心电云端平台同机隔离共存方案、Nginx HTTPS 反向代理、`systemd` 用户常驻服务、备份与平滑升级回退流程），请直接参阅：

- **[腾讯云部署与运维指南](docs/腾讯云部署与运维指南.md)**
- 部署脚本与配置模板：[deploy/tencent-cloud/](deploy/tencent-cloud/)

---

## 自动化测试与质量门禁

```powershell
# 一键运行全套门禁（后端 Pytest + 前端 Typecheck/Vitest/Build + Playwright & Axe 无障碍 E2E）
.\.venv\Scripts\python.exe scripts/check.py --suite all
```

---

## 文档导航

- **心电连接**：[账号绑定、本人摘要与同一 APP 入口](docs/心电集成.md)；需要配套部署及新版 APK，合入源码不代表已上线。
- **部署与运维**：[腾讯云部署与运维指南](docs/腾讯云部署与运维指南.md)
- **适老化 UI 改版文档**：[基线审计](docs/ui-audit.md) · [TDD 改版进度](docs/ui-progress.md) · [32 项验收报告](docs/ui-acceptance.md) · [素材与授权台账](docs/ui-assets.md)
- **后端与产品基础文档**：[系统架构](docs/architecture.md) · [API 契约](docs/api.md) · [架构决策 ADR-0001](docs/adr/0001-decoupled-monolith-and-stack.md) · [隐私治理与医疗边界](docs/privacy-and-moderation.md) · [百科来源核验](docs/knowledge-sources-review.md) · [基础验收矩阵](docs/acceptance.md) · [演示脚本](docs/demo.md)
