# 公开数据评估报告

[算法与评估](../算法与评估.md) · [文档中心](../README.md) · [复跑工具](../../心电云端平台/research/README.md)

这里保存公开数据库离线评估的报告快照。最新一轮使用完整记录比较三种 QRS，并独立测量当前分类模型；早期 50 分钟报告保留原范围与版本，不覆盖旧证据。

| 文件 | 用途 |
| --- | --- |
| [分类误差诊断.md](分类误差诊断.md) | 2026-11-26：基于已有固定模型汇总的 S 类混淆、未输出、误报、逐记录贡献及性能口径 |
| [classification-diagnostics.json](classification-diagnostics.json) | 诊断计数、两路径类别指标、逐记录性能与生成证据摘要 |
| [算法对比与分类评测.md](算法对比与分类评测.md) | 2026-11-24：QRS 44 条全长（22.07 小时）、分类 21 条全长（10.53 小时），逐记录及各类别结果 |
| [qrs-comparison.json](qrs-comparison.json) | 三种 QRS 的 150/50 ms 匹配结果、输入/代码摘要与耗时 |
| [classification-benchmark.json](classification-benchmark.json) | 实际分类链路与参考 R 点诊断对照、混淆矩阵、拒绝及覆盖情况 |
| [结果摘要.md](结果摘要.md) | GitHub 可直接阅读的 QRS/RR 数值摘要，从 JSON 自动生成 |
| [report.html](report.html) | 供人阅读的结果；下载后用浏览器打开，GitHub 文件页显示 HTML 源码 |
| [report.json](report.json) | 结构化结果、配置、输入和代码摘要，便于核对与比较 |

最新结果：150 ms 下现有 QRS / XQRS / FastNVG 的 F1 分别为 **99.27% / 99.21% / 99.13%**。分类完整链路宏平均 F1 **66.44%**，S 类 F1 **23.85%**、召回率 **16.84%**；参考 R 对照宏平均 F1 **68.58%**。这些是不同层级的指标，不能把 QRS F1 当作分类准确率。维持当前默认 QRS，后续优先研究分类输入处理和 S 类能力；XQRS 的漏检更少但误检更多，仍可保留为离线复核候选。

早期 `report.html/report.json/结果摘要.md` 配置：MIT-BIH 记录 `100 101 103 105 200 201 207 208 231 232`，每条前 300 秒，共 50 分钟，通道 0。最新完整记录报告按名称选择 MLII、采用固定整数 ADC 映射，范围和处理口径与早期报告不同，不能把两者差值称为算法升级幅度。

报告是指定公开记录的离线结果，不代表完整数据库、实物设备或临床验证，也不代表云端已部署在线 HRV 功能。替换报告时应同时更新 HTML 与 JSON，运行 `python tools/sync_docs.py --write` 同步摘要，并在 PR 中说明数据、配置和版本变化；原始数据库文件不加入仓库。

上段替换步骤仅适用于早期 HTML 报告。最新两份 JSON 更新后，用 `research.render_benchmark` 重新生成 Markdown；CI 通过 `--check` 防止文档和数值脱节，命令见[研究工具](../../心电云端平台/research/README.md#三种-qrs-与当前分类模型统一评测)。
