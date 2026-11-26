# 离线 ECG 研究工具

[算法与评估](../../docs/算法与评估.md) · [已有报告](../../docs/algorithm-validation/README.md) · [云端首页](../README.md)

## 固定模型误差诊断

新增 [分类误差诊断](../../docs/algorithm-validation/分类误差诊断.md)，使用已有 21 条公开记录的实际链路和参考 R 汇总，分解 S→N/S→V、未匹配输出及 S 误报，并保留逐记录贡献与原性能计时。未重新训练、替换权重或调整默认算法。

从本目录的上一级云端目录执行 `python -m research.classification_diagnostics` 可重新生成报告和 JSON；追加 `--check` 只核对证据是否同步。该工具只需 Python 标准库，不下载数据。CI 同时运行诊断测试和过期检查。未输出的细分原因不能由汇总直接得出，下一步需回看逐拍明细，见报告中的限制和优先记录。

本目录用于公开数据回放与离线评估。`streaming_qrs.py` 与 `physiology.py` 同时供云端独立 QRS/RR 分析复用，随源码包交付；评估脚本、基准工具、WFDB 及公开数据不进入生产部署包。

## 2026-11-24 统一评测协议与验收

目标：完成现有 QRS、XQRS、FastNVG 的同条件比较，并独立评测当前固定 CardioEdgeAI 权重。沿用既有离线研究目录，不修改生产检测器、模型、界面或部署配置。

选择离线对照报告：直接替换生产算法会混淆算法评估与应用改造；只摘录上游指标无法评价本项目的流式输入。因此本轮先建立可复跑证据，再决定后续替换。

评测约定（实现时采用的默认值）：

- QRS 使用 MIT-BIH 1.0.0 的 44 条非起搏记录全长，按名称选择 MLII（包括 114 的第二通道），360 Hz，固定 `2048 + 200 * mV` 四舍五入并限幅为 12 位 ADC。三条路径使用同一量化后的波形，各自保留方法要求的滤波；150 ms 一对一匹配，另报 50 ms 敏感性结果。
- 当前算法按 36 点块复用实际质量门控及检测器；XQRS、FastNVG 作为云端整段离线候选，保留内部学习/滤波。全时段参考心搏均计分，不删除启动、末尾或质量不通过时段；明确离线候选的未来数据可见性，不将处理耗时当作流式确认延迟。
- 分类使用上游 DS2 中排除 202 后的 21 条记录全长。201 和 202 属于同一个人，而 201 在上游训练集合中，因此排除 202。这是已公开且曾被项目用于探索的数据，属于独立重新测量，不宣称全新盲测或外部验证。
- 固定现有权重及输入处理，分别执行原始流式链路和仅以专家 R 位置替换检测器的诊断对照。对照不提供类别标签，不改质量门控、滚动标准化及拒绝规则；它也不是上游整记录标准化分数的复现。
- N/S/V 按上游符号映射；F/Q 等非目标心搏不静默删除，单列被错误分入 N/S/V 的数量；漏检、未输出和误检纳入完整链路指标。匹配心搏上的分类分数与完整链路分数分开，并提供混淆矩阵、类别支持数、覆盖率和拒绝原因。
- 保存输入、代码、权重摘要和环境版本；只交付汇总报告及可复跑代码，原始数据库留在现有外部目录。性能仅代表本机离线运行。

实施与验收：

- [x] 新增 `benchmark_common.py`、`qrs_comparison.py` 及测试：验证同一输入、导联选择、缺失记录/依赖明确失败、匹配边界及无心搏情况；运行三种算法全长比较。
- [x] 新增 `classification_benchmark.py` 及测试：验证患者分组、类别映射、未匹配/非目标心搏与零输出统计、参考 R 对照的接收边界；运行两种分类路径。
- [x] 生成 `docs/algorithm-validation/` 下的比较报告及机器可读汇总，更新导航和进度；核对记录数、分母、摘要、复跑命令，运行受影响回归并独立复核。

验收通过指评测流程与报告可复跑、统计口径清楚，不要求候选算法优于当前算法；本轮不训练、不调参、不自动切换默认算法。

本轮两类完整记录评测均已运行，结果见[统一报告](../../docs/algorithm-validation/算法对比与分类评测.md)。QRS 的 264 组、分类的 84 组逐拍结果重新计分一致；共享输入、门控、代码和权重摘要核对通过。研究专门测试 26 项通过且无跳过；完整工程回归与交付状态统一记在[云端迭代](../docs/云端工作台迭代.md)。

