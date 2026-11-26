# ADR-0001：独立模块化单体架构、技术栈与测试门禁约定

- **状态**：已采纳（2026-11-26）
- **背景**：HeartLife（心伴）需在不改动、不依赖原 `bme-ecg-system` 任何代码、数据库、会话或设备的前提下，提供独立的心脏健康生活记录、习惯计划、科普学习、健康周报与同伴互助社区。

## 决策

1. **物理与工程完全隔离**：在原仓库同级目录 `c:\Users\NickHu\Desktop\bme\heartlife` 建立独立 Git 仓库、独立 `.venv`、独立 `frontend/` 与独立 SQLite 数据库。
2. **后端选型**：Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic + SQLite（开启 `PRAGMA foreign_keys=ON`、`busy_timeout=5000`、`WAL` 模式）+ Argon2id (`argon2-cffi`)。
3. **会话与安全**：采用服务端 `sessions` 表存储 SHA-256 哈希后的随机会话令牌，通过同源 `HttpOnly` Cookie (`hl_session`) 传递会话，写接口强制校验 `X-CSRF-Token` 请求头与会话绑定的 CSRF 令牌，杜绝 `localStorage` 存储登录凭据。
4. **前端选型与设计语言**：Vue 3 + TypeScript + Vite + Pinia + Vue Router；采用青绿清爽色调（`#087f71` / `#f4f7f6`）与视觉居中布局（居中顶栏 + `max-width: 960px` 居中主容器 + 移动端底部导航），界面不添加多余说明文字。
5. **模块边界**：后端按领域划分 `accounts`、`community`、`journal`、`plans`、`knowledge`、`reports`、`notifications`、`privacy`、`challenges`、`assistant`、`family`，共享统一 `notifications.service` 与可注入 `Clock`，便于确定性测试与并行子代理协作。
