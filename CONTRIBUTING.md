# 成员入门与协作流程

## 权限

所有成员均可修改固件、终端、算法、云端、网页和文档。没有目录专属负责人或 CODEOWNERS 审批门槛。任务负责人仅用于协调进度，任何成员都能认领任何模块的任务。

仓库所有者在 GitHub 仓库 `Settings → Collaborators → Add people` 使用成员的 GitHub 用户名或注册邮箱发出邀请。成员接受后获得协作写入权限；每人使用自己的账号和本地克隆。

PR 必须通过 `Quality gate`、与主分支同步、解决审查讨论，并获得至少另一位有写入权限成员的正式批准（Approve）；新提交使旧批准失效时，需重新审查。所有成员可审查所有模块，不设置目录专属批准人。GitHub 强制规则以仓库设置为准，具体配置、AI 审查和发布流程见 [协作质量与发布](docs/协作质量与发布.md)。仓库管理权限与开发写入权限不同，所有者负责成员邀请和仓库设置。

## 首次加入

```powershell
git clone https://github.com/XiongBoT/bme-ecg-system.git
cd bme-ecg-system
git config user.name "你的姓名"
git config user.email "你的 GitHub 提交邮箱"
```

按 README 安装依赖。可以在 VS Code 中编辑；每人独立安装工具链，不共享虚拟环境。没有 STM32 或树莓派的成员可用现有模拟和回放工具开发，PR 中注明使用了哪种数据。

## 每个任务的操作

1. 在 Issues 建立任务，写明目标、预计修改的文件/目录、任务分支和验收条件，认领后开始。先查看未完成的 Issue/PR，按[任务协调约定](docs/团队协作.md#任务认领)确认是否存在重叠修改；扩大范围时先更新任务。跨模块修改可放在同一任务中；一个 PR 聚焦一个问题。
2. 确认当前修改已提交或妥善暂存，再更新主分支并创建任务分支：

```powershell
git switch main
git pull --ff-only
git switch -c feat/history-filter
```

3. 编写代码与必要的测试。串口协议、原始记录格式、HTTP API、账号/设备归属或模型输入有变化时，同步修改 `docs/接口约定.md`、相关模块说明及相应测试，并检查调用端兼容性。避免在功能修改中夹带无关的整文件格式化、批量改名或目录搬迁；确有必要时另开任务。
4. 查看差异后，只暂存这次任务涉及的文件。例如修改云端网页：

```powershell
git status --short
git diff
git add "心电云端平台/web/app.js"
git diff --cached
git commit -m "feat: 增加历史记录筛选"
git push -u origin feat/history-filter
```

5. 在 GitHub 创建 PR，目标分支为 `main`，关联 Issue，按模板填写文件范围、效果、检查结果、兼容性和是否需要部署。可先开 Draft PR 让并行任务看到修改范围；准备好后再转为正式审查。
6. 提交审查及合并前检查是否落后于 main。在工作区无未提交改动时，于任务分支执行 `git fetch origin`、`git merge origin/main`；如有冲突，逐处核对两边意图，保留双方有效功能，重跑受影响的检查后提交、推送。不要整文件选择“全部用我的/对方的”来消除冲突，也不要强制推送覆盖公共分支。main 后续又更新时重复同步；Git 显示无冲突仍需检查行为是否兼容。
7. 等待 GitHub Actions 的 `Quality gate` 成功，核实 AI/人工意见、解决讨论，并获得至少另一位有写入权限成员的有效批准后合并 PR。批准后有新修改且旧批准被撤销时，重新请求审查；AI 无意见或提交者自查均不能替代该批准。其他成员随后更新 main；一个任务结束后，下个任务重新建分支。

不要多人同时编辑同一个共享磁盘工作目录。同一电脑需要并行任务时使用独立克隆或 Git worktree；已有未提交工作时优先新建隔离工作目录，不替他人 stash、reset 或 clean。对同一个文件的重叠修改先在任务中协调，具体方式见[任务认领](docs/团队协作.md#任务认领)。这些约定减少冲突，不能保证永远没有冲突；GitHub 不会自动锁定 Issue 中声明的文件。

## 检查与实物联调

```powershell
.\.venv\Scripts\python.exe tools/run_checks.py --suite pi
.\.venv\Scripts\python.exe tools/run_checks.py --suite cloud
.\.venv\Scripts\python.exe tools/run_checks.py --suite web
```

不指定 `--suite` 则依次运行三个模块的检查，任一失败返回非零退出码。两个 Python 工程分开运行，防止它们的同名 `protocol.py` 相互干扰。

固件改动还应提供 Keil 编译结果；串口、显示、采集或部署相关修改还应提供实物验证记录。记录明确区分本机模拟、公开数据库回放、板端模拟与真实采集。

正式设备和服务器的更新需要另行安排，合并 PR 不自动部署。部署前记录当前版本和回退方法，共用板卡时先协调使用时间。

## 文件与数据

查找源码和决定新增文件的位置时，先看 [仓库导览](docs/仓库导览.md)；模型与离线研究入口见 [算法与评估](docs/算法与评估.md)。

提交源码、依赖清单、文档、公开来源的必要模型及测试向量。真实心电记录、账号数据库、设备凭据和服务器密钥通过另行授权的渠道管理，不放进仓库或 Issue/PR 附件。

本地历史报告不自动进入仓库；要新增可共享文档时放到 `docs/`。新增顶层模块需要同步调整根目录 `.gitignore` 的纳入规则。

文档维护：当前源码、下载、部署和实机验收状态统一更新[版本与交付状态](docs/版本与交付状态.md)，分别附提交、Release 或验证证据；操作文档链接到该页，不将“已合并”写成“已上线”。移动文档或修改章节标题时检查旧链接，历史记录保留适用版本。

文件归位：共同说明放根 `docs/`；模块操作与设计放各模块 `docs/`，历史方案与旧图放 `docs/archive/` 并标注适用阶段。可复用脚本放原有 `tools/` 或 `deploy/`；软件测试放模块 `tests/`。模块 `README.md` 提供导航，现行步骤在模块 `docs/快速开始.md`、`使用说明.md`、`故障排查.md` 维护；修改后执行 `python tools/sync_docs.py --write` 更新离线 `README.txt`，不手工维护两份内容。新增重要入口时更新 [文档导航](docs/README.md)，移动文件时一并修正链接和打包引用。Keil、Python 导入及启动脚本要求的目录保持原样。

文档和文件归位修改提交前，执行 `python tools/check_docs.py`、`python tools/sync_docs.py --check` 及 `python -m unittest discover -s tools -p "test_*.py" -v`。新增文件先纳入暂存区：检查器以 Git 跟踪路径为准，不让本机未跟踪文件掩盖断链。当前四份服务器/终端发布白名单纳入静态路径检查；Windows/Android 打包另有原 CI 检查。
