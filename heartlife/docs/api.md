# HeartLife API 契约导览 (`/api/v1`)

运行后端服务后，可通过 `/api/docs` 查看实时 OpenAPI 交互式文档，或访问 `/api/openapi.json` 获取完整 Schema。

## 统一约定

- **会话与安全**：登录后写入同源 `HttpOnly` Cookie `hl_session` 及可读 Cookie `hl_csrf`；所有已登录写接口（`POST` / `PUT` / `PATCH` / `DELETE`）须携带请求头 `X-CSRF-Token`。
- **错误响应格式**：
  ```json
  {
    "error": {
      "code": "VALIDATION_ERROR",
      "message": "可读错误原因",
      "request_id": "8f2c..."
    }
  }
  ```
- **分页约定**：列表接口统一返回 `{ "items": [...], "next_cursor": "..." }`。

## 核心路由总览

| 模块 | 方法与路径 | 权限 | 说明 |
|---|---|---|---|
| 系统 | `GET /api/v1/health` | 匿名 | 健康检查 |
| 系统 | `GET /api/v1/public-config` | 匿名 | 返回助手开关、经校验的外部 ECG HTTPS 链接及演示标识 |
| 认证 | `POST /api/v1/auth/register` | 匿名 | 独立账号注册（Argon2id 存储） |
| 认证 | `POST /api/v1/auth/login` | 匿名 | 登录（含可注入时钟滑动窗口限流） |
| 认证 | `POST /api/v1/auth/logout` | 登录+CSRF | 撤销当前会话 |
| 个人 | `GET/PATCH /api/v1/me` | 登录 | 获取/更新昵称、简介与时区 |
| 个人 | `POST /api/v1/me/revoke-sessions` | 登录+CSRF | 撤销本人全部活跃会话 |
| 个人 | `GET /api/v1/users/{user_id}` | 匿名/登录 | 查看他人公开主页（绝不返回私密日记/计划/挑战） |
| 社区 | `GET/POST /api/v1/posts` | 公开读 / 登录写 | 分类筛选、关键词搜索、关注流、游标分页与发帖 |
| 社区 | `GET/PATCH/DELETE /api/v1/posts/{id}` | 公开读 / 作者写 | 帖子详情、编辑与删除 |
| 互动 | `PUT/DELETE /api/v1/posts/{id}/like` | 登录+CSRF | 幂等点赞与取消点赞 |
| 互动 | `GET/POST /api/v1/posts/{id}/comments` | 公开读 / 登录写 | 单层回复嵌套评论（支持 `request_id` 幂等去重） |
| 互动 | `PUT/DELETE /api/v1/bookmarks/{type}/{id}` | 登录+CSRF | 收藏帖子或百科文章（收藏夹仅本人可见） |
| 治理 | `PUT/DELETE /api/v1/me/blocks/{id}` | 登录+CSRF | 屏蔽用户 |
| 治理 | `POST /api/v1/reports` | 登录+CSRF | 幂等举报帖子或评论 |
| 审核 | `GET /api/v1/moderation/reports` | `moderator` | 查看举报队列 |
| 审核 | `POST /api/v1/moderation/reports/{id}/resolve` | `moderator`+CSRF | 处理举报并隐藏违规内容、记录审计 |
| 审核 | `POST /api/v1/moderation/content/{type}/{id}/restore` | `moderator`+CSRF | 恢复已隐藏内容并保留历史审计 |
| 日记 | `GET /api/v1/me/journals` | 本人 | 查询私密健康日记列表 |
| 日记 | `GET/PUT/DELETE /api/v1/me/journals/{date}` | 本人 | 按用户时区本地日读写删除日记（区分 `null` 与 `0`） |
| 计划 | `GET/POST /api/v1/me/plans` | 本人 | 查看与创建习惯计划 |
| 计划 | `PATCH /api/v1/me/plans/{id}` | 本人+CSRF | 修改计划（生成下一本地日生效的新版本，不改写历史分母） |
| 计划 | `GET /api/v1/me/today` | 本人 | 今日待办打卡与站内提醒轮询 |
| 计划 | `PUT/DELETE /api/v1/me/plans/{id}/checkins/{date}` | 本人+CSRF | 幂等打卡与撤销打卡 |
| 百科 | `GET /api/v1/articles` / `GET /api/v1/articles/{id}` | 公开读 | 已审核发布的健康百科列表与详情 |
| 百科 | `PUT /api/v1/me/reading-history/{id}` / `DELETE /api/v1/me/reading-history` | 本人 | 记录与清除个人阅读历史 |
| 编审 | `POST/PATCH /api/v1/editor/articles`、`publish`、`unpublish` | `editor`+CSRF | 草稿编纂、来源与审核校验发布、下架 |
| 聚合 | `GET /api/v1/me/dashboard` | 本人 | 首页卡片聚合 |
| 周报 | `GET /api/v1/me/weekly-report` | 本人 | 周一至周日确定性健康周报 |
| 消息 | `GET /api/v1/me/notifications`、`read`、`read-all` | 本人 | 站内通知与目标可见性复验 |
| 隐私 | `GET /api/v1/me/export`、`POST /api/v1/me/delete` | 本人+二次认证 | 导出个人 JSON 数据、事务级注销账号 |
| P1/P2 | `/challenges`、`/assistant/chat`、`/me/family/*` | 登录 | 行为挑战徽章、可关闭生活助手、家庭最小字段共享 |
