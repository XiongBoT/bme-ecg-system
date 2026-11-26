# HeartLife 视觉素材与授权登记台账 (UI Assets Registry)

> 遵循 `HeartLife_UI_Redesign_PRD.md` 第 10 节：严禁热链外部图片、严禁使用真人照片冒充患者头像或临床案例、严禁内嵌 `<script>` 或事件处理器。

## 1. 本地实际启用矢量插画与图标资产

| 资产 ID | 本地路径 | 来源与作者 | 许可类型 | 用途 | 安全与合规核验 |
|---|---|---|---|---|---|
| `HL-IL-01` | `frontend/src/assets/heartlife/illustrations/welcome-companion.svg` | HeartLife 项目内原创绘制 | 项目自有（CC0 等效） | 首页晨间问候卡装饰配图（`alt=""`） | 纯几何 SVG，无 `<script>`、无外链、不代表临床结论 |
| `HL-IL-02` | `frontend/src/assets/heartlife/illustrations/community-empty.svg` | HeartLife 项目内原创绘制 | 项目自有（CC0 等效） | 同伴社区空列表状态温暖对话插画 | 纯几何 SVG，无 `<script>`、无外链 |
| `HL-IL-03` | `frontend/src/assets/heartlife/illustrations/journal-calm.svg` | HeartLife 项目内原创绘制 | 项目自有（CC0 等效） | 健康日记未记录日与习惯计划空状态装饰图 | 纯几何 SVG，无 `<script>`、无外链 |
| `HL-IL-04` | `frontend/src/assets/heartlife/illustrations/article-cover-heart.svg` | HeartLife 项目内原创绘制 | 项目自有（CC0 等效） | 百科「心脏基础 / 设备解读 / 就医沟通」16:9 封面与断图兜底 | 纯几何 SVG，无临床诊断暗示 |
| `HL-IL-05` | `frontend/src/assets/heartlife/illustrations/article-cover-sleep.svg` | HeartLife 项目内原创绘制 | 项目自有（CC0 等效） | 百科「睡眠与休息」分类 16:9 封面 | 纯几何 SVG，无外链 |
| `HL-IL-06` | `frontend/src/assets/heartlife/illustrations/article-cover-walk.svg` | HeartLife 项目内原创绘制 | 项目自有（CC0 等效） | 百科「运动与习惯 / 日常健康」分类 16:9 封面 | 纯几何 SVG，无外链 |
| `HL-IC-01` | `lucide-vue-next`（npm 锁定包） | Lucide Contributors (`https://lucide.dev/license`) | ISC License | 全站 24px 线性语义图标（均配中文可见标签或 `aria-label`） | 本地打包，运行时零 CDN 请求 |

## 2. 外部真人摄影素材处理说明（PRD §10.1）

- PRD §10.1 所列 Pexels 生活方式摄影（`HL-PH-01` ~ `HL-PH-04`）在本轮评估中遵循第 10.1 节合规建议（「若对医疗产品中的使用权限有疑问，优先改用 Open Peeps 或自行授权的非人物素材；不要暗示照片人物患病或使用过 HeartLife」），登记为 **未使用真人肖像，统一采用上述本地原创温暖草木绿/暖陶橙主题矢量插画**，彻底杜绝医疗场景肖像权风险及外网加载失败隐患。
- 社区成员头像统一由 `HlAvatar.vue` 基于真实用户昵称首字在本地确定性生成温暖配色圆角头像，不使用任何真人照片。
