# 心电健康助手 · 安卓安装包

下载入口：[Android 1.0.0 试用版](https://github.com/XiongBoT/bme-ecg-system/releases/tag/android-v1.0.0-preview.1)。最终包 `dist/ecg-records-1.0.0.apk` 为 96,320 字节，APK v2/v3 签名、文件对齐、安装信息和资源清单已通过检查；尚未进行安卓手机实机安装验收。当前仓库公开，平台中的个人记录仍需登录本人账号访问。

应用使用已有项目账号，预设服务器 `https://62.234.150.104/`。界面资源随 APK 安装；账号、设备、心电记录和分析仍由现有服务器提供，需要联网。无需在手机填写服务器地址，也不包含任何预设账号密码。

支持 Android 8.0（API 26）及以上，需要保持 Android System WebView / Chrome 更新。应用不需要相机、定位、麦克风、通讯录或广泛存储权限。下载 CSV 时由系统文件选择器选择保存位置。

## 当前源码与公开下载

公开下载仍为上方 1.0.0 试用版；本轮任务分支 Android manifest 为 1.1.0（4），基于 main `db455604`；手机 PR #36 和数据库 PR #34 均已合并。各端发布与部署以[统一状态页](../../docs/版本与交付状态.md)为准。

已记录的本地 1.0.2 包构建自 `8c25db0`，包含手机优化和此前账号管理，但早于数据库 PR #34。当前 main 已增加数据库管理资源，需重新构建才能纳入；APK 文件名和版本号不能代替源码提交记录。CI 使用临时签名验证构建，不能用于覆盖正式签名安装。

## 生成 APK

需要 Python 3.10+、JDK 17+ 和 Android SDK。先阅读并接受 [Google Android SDK 许可](https://developer.android.com/studio#command-tools)，再使用自动安装脚本；`-AcceptSdkLicense` 表示执行者已确认许可。其他电脑不会自动沿用本机路径或许可确认。

双击 `生成安卓安装包.cmd`，或在普通 PowerShell 执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\setup-and-build.ps1" -AcceptSdkLicense -JdkPath "你的JDK目录"
```

脚本下载官方命令行工具并校验官方 SHA-256，安装 Android 35 与 Build Tools 35.0.0，然后编译、签名、验证 APK。SDK 默认放在 `D:\workspace\bme-android-sdk`；完整组件已安装时直接复用。通过独立的 Python 安装入口传递已批准的许可确认，并检查组件实际存在，避免 Windows PowerShell 管道编码造成误跳过。环境变量仅对该进程有效，不修改系统环境变量或系统执行策略。首次 SDK 下载需要能访问 `dl.google.com`。

Windows 构建中间文件放在 SDK 下的 `app-build` 英文目录，避免 aapt2 无法识别中文目录；可用 `build.py --build-root` 指定其他英文路径。源项目保留在原目录。执行日志位于 `work/setup-build.log` 和 `work/sdk-install.log`。

已有 SDK/JDK 时可直接编译，不联网下载依赖：

```powershell
python build.py --sdk "你的安卓SDK目录" --jdk "你的JDK目录"
```

当前源码输出为 `dist/ecg-records-1.1.0.apk`，内部版本 1.1.0（4），同时生成 SHA-256、签名验证记录和构建信息。只有脚本退出成功且该 APK 存在时，才表示安装包生成完成。1.0.2 已有本地构建记录，尚未发布 GitHub Release；上方下载仍为 1.0.0 试用版。后续构建须记录实际源码提交，不能沿用旧包摘要。界面变化与验证边界见 [日常使用流程](../../docs/手机端与安卓安装包.md#2026-11-24-日常使用流程102本地构建)。

将 APK 传到安卓手机，点击文件并按系统提示允许该文件来源安装。完成后打开“心电健康助手”，用项目账号登录。服务器和设备上传链路需正常运行；应用不承担离线分析或树莓派采集程序的职责。

## 签名与后续更新

首次构建生成项目独立发布密钥，保存在 `work/signing/ecg-release.jks` 与 `work/signing/store-password.txt`。这两个文件必须私下备份，不能上传 GitHub、发给安装用户或放入 APK。后续覆盖安装必须继续使用同一签名密钥，并增加 manifest 的版本编号。现有密钥不完整时脚本会停止，不自动替换。

本包是项目直接分发的 APK，未上架应用商店。编译/签名成功不等同于手机实机验证。

在另一个工作树构建时，可在 `build.py` 命令后加入 `--signing-dir "原签名目录"`，直接读取原签名对，不复制到工作树。显式目录缺少任一文件时停止构建，不生成替代密钥。新克隆没有原私钥，只能生成自己的试验签名，不能覆盖安装项目正式签名版本。

## 心电健康助手 1.1.0

新增登录页账号申请（管理员审核）、记住账号／密码、日／月／年趋势、1／3／5 分钟远程采集、设置与管理员设备详情，操作及部署顺序见[使用说明](../../docs/心电健康助手.md)。保持原包名与原签名；原生保存使用 Android Keystore AES-GCM，仅在成功登录、核对服务器账号后加密持久化，不将密码写入网页存储或 URL。退出保留主动记住的资料，设置中可清除；实体手机上的加密保存与覆盖升级仍待验收。

## 实现与验证

- Java 原生容器 + 随包网页资源，保留统一前端代码，避免手机端与浏览器版独立维护两套业务逻辑。
- 本地资源映射到预设 HTTPS 站点的相同来源；`/api/` 请求沿用服务器 HTTPS、HttpOnly Cookie、账号隔离与 CSRF 校验。
- 不使用 JavaScript 原生对象桥，不接受任意服务器地址；拒绝非预设来源的导航及初始资源请求，不允许 HTTP 明文或忽略 TLS 错误。普通 API 的后续重定向由 WebView 网络实现处理，来源回调不等同于所有重定向链的检查。
- CSV 导出禁止重定向并核对服务端用户标识、当前登录和内容长度。先完整下载到私有临时文件，再写入用户选择的位置；失败尽力删除不完整目标，临时文件用后清理。服务器不提供长度时，能识别网络异常但不能据此证明记录行数完整。
- APK 隐藏 Windows 下载入口。管理员“设备管理”打开固定项目网址的系统浏览器，需在浏览器独立登录后管理及下载凭据；应用不向浏览器传递登录凭据。
- 不自动缓存心电数据，不包含 SDK、样例记录、凭据或模型数据；仅明确列出的网页资源进入 APK。
- 手机交互、账号清空、日期校验、失败重试和导出分派通过 Node 回归测试；地址/路径策略通过 Java 独立测试。
- 1.0.2 导航为“记录、设备、我的”，结果从记录进入。“预览报告”只整理当前已读取的结果和波形片段，标明读取时间、范围与来源；不自动保存或分享。
- 用户在报告预览主动点击打印后，固定 `ecg-report://print` 入口核对来源与手势，读取有效快照，交由禁用脚本、文件访问和网络的独立 WebView 打印。取消或结束后清理该 WebView。浏览器版使用浏览器打印，系统是否提供 PDF 保存需在目标设备验收。
- CSV 完成保存后可主动选择“打开文件”，只向用户选择的文件查看应用授予该文件读取权限；没有查看应用时，已保存文件仍保留在所选位置。
- 需要实机确认：安装/启动、登录与退出、记录筛选与波形、后台再打开、断网重连、修改密码、CSV 保存、覆盖升级。云端尚未部署的接口功能仍取决于对应服务器版本。

官方依据：[WebViewClient](https://developer.android.com/reference/android/webkit/WebViewClient)、[HTML 打印](https://developer.android.com/training/printing/html-docs)、[AAPT2](https://developer.android.com/tools/aapt2)、[命令行构建与签名](https://developer.android.com/build/building-cmdline)。
