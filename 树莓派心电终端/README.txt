由 tools/sync_docs.py 从本模块 docs/ 下的快速开始、使用说明、故障排查生成。
请修改 Markdown 原文后重新生成，不单独编辑本文件。
本文说明完整仓库当前代码；早期精简发布包不一定包含全部功能。

# 树莓派快速开始

终端导航（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/README.md） · 使用说明（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/使用说明.md） · 故障排查（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/故障排查.md）

本文说明仓库当前代码的安装与启动。板上是否已安装相同版本，先查交付状态（https://github.com/XiongBoT/bme-ecg-system/blob/main/docs/版本与交付状态.md）并核对设备实际版本；设备阶段记录（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/设备待机与日常使用.md）保留历史证据；本轮文档整理不部署设备。

## 安装依赖

Raspberry Pi 2 使用 Raspberry Pi OS 的 ARM32 软件包。在树莓派执行：

```sh
sudo apt update
sudo apt install python3-numpy python3-scipy python3-serial python3-tk python3-reportlab fonts-wqy-microhei
python3 -c "import numpy, scipy, serial, tkinter, reportlab; print('dependencies OK')"
```

Lite 系统若没有图形环境，还需安装 `xserver-xorg xserver-xorg-legacy xinit openbox x11-xserver-utils`。应用由普通用户运行，依赖导入成功不代表图形会话已可用。

采用 apt 路线无需再对系统 Python 执行 pip。需要隔离环境时，先安装 `python3-venv`，再用 `python3 -m venv --system-site-packages .venv`，通过 `ECG_PYTHON` 指定环境中的解释器。不要复制 Windows 虚拟环境。

## 在本地屏幕启动

以下路径是现有部署示例，换机器后替换为实际目录。在树莓派所接屏幕的本地终端执行：

```sh
sh "/home/pi2/树莓派心电终端/start-device.sh"
```

进入待机后点击“开始采集”，确认使用者、串口、存储和云端状态。自动识别串口不会自动开始记录。多个 USB 串口必须人工选择。

未接硬件时，可运行明确标记的合成演示：

```sh
sh "/home/pi2/树莓派心电终端/start-demo.sh" --duration 180 --fullscreen
```

没有本地图形会话的 SSH 连接用于编辑、查看日志及无界面检查。短时模拟示例：

```sh
python3 app.py --headless --demo --duration 10 --summary evidence/demo-10s-summary.json
```

这条相对路径命令从终端模块根目录执行。模拟输出保留在本机，不作为实物采集证据。

## 接入串口

从终端模块根目录运行 `python3 app.py --list-ports`，优先选择 `/dev/serial/by-id/` 稳定路径。当前固件使用七字节帧、115200、8N1、360 Hz；接线和格式见 STM32 串口对接（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/STM32串口对接说明.txt）。

若账号没有串口权限，按实际用户名加入 `dialout` 组后重新登录。`--port auto` 仅在存在唯一 USB 串口时选择它。

## 接入云端和手机

按账号与记录归属（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/云端账号与记录归属.txt）配置 HTTPS 地址及本设备凭据，管理员分配使用者授权。手机登录同一平台的本人账号。当前终端支持手动和 1／3／5 分钟；手机发起测量还要求云端提供健康助手接口、终端空闲且真实串口就绪，见手机测量步骤（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/使用说明.md#手机发起固定时长测量）。

## 升级与开发

当前完整工作台包由 `python tools/package_cloud_workspace.py` 构建，输出 `dist/ecg-cloud-workspace.tar.gz`。构建不安装、不部署；历史 `build_cardioedge_release.py` 和固定哈希安装工具不用于当前完整工作台升级。

板上文件比对、备份、开机配置与回退方法见设备说明（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/设备待机与日常使用.md#启动与部署准备）。电脑开发和分模块测试见贡献指南（https://github.com/XiongBoT/bme-ecg-system/blob/main/CONTRIBUTING.md#检查与实物联调）。

# 树莓派使用说明

快速开始（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/快速开始.md） · 故障排查（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/故障排查.md） · 文档分类（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/README.md）

## 完成一次测量

1. 在待机界面接入 USB 串口；多个设备时明确选择采集端口。
2. 点击“开始采集”，核对使用者、端口、可用空间和云端状态，选择手动结束、1 分钟、3 分钟或 5 分钟。取消准备窗口不会建立记录。
3. 观察接收点数、信号质量与保存状态。“暂停显示”只冻结画面，采集和保存继续。
4. 点击“停止并保存”，或等待所选时长结束；等到保存完成后查看测量总结。
5. 在历史记录中复核、导出 CSV/ZIP 或中文 PDF；确认云端授权后可以手动上传并查看分析。

设备待机、总结和安全关机的详细行为及待验收项见设备待机与日常使用（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/设备待机与日常使用.md#日常使用）。源码具备相应功能不代表板端已经升级。

## 手机发起固定时长测量

云端和终端均更新后，终端联网并保持真实串口模式的空闲状态；管理员先给本人账号分配设备。手机“开始测量”选择就绪设备与 1／3／5 分钟，确认人在设备旁、电极已准备，再发起请求。

终端领取请求后计时、保存和上传。手机断网或关闭页面不会停止已开始的测量；提前结束使用终端停止按钮。45 秒未领取的请求过期，终端重启不自动重复采集。上传失败保留本地记录，排除问题后在终端补传。

测量总结中的采样时长按实际保存点数计算；选了 3 分钟但提前停止或发生断流，不能把报告视作完整 3 分钟数据。详情与报告见健康助手（https://github.com/XiongBoT/bme-ecg-system/blob/main/docs/心电健康助手.md）。

## 来源、波形与分类

