# 旧项目基线与隔离观察记录 (Legacy Observations)

## TASK-00 执行前原仓库只读快照

- **核查时间**：2026-11-26T11:50+08:00
- **原仓库路径**：`c:\Users\NickHu\Desktop\bme\bme-ecg-system`
- **Git 分支**：`main`（与 `origin/main` 同步）
- **Git HEAD SHA**：`91ad66e1ace19c213035ad92276ae5a56670a685`
- **工作区状态**：`nothing to commit, working tree clean`（无未提交改动）
- **隔离方式**：在原仓库同级目录 `c:\Users\NickHu\Desktop\bme\heartlife` 初始化全新独立 Git 仓库与独立 Python `.venv`、独立 `frontend/node_modules` 及独立 SQLite 数据库，未对 `bme-ecg-system` 执行任何写入、依赖安装或服务调用。

## 观察说明

- 原仓库包含 `硬件/STM32心电采集`、`树莓派心电终端`、`心电云端平台`、`docs`、`tools`，根目录 `.gitignore` 采用白名单机制。
- 将 `heartlife` 置于原仓库之外的同级独立目录，天然满足「零改动原仓库代码、配置、数据库与构建脚本」的最高隔离门禁。
