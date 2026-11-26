# HeartLife 5–7 分钟课程演示指引 (Demo Script)

## 启动准备（完全无需原 ECG 服务或外部密钥）

```powershell
cd c:\Users\NickHu\Desktop\bme\heartlife
$env:DEMO_MODE="1"
$env:APP_ENV="local"
.\.venv\Scripts\python.exe scripts/seed_demo.py
```

分别启动后端（默认 `8010`）与前端（默认 `5174`）：

```powershell
# 终端 1：后端
cd c:\Users\NickHu\Desktop\bme\heartlife\backend
$env:DEMO_MODE="1"
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010

# 终端 2：前端
cd c:\Users\NickHu\Desktop\bme\heartlife\frontend
npm run dev
```

内置合成演示账号（仅本地 `DEMO_MODE=1` 生成，均带「演示」标识，密码统一为 `DemoPass123!`）：
- 普通成员 A：`demo_alice`
- 普通成员 B：`demo_bob`
- 社区审核员：`demo_mod`
- 科普编辑：`demo_editor`

## 演示步骤

1. **独立架构开场（30s）**：确认原 `bme-ecg-system` 服务未启动，打开 `http://localhost:5174` 展示 HeartLife 独立运行。
2. **日常记录与打卡闭环（90s）**：使用 `demo_alice` 登录，在居中首页查看今日计划进度，点击「记录今日」填写睡眠、活动与心情，返回计划页完成今日打卡并刷新页面验证持久化。
3. **多人健康社区交互（90s）**：`demo_alice` 发布一条作息分享帖；在无痕窗口登录 `demo_bob` 对该帖点赞、收藏并发表评论；切回 `demo_alice` 查看右上角站内消息提醒。
4. **百科溯源与社区治理（60s）**：浏览「百科」文章底部的权威参考来源与「课程内容审核」记录；演示 `demo_bob` 举报不当建议帖后，登录 `demo_mod` 在「运营」页隐藏该帖，验证普通用户列表与详情均不再可见。
5. **健康周报与隐私边界（60s）**：进入「周报」查看睡眠均值、打卡完成率、缺失值说明及趋势图，点击打印预览验证默认隐藏私密备注；在「我的」演示个人 JSON 导出说明。
6. **行为挑战与可选扩展（30s）**：展示「挑战」页的 7 日规律睡眠与科普共读进度，说明非诊疗定位与研究局限性。