“更多 → 数据来源”可选择合成模拟或文件回放；来源标签必须保留。串口的 MODE=0 表示实采来源，MODE=1 表示板端模拟。协议有效不等于信号有效。

当前主分类模型位于 cardioedge/（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/cardioedge/README.md），输出 N/S/V；旧 models/（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/models/README.md） 是历史原型。分类需要有效信号及前后心搏上下文，初次输出有延迟。模型分数不是诊断概率，N 类也不等于完全正常，S 类需结合波形复核。

显示电压按 ADC 与参考电压换算，不直接代表皮肤心电幅度。处理后波形用于显示对照，原始 ADC 和接收字节继续保存。具体规则见实采预处理（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/实采预处理说明.txt）、状态与信号质量（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/状态与信号质量说明.txt）、分类呈现（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/分类呈现与复核说明.txt）。

## 记录、导出与云端

默认记录位于模块内 `data/sessions/<session_id>/`；可用 `--data-dir` 指定其他可写目录。会话包括原始块、SQLite 索引、事件与质量摘要，历史导出读取完整已提交数据。

测量总结中的有效采样比例、质量通过时间和有效 RR 心率各有不同含义；缺失统计显示未知。PDF 使用本地保存的结果，不能据此判断云端分析完成。数据管理详见记录与设置（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/数据管理与设置说明.txt）。

云端支持当前 HTTPS 平台和账号/设备授权。手机使用记录所属账号登录；未分配记录由管理员处理归属。具体接入见账号与记录归属（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/云端账号与记录归属.txt），跨模块约定见共同接口（https://github.com/XiongBoT/bme-ecg-system/blob/main/docs/接口约定.md）。

## 退出与关机

先停止并等待保存完成。界面“安全关机”会确认并等待后台任务；保存失败或权限不足时不自动关机。笔记本预览不会执行树莓派关机。

开机待机配置由独立工具管理，安装、撤销与实物验收步骤见设备说明（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/设备待机与日常使用.md#查看与撤销开机配置）。

# 树莓派故障排查

快速开始（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/快速开始.md） · 使用说明（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/使用说明.md） · 诊断工具分类（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/tools/README.md）

| 现象 | 检查顺序 |
| --- | --- |
| SSH 启动后没有本地窗口 | 图形启动脚本应在树莓派物理控制台或本地图形会话运行；SSH 使用无界面模式检查链路，不用 `sudo` 或强设 `DISPLAY=:0` 绕过会话权限 |
| 模块导入失败 | 按快速开始检查 NumPy、SciPy、pyserial、Tk 和 ReportLab；确认实际解释器，检查 `ECG_PYTHON` 是否指向预期环境 |
| 串口不存在或被拒绝访问 | 运行 `python3 app.py --list-ports`；核对 USB-TTL、稳定设备路径、`dialout` 权限及是否已有进程占用 |
| 多个 USB 串口无法自动开始 | 在界面明确选择端口；`auto` 不会猜测正确设备 |
| 收到字节但没有有效点 | 核对七字节固件、115200/8N1、共地与 RX 接线；检查帧头、MODE 和 SUM8；旧三字节协议不兼容 |
| 显示无效、平直、饱和或没有分类 | 先查原始信号、导联和来源；无效 ADC、板端模拟、上下文不足或质量不通过均可能暂停分析 |
| PDF 提示缺少中文字体 | 安装 `python3-reportlab fonts-wqy-microhei`，或将 `ECG_REPORT_FONT` 指向有效中文字体文件 |
| 空间不足或保存失败 | 查看存储状态，停止后检查数据目录权限；导出并确认备份后再人工管理记录，不删除原始目录来消除提示 |
| 上传后手机看不到记录 | 确认上传完成、设备授权、记录归属及登录账号；源记录保存成功不代表云端已收到或分析完成 |

## 手机发起测量

| 现象 | 检查顺序 |
| --- | --- |
| 手机找不到设备或显示未就绪 | 检查本人设备授权、独立凭据、云端地址、终端版本；终端应联网空闲并选择真实串口，近 35 秒有心跳 |
| 请求过期，没有开始采集 | 请求 45 秒未领取即过期；修复终端连接后重新发起，不重放旧请求 |
| 手机关闭后仍在采集 | 计时由终端执行；在终端停止并等待保存 |
| 重启后提示采集中断 | 为避免重复测量不会自动重启采集；先检查本地记录与保存结果，再重新发起 |
| 上传失败，手机没有报告 | 本地记录保留；核对账号、凭据和网络后在终端重试上传，不修改旧记录归属 |

更多状态见健康助手说明（https://github.com/XiongBoT/bme-ecg-system/blob/main/docs/心电健康助手.md）和云端排查（https://github.com/XiongBoT/bme-ecg-system/blob/main/心电云端平台/docs/故障排查.md）。

## HDMI 黑屏

现有 `start-screen.sh` 只在自己创建的 X 会话内检查已启用输出的全零 CTM，按原实现修复；正常矩阵与已有桌面不修改。屏幕截图正常不能替代物理 HDMI 检查。

需要临时指定兼容模式时，在物理文字控制台执行：

```sh
ECG_SCREEN_MODE=1024x768 ECG_SCREEN_RATE=60 sh "/home/pi2/树莓派心电终端/start-demo.sh" --fullscreen
```

默认不强制分辨率或刷新率；模式不支持时脚本会报错停止。历史定位过程保留在 README 原文快照（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/docs/archive/README_20261123.txt），不能据历史结果确认新设备已验证。

## 收集问题信息

记录运行版本、操作步骤、错误消息、数据来源和是否使用实体硬件。工具的前置条件与副作用见工具索引（https://github.com/XiongBoT/bme-ecg-system/blob/main/树莓派心电终端/tools/README.md）。真实心电、数据库、设备凭据及私钥不提交 Git，也不附在公开 Issue 中。
