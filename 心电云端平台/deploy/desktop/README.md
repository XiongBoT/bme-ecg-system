# Windows 免安装桌面入口

最新公开试用：[Windows 1.2.0 及校验文件](https://github.com/XiongBoT/bme-ecg-system/releases/tag/desktop-v1.2.0)，构建自 `87f23ba`，包含连接助手与更新提醒。ZIP 为 23,601 字节，5 项白名单和内部摘要验证通过，公开下载 SHA-256 与本地一致。旧稳定版 [1.1.0](https://github.com/XiongBoT/bme-ecg-system/releases/tag/desktop-v1.1.0) 保留；[云端固定下载入口](https://62.234.150.104/downloads/ecg-workspace-windows.zip) 未随此次 GitHub 发布更新，获取新版请使用本页 Release。

用途：将当前正式云端 https://62.234.150.104/ 打包为可解压运行的 Windows 启动入口，使用既有账号。无需安装 Python、Node.js；不包含离线服务、记录、凭据或尚未上线的设计稿。

实施与验收：

1. 编译无控制台 C# 启动程序，连接助手以公开首页 GET 检查连接，约 6 秒超时，允许重试和手动打开。优先 Edge、其次 Chrome 独立窗口，再回退默认浏览器。固定 HTTPS 地址，不读本地密码、不变更浏览器安全策略。
2. 仅打包启动程序、连接助手 CMD、备用 URL、说明、SHA256 清单，共 5 个文件；源码留在本目录，生成包进入 `deploy/dist/desktop/`。快捷方式仅在用户点击后创建，不覆盖已有同名文件。
3. 验证中文和带空格路径构建/解压、归档清单和摘要；覆盖连接结果、关闭取消、重复检查和多屏窗口边界。实际窗口及其他 Windows 电脑的检查结果单独记录，不用编译测试替代。
4. 启动时并行检查公开 `/api/updates`，按本机用户最多每 24 小时自动检查一次；连接助手提供“检查更新”绕过间隔。只在发布版本高于 EXE 的 `AssemblyVersion` 时提醒，用户选择“查看新版”后才打开固定仓库的官方 Release 页面；“稍后”继续使用当前版本。没有下载、安装、强制更新或新增自启动行为。

构建（Windows 开发环境，Python 3.10+ / .NET Framework 4.x 编译器）：

```powershell
python deploy/package_desktop.py
python -m unittest discover -s tests -p test_desktop_package.py -v
```

以上命令从 `心电云端平台/` 模块根目录执行。此处 Python 仅用于开发打包，不是使用者运行条件。输出 EXE 为 AnyCPU，尚未进行代码签名；不使用安装器、管理员权限、计划任务或自启动。工作台页面随服务器部署更新，启动器自身需要重新构建发布；启动地址变化也需重新构建。更新提醒已随 PR #53 合并并纳入 1.2.0 试用包，服务端代码及清单已统一部署，客户端提醒仍待实测；旧公开包不会因网页刷新获得检查器。

用户操作见 [使用说明](使用说明.txt)：完整解压后双击“心电工作台.exe”，连接成功自动打开云端，使用现有账号登录。更新检查不延迟工作台打开；连接助手可能在后台保留数秒，检查结束后退出，发现新版时显示可跳过的提醒。“连接与快捷方式.cmd”以 `--connection` 打开并保留连接助手，可重试、检查更新或创建桌面快捷方式。遇到启动限制可使用包内浏览器备用入口。需联网；当前包不是离线分析软件。

`Launcher.cs` 负责窗口及浏览器/快捷方式交互，`LauncherCore.cs` 负责可独立测试的连接与窗口边界逻辑，`UpdateCore.cs` 负责更新元数据、请求与本机检查间隔。三者一并编译，JSON 解析使用 .NET Framework 自带的 `System.Web.Extensions`。本次沿用主分支已发布的电脑网页，保留记录栏、波形窗口/幅度调整、心搏筛选定位、专注查看、连接提示和下载入口。构建启动包不会自动部署网页。

更新检查固定使用 `https://62.234.150.104/api/updates`，不发送账号、Cookie 或设备信息，不跟随重定向，保留正常 TLS 证书验证；请求含正文约 6 秒截止、最多 16 KiB。仅接受 schema 1、有效数字版本及对应 `https://github.com/XiongBoT/bme-ecg-system/releases/tag/desktop-v<version>`，说明按纯文本显示并限制长度。`windows: null` 表示暂未提供信息，不提示“已是最新”；自动失败安静结束，手动失败明确提示“暂时无法检查”。关闭连接助手会取消检查并拒绝晚到结果。

本机仅在 `%LOCALAPPDATA%\BmeEcgWorkspace\update-check.txt` 保存非敏感的上次检查时间，失败也计入自动检查间隔；手动检查始终可用。系统时间回退时重设基准并等待 24 小时，避免重复提醒或永久停查。该文件不在交付 ZIP 中，不含账号或记录。

当前公开试用 EXE 版本为 `1.2.0.0`，对应 `desktop-v1.2.0` Release。更新接口及清单代码已随 `6ac70ff3` 部署，实际客户端提醒与窗口操作仍待验收。后续构建应增加版本、生成对应 `desktop-v<version>` Release 并核验下载包，再更新清单。旧版已安装启动器不会因网页刷新获得本检查功能，需先手动换用包含检查功能的新包。

当前服务器按[统一部署](../../../docs/统一部署.md)维护，2026-11-27 的服务更新未替换 Windows 安装包或服务器固定下载附件。发布新桌面包仍需独立构建、核验和交付；公开下载路由只接受固定文件名，不公开目录、凭据或记录。

历史单模块部署使用 `deploy/package_cloud.py` 与 `deploy/linux/update_desktop.py`，面向其约定的 ubuntu 服务布局；后者会停服、备份并切换程序，不只是复制桌面 ZIP。使用前核对适用目录、服务和数据，不将它直接套用于当前统一部署。

1.0 源码通过 `feat/ecg-desktop-portable` 同步，已发布 1.1.0 通过 `feat/ecg-desktop-workspace-110` 合入；1.2 连接助手使用 `feat/windows-workspace`。构建生成的 ZIP/EXE、记录和凭据不进入 Git。项目进度、验收证据、交付包摘要和后续事项统一见 [云端工作台迭代](../../docs/云端工作台迭代.md) 的“Windows 免安装电脑端”小节。
