# HeartLife 开发进度与 TDD 证据台账 (Progress)

> 状态枚举：`TODO` / `IN_PROGRESS` / `PASS` / `BLOCKED` / `DEFERRED`
> 真实性声明：以下所有命令与退出码均为本轮实际执行记录。自动化测试 `PASS` 代表软件契约、权限隔离与多视口浏览器交互通过，不等同于临床有效性验证或真实多用户长期运营实验。

| 任务 ID | 范围 | 状态 | Red 验证命令与退出码 | Green 验证命令与退出码 | 覆盖测试 ID | 关键产物 |
|---|---|---|---|---|---|---|
| TASK-00 | 独立工程、Alembic 迁移、seed_demo、外部 URL 门禁与检查脚本 | PASS | `pytest tests/test_epic00_bootstrap.py -q` → Exit `1` (13 failed) | `pytest tests/test_epic00_bootstrap.py -q` → Exit `0` (13 passed) | T-0001~T-0006, T-1001~T-1003 | `app/core/`, `app/db/`, `migrations/`, `app/seed.py`, `scripts/check.py` |
| TASK-01 | 账号注册、Argon2id、HttpOnly 会话、CSRF、登录限流与公开主页 | PASS | `pytest tests/test_epic01_accounts.py -q` → Exit `1` (7 failed) | `pytest tests/test_epic01_accounts.py -q` → Exit `0` (7 passed) | T-0101~T-0108 | `app/accounts/`, `tests/test_epic01_accounts.py` |
| TASK-02 | 社区 5 大分类、发帖、游标稳定分页、搜索与纯文本防 XSS | PASS | `pytest tests/test_epic02_community.py -q` → Exit `1` (16 failed) | `pytest tests/test_epic02_community.py -q` → Exit `0` (16 passed) | T-0201~T-0206 | `app/community/`, `tests/test_epic02_community.py` |
| TASK-03 | 点赞、私密收藏、单层嵌套评论（幂等）、举报、屏蔽与审核闭环 | PASS | 同上（Exit `1`, 16 failed） | 同上（Exit `0`, 16 passed） | T-0207~T-0216 | `app/community/`, `app/notifications/service.py` |
| TASK-04 | 私密健康日记（null 与 0 区分、时区跨日校验、严格本人可见） | PASS | `pytest tests/test_epic03_journal.py tests/test_epic04_plans.py -q` → Exit `1` (16 failed) | `pytest tests/test_epic03_journal.py tests/test_epic04_plans.py -q` → Exit `0` (16 passed) | T-0301~T-0308 | `app/journal/`, `tests/test_epic03_journal.py` |
| TASK-05 | 版本化习惯计划（历史分母不改写）、幂等打卡、连胜计算与站内提醒 | PASS | 同上（Exit `1`, 16 failed） | 同上（Exit `0`, 16 passed） | T-0401~T-0410 | `app/plans/`, `tests/test_epic04_plans.py` |
| TASK-06 | 健康百科（来源 URL 校验、课程内容审核记录、修订版本、阅读历史） | PASS | `pytest tests/test_epic05_knowledge.py tests/test_epic09_assistant.py -q` → Exit `1` (15 failed) | `pytest tests/test_epic05_knowledge.py tests/test_epic09_assistant.py -q` → Exit `0` (15 passed) | T-0501~T-0507（T-0508 登记人工清单） | `app/knowledge/`, `docs/knowledge-sources-review.md` |
| TASK-07 | 首页聚合、确定性健康周报（含打印隐藏私密备注）与站内消息 | PASS | `pytest tests/test_epic06_dashboard_reports.py ... -q` → Exit `1` (25 failed) | `pytest tests/test_epic06_dashboard_reports.py ... -q` → Exit `0` (25 passed) | T-0601~T-0610 | `app/reports/`, `app/notifications/router.py` |
| TASK-08 | 个人数据导出、二次认证原子注销、跨角色越权拦截与多视口 E2E | PASS | 同上（Exit `1`） | `python scripts/check.py --suite all` → Exit `0` | T-0701~T-0709 | `app/privacy/`, `frontend/e2e/heartlife.spec.ts` |
| TASK-09 | P1 行为挑战、单次徽章、显式分享与公开话题关注流 | PASS | 同上（Exit `1`） | `pytest tests/test_epic08_challenges.py tests/test_epic02_community.py -q` → Exit `0` | T-0801~T-0806 | `app/challenges/`, `ChallengesView.vue` |
| TASK-10 | P1 AI 健康生活助手（默认关闭、FTS5 检索、单次授权、引用与急症门禁） | PASS | `pytest tests/test_epic09_assistant.py -q` → Exit `1` | `pytest tests/test_epic09_assistant.py -q` → Exit `0`（T-0909 离线人工评测标 `NOT RUN`） | T-0901~T-0908 | `app/assistant/`, `AssistantView.vue` |
| TASK-11 | P1 可选独立 ECG 外部 HTTPS 入口与无参安全跳转确认框 | PASS | `pytest tests/test_epic00_bootstrap.py -q` → Exit `1` | `pytest tests/test_epic00_bootstrap.py -q` + Vitest → Exit `0` | T-1001~T-1004 | `sanitize_external_ecg_url`, `ExternalEcgModal.vue` |
| TASK-12 | P2 家庭关怀一次性限时邀请码、最小字段共享与即时撤销 | PASS | `pytest tests/test_epic11_family.py -q` → Exit `1` | `pytest tests/test_epic11_family.py -q` + Playwright E2E → Exit `0` | T-1101~T-1105 | `app/family/`, `ProfileView.vue` |
| TASK-13 | 视觉居中前端打磨、并发性能基准、全量回归与交付材料冻结 | PASS | 集成修复评论同秒分组排序与 CWD 相对库路径 | `scripts/check.py --suite all` Exit `0` + 浏览器 1280px/375px 实测通过 | 92 Pytest + 8 Vitest + 6 E2E | `frontend/src/`, `scripts/benchmark_perf.py`, `docs/` |

