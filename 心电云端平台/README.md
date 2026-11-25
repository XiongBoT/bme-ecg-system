# 心电云端与工作台

接收树莓派记录，按账号与设备管理数据，提供波形回看及后台分析。手机和电脑共用网页；Windows 启动器在 `deploy/desktop/`。

[项目首页](../README.md) · [系统架构](../docs/系统架构.md) · [文档分类](docs/README.md) · [源码地图](../docs/仓库导览.md) · [算法入口](../docs/算法与评估.md)

## 使用与开发入口

- [心电健康助手 1.1.0](../docs/心电健康助手.md) — 账号申请与审核、登录记忆、趋势、1／3／5 分钟测量、设置和设备详情；已合入主分支；公开下载、部署和实机验收分别见交付状态。

- [管理员指南](../docs/管理员指南.md) — 入口、申请审核、设备开通、账号操作与维护。
- [任务中心与人工复核](docs/使用说明.md#统一工作流程) — 本人上传/分析进度、默认关闭的自动分析及复核状态。
- [部署与升级](docs/部署与升级.md) — 云端、终端及 APK 的更新顺序与恢复边界。
- [下载电脑端与打开网页](../README.md#应用下载)
- [快速开始](docs/快速开始.md)、[使用说明](docs/使用说明.md)、[故障排查](docs/故障排查.md)；[离线文本](README.txt) 自动生成，原文快照在历史目录。
- [统一管理后台](docs/使用说明.md#统一管理后台源码已实现待部署) — 运行总览、账号详情、设备查询及单账号授权，贯通记录与维护；本次已完成服务与网页部署，实体设备验收待补。
- [管理员账号管理](docs/使用说明.md#管理员账号管理待部署) — 搜索、筛选、创建、重置密码、停用/恢复及撤销登录；服务与网页已部署，旧APK内置页面需另行更新。
- [数据库管理](docs/使用说明.md#数据库管理源码已实现待部署) — 存储概况、记录整理、完整性检查与服务器本地备份；服务与网页已部署，服务器本地备份创建已验证。
- [片段标注与每日备份](docs/使用说明.md#片段标注本地完成待部署) — 本地完成，待审核部署；计划默认关闭。
- [版本与交付状态](../docs/版本与交付状态.md) — 当前源码、下载、部署与待验收项；[阶段记录](docs/云端工作台迭代.md)保留历史设计和测试证据。
- [手机使用流程](docs/使用说明.md#手机使用流程) — 健康助手延续“记录、设备、我的”，包含报告预览与帮助；公开 APK 与源码版本分别登记。
- [Windows 客户端构建](deploy/desktop/README.md)、[Linux 部署](deploy/linux/部署说明.txt)、[手机 HTTPS 访问](deploy/linux/手机公网访问说明.txt)
- [Android 试用版下载与验收边界](../docs/手机端与安卓安装包.md)、[Android 工程与构建](android/README.md)
- 历史流程复现：[2026-10-29 笔记本中转](docs/自动连接说明.txt)、[2026-10-28 开发板演示](docs/开发板上传演示说明.txt)。新账号登录使用根 README 的 HTTPS 入口。

## 目录与职责

| 位置 | 职责 |
| --- | --- |
| [server.py](server.py)、[run_server.py](run_server.py) | 服务端与启动入口 |
| `*_store.py`、[device_routes.py](device_routes.py)、[analysis_tasks.py](analysis_tasks.py) | 账号、设备、记录与持久分析任务 |
| [database_management.py](database_management.py)、[database_backup.py](database_backup.py)、[maintenance_tasks.py](maintenance_tasks.py) | 管理元信息、服务器本地备份及独立维护任务 |
| [admin_console.py](admin_console.py) | 管理总览、账号与设备分页元信息及单项授权 |
| [account_applications.py](account_applications.py)、[health_routes.py](health_routes.py) | 账号申请、日/月/年趋势与远程固定时长测量 |
| [workflow_store.py](workflow_store.py)、[workflow_routes.py](workflow_routes.py) | 自动分析意图、任务中心、人工复核与运行总览 |
| [web/](web/) | 手机/电脑网页、PWA、波形与操作界面 |
| [android/](android/README.md) | Android 试用客户端、资源与构建工具 |
| [cloud_model/](cloud_model/README.md) | 云端模型适配器及固定版本依赖；[来源](cloud_model/SOURCE.json) |
| [physiology_analysis.py](physiology_analysis.py) | 独立 QRS/RR 后台分析、结果版本与输入门控 |
| [research/](research/README.md) | 离线评估；其中检测与统计两个纯函数模块供云端复用 |
| [deploy/](deploy/README.md) | 按目标查找云端、Windows 打包和升级工具 |
| [tests/](tests/) | Python、网页脚本与 Windows 启动器检查 |
| [docs/](docs/README.md) | 使用、部署进度与历史流程分类 |
| [docs/archive/](docs/archive/README.md) | 历史技术方案、阶段验证 |

根目录 `.cmd`、`.ps1`、连接及验证脚本按[辅助工具索引](tools/README.md)分类查阅，保留原运行路径。`requirements*.txt` 仍放在模块根目录。测试方式统一见 [贡献指南](../CONTRIBUTING.md#检查与实物联调)。

`work/`、`outputs/`、`deploy/dist/`、`.cloud_private/` 和采集数据属于本地运行内容，不加入 Git；下载包通过 Release 或正式网页分发。

## QRS/RR 分析

安装 `requirements-model.txt` 后即可运行 QRS/RR，不要求启用分类模型。记录上传完成后，在手机或电脑的“心搏与间期（QRS / RR）”面板点击分析；后台排队并保存结果，退出页面不影响已接受的任务。页面显示 R 峰数、平均 RR、换算心率、质量门控比例、有效时长/点数、排除原因及 RR 变异性。没有可靠正常窦性间期标记时，HRV 明确显示不可用。

单记录上限 100 万采样点（360 Hz 时约 46 分钟）；模拟、模式不明或质量不足的记录可能没有可用结果。原始记录和分类结果分别保留。接口及升级/回退边界见 [接口约定](../docs/接口约定.md#独立-qrsrr-分析2026-11-24待部署)。服务与页面版本须配套，实际交付以[统一状态页](../docs/版本与交付状态.md)为准。
