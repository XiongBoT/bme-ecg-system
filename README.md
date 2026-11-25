# 生医工综合 · 心电采集与分析系统

STM32 心电采集、树莓派显示与分析、云端记录平台的共同开发仓库。

按使用目的选择入口。各模块 README 提供导航，具体操作在模块 `docs/`；离线 `README.txt` 由现行 Markdown 自动生成。

| 你要做什么 | 从这里开始 |
| --- | --- |
| 下载并使用系统 | [应用下载](#应用下载) → [快速开始](心电云端平台/docs/快速开始.md#使用现有平台) |
| 手机查记录、设备或报告 | [手机使用说明](心电云端平台/docs/使用说明.md#手机使用流程102-源码待发布) · [手机版本区别](docs/手机端与安卓安装包.md) |
| 在终端测量、接线或排查设备 | [终端日常使用](树莓派心电终端/docs/设备待机与日常使用.md) · [硬件导航](硬件/README.md) |
| 管理账号、设备和数据库 | [管理员操作](心电云端平台/docs/使用说明.md#管理员账号管理待部署) · [数据库管理](心电云端平台/docs/使用说明.md#数据库管理源码已实现待部署) |
| 确认哪些功能已合并、已发布或待部署 | [版本与交付状态](docs/版本与交付状态.md) |
| 阅读源码与接口 | [仓库导览](docs/仓库导览.md) → [接口约定](docs/接口约定.md) |
| 找算法、模型和实验结果 | [算法与评估](docs/算法与评估.md) |
| 参与开发、了解计划或查全部文档 | [贡献指南](CONTRIBUTING.md) · [项目计划书](docs/项目计划书.md) · [文档中心](docs/README.md) |

## 应用下载

| 平台 | 当前下载或入口 | 使用方式 |
| --- | --- | --- |
| Windows 10/11 | [下载 1.1.0 ZIP](https://github.com/XiongBoT/bme-ecg-system/releases/download/desktop-v1.1.0/ecg-workspace-windows-1.1.0.zip) · [版本与校验](https://github.com/XiongBoT/bme-ecg-system/releases/tag/desktop-v1.1.0) | 全部解压后双击“心电工作台.exe”；无需 Python 或 Node.js，需联网 |
| Android 8.0+ | [下载 1.0.0 试用 APK](https://github.com/XiongBoT/bme-ecg-system/releases/download/android-v1.0.0-preview.1/ecg-records-1.0.0.apk) · [版本与校验](https://github.com/XiongBoT/bme-ecg-system/releases/tag/android-v1.0.0-preview.1) | 安装后使用现有平台账号；实体手机安装、保存和升级仍待验收 |
| 浏览器／iPhone | [打开 HTTPS 网页](https://62.234.150.104/) | 联网使用；iPhone 可添加到主屏幕 |

**当前下载仍为 Windows 1.1.0 和 Android 1.0.0 试用版。** 手机 1.0.2、账号管理、独立 QRS/RR 和数据库管理已合入源码，发布与部署状态见[统一状态页](docs/版本与交付状态.md)。旧 APK 的“记录、结果、账号”与新源码的“记录、设备、我的”属于不同版本；刷新旧 APK 不会更新内置界面。

仓库及安装包公开，个人心电记录仍需使用本人平台账号登录。没有账号或忘记密码时，联系创建账号的项目管理员；GitHub 账号、服务器 SSH 账号与平台账号分别管理。

安装细节：[Windows 使用说明](心电云端平台/deploy/desktop/使用说明.txt) · [手机与 APK 指南](docs/手机端与安卓安装包.md)。

## 从这里开始

首次阅读建议按“[仓库导览](docs/仓库导览.md) → 所需模块 → [接口约定](docs/接口约定.md)”的顺序；早期设计与阶段资料见各模块的历史分类。

| 目录 | 内容 | 入口 |
| --- | --- | --- |
| [硬件/STM32心电采集](硬件/STM32心电采集/) | 固件、HAL/CMSIS、Keil 工程及接线资料 | [模块导航](硬件/STM32心电采集/README.md) |
| [树莓派心电终端](树莓派心电终端/) | 采集、屏幕显示、记录、预处理和端侧分类 | [模块导航](树莓派心电终端/README.md) |
| [心电云端平台](心电云端平台/) | 服务端、网页、账号/设备、电脑客户端与部署工具 | [模块导航](心电云端平台/README.md) |
| [docs](docs/) | 共同接口、协作与公开数据评估结果 | [文档导航](docs/README.md) |
| [tools](tools/) | 仓库级检查工具 | [工具导航](tools/README.md) |

各模块的 `docs/` 存使用及设计说明，`docs/archive/` 存明确标注的历史资料；`tests/` 存测试，部署和构建工具保留在各模块原有目录。模型和固件依赖随所属模块维护，避免跨目录导入或工具工程路径变化。新增资料按用途归位，完整约定见 [贡献指南](CONTRIBUTING.md#文件与数据)。

现有日期目录、演示视频、阶段报告、运行环境、个人配置、实采记录和密钥不纳入 Git。它们保留在原电脑；新成员克隆仓库后不会得到这些文件。需要共享的接线图或报告经确认后可放入 `docs/`。

## 开发环境

桌面开发建议 Python 3.12、Node.js 22 与 Git。树莓派 ARM32 的安装方式单独遵循终端 README，不复制 Windows 虚拟环境。

在 PowerShell 中，从仓库根目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r "树莓派心电终端/requirements-pi.txt" -r "心电云端平台/requirements-test.txt" -r "心电云端平台/requirements-model.txt"
.\.venv\Scripts\python.exe tools/run_checks.py
```

不需要激活虚拟环境，因此不依赖 PowerShell 脚本执行策略。Node.js 仅用于网页脚本测试。Python Tk 界面测试需要可用的显示环境，缺少显示时部分测试会跳过；应在 PR 中记录跳过原因。

STM32 使用现有 Keil 工程：ARM Compiler 5.06 update 7（build 960）、Keil.STM32F1xx_DFP 2.3.0。具体参数以工程文件为准。固件编译与板上串口联调单独验收，不由 Python 测试代替。

## 版本与部署

**所有协作者均可修改所有模块，没有按人员或目录划分的写入限制。** 开工前在 Issue 声明目标、预计修改路径和验收条件，协调重叠修改；每项任务使用独立分支和工作目录。PR 通过检查、同步最新 main、解决审查讨论后，由仓库所有者 XiongBoT 最终审核并合并，不要求其他成员批准。流程见 [贡献指南](CONTRIBUTING.md) 和 [协作质量与发布](docs/协作质量与发布.md)。

`main` 为共同集成分支；每个任务从最新 `main` 建立 `feat/...`、`fix/...` 或 `docs/...` 分支。各组件的已合并、已发布和待验收状态统一见[版本与交付状态](docs/版本与交付状态.md)，源码合并不会自动部署到树莓派或公网。发布时记录提交编号、设备、验证结果和回退版本。

当前模型、第三方库和公开验证数据沿用各自许可证。保留其 LICENSE 与来源说明；仓库未为整个项目额外授予开源许可证。分类结果用于课程研究，不将软件测试结果表述为临床有效性验证。