## 心电集成第二轮（任务 #85，2026-11-27）

本轮在第一轮合并提交 `751e83d` 上实现另行授权的测量、进度及独立私密心电周报。沿用旧账号与设备规则，不自动扩大旧授权，不触发生产部署或公开安装包发布。

| 检查 | 状态 | 实际执行与证据 |
| --- | --- | --- |
| 心电网页回归 | PASS | `node --test 心电云端平台/tests/*.test.cjs`：退出码 0，190 项通过、0 跳过；包括 15 项授权页测试 |
| 心电 Python 局部回归 | PASS | 短程 `unittest`：31 项通过，命令退出码均为 0，覆盖 5 项新测量、1 项旧表迁移、13 项原桥接、10 项原健康助手与 2 项趋势测试；首次新测试执行退出码 1，原因是尚未实现接口及本地缺少时区数据 |
| Python 与双服务完整契约 | PASS | [CI 45932330193](https://github.com/XiongBoT/bme-ecg-system/actions/runs/45932330193)：心伴 `python -m pytest -q` 退出码 0，127 项通过；心电云端 257 项、10 项按环境跳过，退出码 0；周统计、旧授权、幂等、撤销竞态均已运行 |
| 心伴前端回归与生产构建 | PASS | 首次 CI Vitest 退出码 1：54 项通过、2 项旧周报测试缺少登录场景。补齐登录 fixture 并保留原行为断言后，[CI 45932725116](https://github.com/XiongBoT/bme-ecg-system/actions/runs/45932725116) 的 `npm run test -- --run` 退出码 0，56 项通过；`VITE_BASE_PATH=/heartlife/ npm run build` 退出码 0，含 `vue-tsc -b` 与生产构建 |
| 真实设备、手机视觉及生产部署 | DEFERRED | 本轮没有执行，不以自动化测试替代 |
| 仓库与文档工具 | PASS | `python -m unittest discover -s tools -p 'test_*.py' -v`：退出码 0，26 项通过；文档链接及生成文件检查退出码 0 |

本地没有完整心伴运行依赖；不把语法检查记为运行测试。第一轮本地依赖安装和浏览器配置曾因非必要遥测请求被自动审批拒绝，本轮沿用隔离 CI 完成完整验证，不重复该配置。

上述 CI 验证提交 `23a4e1f694b2d20abde1d413b55e2acb7116bb3e`；仓库、云端、树莓派、网页、算法与 Windows / Android 打包检查均通过。后续提交的最终门禁结果以 [PR #86](https://github.com/XiongBoT/bme-ecg-system/pull/86) 当前 HEAD 的检查为准。合成数据测试不代表已部署或实机验收。

## 部署后文档同步（任务 #90，2026-11-27）

依据负责人回传的部署结果，更新根 README、心伴与云端说明、使用入口及运维导航；服务器实际版本仍为 `6ac70ff3`。保留历史记录和旧章节锚点，不将文档更新记为服务重新部署或 APK 发布。真实账号绑定、实体测量与报告待验收，详见[交付状态](../../docs/版本与交付状态.md)。

本次仅修改文档，使用已有检查验证链接、打包引用与生成文本；未新增业务测试，也未重跑应用完整测试。

| 实际执行命令（仓库根目录） | 退出码 | 结果 |
| --- | --- | --- |
| `python tools/check_docs.py` | 0 | 本地文档链接、章节锚点及打包引用检查通过 |
| `python tools/sync_docs.py --write` | 0 | 更新 1 份生成的云端离线 README |
| `python tools/sync_docs.py --check` | 0 | 3 份生成文档同步，无过期文件 |
| `python -m unittest discover -s tools -p "test_*.py" -v` | 0 | 共 34 项，33 通过，1 项因 Windows 不允许创建符号链接而跳过；对应 Linux 检查由 CI 执行 |

## 待人工验收项（诚实登记，不冒充自动化完成）

1. **T-0508（科普来源人工核验）**：11 篇内置科普已整理公开权威来源链接并标记「课程内容审核（演示核验）」，正式对外发布前须由课程成员逐条点击外链核对原文并签字（清单见 `docs/knowledge-sources-review.md`）。
2. **T-0909（真实外部大模型 30 题离线人工评测）**：当前未授权调用外部商用 LLM API Key，状态登记为 `NOT RUN`；本地确定性检索与 `FakeLLM` 引用校验/急症拒答自动化测试（`T-0901`~`T-0908`）已全部通过。
3. **课堂可用性志愿者试用（PRD §11）**：待课程展示前组织 5–10 名同学使用合成账号完成 5 项任务并记录主观问卷，当前登记为 `NOT RUN`。
