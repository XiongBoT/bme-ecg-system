# 部署与打包工具

[云端首页](../README.md) · [云端文档](../docs/README.md) · [版本与发布流程](../../docs/协作质量与发布.md)

当前服务器采用[统一部署](../../docs/统一部署.md)，同一提交交付心电云端、心伴后端及生产前端。再按[部署与升级](../docs/部署与升级.md)选择终端或客户端构建目标。当前功能和实际安装包分别核对[交付状态](../../docs/版本与交付状态.md)；本目录保留的旧安装流程有各自适用范围。

## 按目标查阅

| 目标 | 说明 | 主要文件 |
| --- | --- | --- |
| 当前统一服务器 | [统一部署](../../docs/统一部署.md) | [统一打包](../../tools/package_system_release.py) |
| 仅心电 Linux 服务 | [独立初装说明](linux/部署说明.txt) | [linux/](linux/)、[单模块源码打包](package_cloud.py) |
| 手机公网 HTTPS | [手机公网访问](linux/手机公网访问说明.txt) | [公开入口配置](prepare_public.py) |
| Windows 免安装客户端 | [使用与构建](desktop/README.md)、[用户说明](desktop/使用说明.txt) | [桌面打包](package_desktop.py)、[启动器](desktop/Launcher.cs) |
| Android 客户端 | [安卓工程说明](../android/README.md) | [android/](../android/) |

## 升级与维护脚本

| 文件 | 用途 |
| --- | --- |
| [create_bootstrap.py](create_bootstrap.py) | 引导安装包生成 |
| [create_app_update.py](create_app_update.py) | 应用更新包生成 |
| [create_model_update.py](create_model_update.py) | 模型更新包生成 |
| [linux/update_desktop.py](linux/update_desktop.py) | 服务器端桌面包更新 |
| [build_app_icons.py](build_app_icons.py) | 应用图标生成 |
| [prepare_historical_relay.py](prepare_historical_relay.py) | 历史中转流程准备 |

运行目录、参数与先决条件以对应说明和脚本为准；不要仅因文件位于此目录就从此目录启动。构建产物不提交 Git，下载包通过 Releases 分发。合并源码与实际部署分别记录，操作正式服务器或设备须在当前任务授权范围内。