| 文件 | 职责 |
| --- | --- |
| [evaluate_ecg.py](evaluate_ecg.py) | 读取 MIT-BIH 记录、匹配 QRS、计算误差并生成 HTML/JSON |
| [streaming_qrs.py](streaming_qrs.py) | 流式 QRS 检测路径 |
| [physiology.py](physiology.py) | RR/NN 与时域 HRV 研究统计 |
| [研究依赖](../requirements-research.txt) | 离线评估使用的依赖 |
| [研究测试](../tests/test_ecg_research.py) | 软件回归测试 |
| [benchmark_cloud_physiology.py](benchmark_cloud_physiology.py) | 临时合成数据的 3 设备、2 账号本地并发检查 |
| [qrs_comparison.py](qrs_comparison.py) | 现有 QRS、XQRS、FastNVG 同输入、全长对比 |
| [classification_benchmark.py](classification_benchmark.py) | 当前固定模型的实际链路及参考 R 点诊断对照 |
| [benchmark_common.py](benchmark_common.py) | 数据队列、固定 ADC 转换、匹配评分及输入/代码摘要 |
| [render_benchmark.py](render_benchmark.py) | 核对两份报告的共同输入与代码后生成 Markdown |

## 复跑入口

先按 [根 README](../../README.md#开发环境) 创建环境。从 [MIT-BIH 1.0.0](https://physionet.org/content/mitdb/1.0.0/) 取得对应记录的 `.hea`、`.dat`、`.atr` 文件，保留数据许可和来源，放在仓库外。进入 `心电云端平台/` 执行：

```powershell
..\.venv\Scripts\python.exe -m pip install -r requirements-research.txt
..\.venv\Scripts\python.exe -m research.evaluate_ecg --data "D:\datasets\mitdb" --records 100 101 103 105 200 201 207 208 231 232 --seconds 300
```

示例数据路径需要替换为本机位置。输出中的配置、代码及输入摘要用于复核结果。单元测试不需要下载 MIT-BIH 数据；测试入口见 [检查工具](../../tools/README.md)。当前交付及验证状态见 [更新日志](../../CHANGELOG.md)。

## 三种 QRS 与当前分类模型统一评测

在独立研究环境安装 `requirements-research.txt`；新依赖不进入生产依赖或部署包。两个命令顺序运行，减少本机并发计算对计时的干扰；关闭其他高负载程序。PowerShell 示例（从云端目录）：

```powershell
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
..\.venv\Scripts\python.exe -m research.qrs_comparison --data "D:\datasets\mitdb" --output "outputs/qrs-comparison"
..\.venv\Scripts\python.exe -m research.classification_benchmark --data "D:\datasets\mitdb" --output "outputs/classification-benchmark"
..\.venv\Scripts\python.exe -m research.render_benchmark --qrs "outputs/qrs-comparison/qrs-comparison.json" --classification "outputs/classification-benchmark/classification-benchmark.json" --output "outputs/算法对比与分类评测.md"
```

默认读取上述队列的完整记录，数据目录需包含所有 `.hea/.dat/.atr`。`--records 100 --seconds 30` 可用于两入口的快速运行检查，但不能当作全长结果。每次使用新的或空输出目录，已有结果不覆盖；失败时不会悄悄换成另一种算法。

输出包括完整汇总 JSON、`details/` 中的逐拍明细和运行中的 `incomplete.json`。只有最终命名的汇总 JSON 表示全部请求记录已完成；`incomplete.json` 不可作为完成报告。报告生成器检查两条评测的采样率、增益、相同记录的原始文件/ADC 摘要、采样数和共享代码摘要；不接受混合输入或未完成结果。Markdown 中的固定报告链接用于放入仓库报告目录，直接查看临时输出时以命令给出的两个 JSON 为准。

本轮没有上游训练过程重跑；使用模型现有固定权重。参考 R 点对照只替换 R 位置，仍使用本项目的滚动输入和拒绝规则，因此不能拿其准确率直接对齐上游整记录标准化的分类结果。所有参考目标心搏计入完整链路分母；同时提供成功匹配子集上的条件分类指标。被归入 N/S/V 的 F/Q 等非目标心搏、无对应参考的预测分别统计，并计入精确率分母。

研究测试不读取外部数据库：

```powershell
..\.venv\Scripts\python.exe -m unittest discover -s tests -p "*benchmark*.py" -v
```

GitHub 的 `Algorithm evaluation tests` 单独安装研究依赖并执行上述测试；普通云端测试环境没有 WFDB 时，仅跳过明确标注的研究匹配用例，专门检查中不得跳过。当前三种方法不是生产算法选择菜单；切换默认算法属于后续工作。

生成报告后，在 `research.render_benchmark` 的同一命令末尾添加 `--check` 可只读检查 Markdown 是否与 JSON 一致。仓库 CI 已对交付报告启用这一检查；若未同步会失败，不会自动覆盖报告。

从云端模块执行 `python research/benchmark_cloud_physiology.py` 可复跑本地并发基准。需要当前云端测试依赖及 NumPy/SciPy；脚本建立临时账号和三条 60 秒合成记录，完成后清除。它使用本地 TestClient，不包含公网传输、TLS、实体设备或真实心电数据，不能推导服务器并发容量。实际测量结果记录在 [云端工作台迭代](../docs/云端工作台迭代.md)。
