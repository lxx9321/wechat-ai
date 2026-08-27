# Direction 2.5 Design Spec

Direction 2.5 是 wechat-ai Web 产品已经批准的最终视觉方向，也是下一阶段 React + Vite 前端实现的唯一视觉基准。

产品定位为“AI 助手 + 未来影视内容发现”。当前真实能力包括文字聊天、图片理解、历史恢复、清空记忆和匿名 Session；未来可以自然扩展 AI 搜剧、短剧搜索、漫剧搜索和自然语言影视推荐，但不得把尚未上线的功能用假数据伪装成真实能力。

视觉目标：深色、高级、电影感、克制、内容型、现代、移动端友好。避免 ChatGPT Clone、后台管理系统、廉价紫色渐变、满屏霓虹、大量玻璃拟态、巨大机器人 Logo、电影放映道具和大量圆角卡片。

## Final Deliverables

### Core screens

1. [Desktop / Empty](./01-desktop-empty.png)
2. [Desktop / Chat + Image](./02-desktop-chat-image.png)
3. [Desktop / Drama Search](./03-desktop-drama-search.png)
4. [Mobile / Empty](./04-mobile-empty.png)
5. [Mobile / Chat + Image](./05-mobile-chat-image.png)
6. [Mobile / Drama Search](./06-mobile-drama-search.png)

### Components and prototype

7. [Composer States](./07-composer-states.png)
8. [Drama Result Card](./08-drama-result-card.png)
9. [Message & System States](./09-message-system-states.png)
10. [Prototype Flow](./10-prototype-flow.png)

桌面 Empty 和 Desktop Drama Search 均为 Design QA 修正后的最终版本。仓库中不保存被替代的旧稿和探索稿。

生成图片用于表达最终视觉、布局和组件意图。开发中的精确颜色、尺寸、响应式规则和交互行为以本文为准；图片中的细小文字若受生成渲染影响，不应覆盖本文中的明确数值。

## Product Structure

### Desktop：双幕结构

- 使用非对称双幕布局：左侧为 AI 交互舞台，右侧为视觉与内容发现舞台。
- 1440px 视口下，左侧约 `560px`，右侧约 `880px`，比例约为 `39% / 61%`。
- 左侧承载提示词、用户输入、AI 文本回复、Markdown 和 Composer。
- 右侧承载图片分析、大图、海报、影视详情和 AI 匹配理由。
- 两个舞台属于同一内容产品，不使用后台式 Sidebar、数据面板或互相割裂的大卡片容器。
- Header 高度为 `64px`。左侧内容横向 padding 为 `40px`，正文阅读宽度约 `480px`。
- 右侧内容 padding 为 `28–32px`。
- 1280px 视口下，左侧约 `496px`，右侧约 `784px`。
- Desktop Empty 右侧保持安静的抽象空间，不放映机、胶片、座椅、机器人或虚构内容结果。

### Mobile：独立单列结构

- Mobile 采用独立的单列沉浸式“字幕剧场”阅读流，不是桌面双幕的机械压缩。
- 视觉内容直接进入消息流：图片使用内容宽度展示，Drama Result 使用竖向列表。
- Header 高度为 `56px`，品牌位于左侧，汉堡菜单位于右侧。
- 390px 视口使用 `20px` 水平边距；375px 视口使用 `16px` 水平边距。
- 最小触控目标为 `44 × 44px`。
- Composer 固定在底部并处理 `safe-area-inset-bottom`，页面内容必须预留足够的底部滚动空间。
- 移动端菜单只承载低频工具和说明，不出现后台导航或虚构历史会话列表。

## Color Tokens

| Token | Value | Usage |
| --- | --- | --- |
| Background / Default | `#070A0E` | 页面主背景 |
| Background / Subtle | `#0B0F14` | 次级背景、舞台层次 |
| Surface / Default | `#10161D` | Composer、消息表面 |
| Surface / Raised | `#151C24` | 抬升层、代码块、菜单 |
| Surface / Hover | `#1B232D` | Hover 表面 |
| Border / Default | `#252E39` | 默认边框、分割线 |
| Border / Strong | `#3A4552` | 强调边框 |
| Text / Primary | `#F4F0E8` | 标题和主要正文 |
| Text / Secondary | `#A7ADB4` | 次级正文 |
| Text / Tertiary | `#7E8792` | 元信息和占位文本 |
| Accent / Default | `#C59A52` | 主要强调色 |
| Accent / Focus | `#D8B36C` | Focus、主要操作 |
| Accent / Subtle | `rgba(197, 154, 82, 0.12)` | 轻量强调背景 |
| Danger | `#D0645D` | 可恢复错误 |
| Warning | `#D9A74F` | 警告和限频 |
| Success | `#58A27B` | 成功状态 |
| Info | `#668AC2` | 信息状态 |
| Overlay | `rgba(0, 0, 0, 0.60)` | Drawer、Modal 遮罩 |

## Typography

不要依赖 Google Fonts 或其他在线字体服务。优先使用中国大陆环境可靠的系统字体栈。

### Font stacks

- 标题：`Songti SC, STSong, SimSun, serif`
- 正文与 UI：`PingFang SC, Microsoft YaHei, system-ui, sans-serif`
- 一个页面最多使用标题和正文两套字体体系。

### Type scale

| Usage | Desktop | Mobile |
| --- | --- | --- |
| Empty 主标题 | `48px / 58px / 500` | `36px / 46px / 500` |
| 页面标题 | `32px / 42px / 600` | `28px / 38px / 600` |
| 区块标题 | `24px / 34px / 600` | `22px / 32px / 600` |
| 正文 | `16px / 28px / 400` | `16px / 26px / 400` |
| 辅助信息 | `14px / 22px / 400` | `14px / 22px / 400` |
| 标签、Caption | `12px / 18px / 500` | `12px / 18px / 500` |
| 按钮 | `15px / 22px / 500` | `15px / 22px / 500` |

长中文回答必须保持足够行高和合理阅读宽度，不能为了单屏展示而压缩为小字号。

## Spacing

- 基础网格：`4px`
- 间距序列：`4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 64`
- Desktop 页面横向主要边距：`40px`
- Desktop 内容区常用间距：`24–32px`
- Mobile 页面横向边距：390px 使用 `20px`；375px 使用 `16px`
- 卡片内部 padding：`16 / 20 / 24px`
- 图片与正文间距：`16–20px`

## Radius

- 紧凑按钮、标签：`4px`
- Composer、图片、内容卡片：`6px`
- Drawer、浮层：`8px`
- 不使用巨大的 Pill Radius，不把每段内容都包装成圆角卡片。

## Border

- 默认：`1px solid #252E39`
- Strong：`1px solid #3A4552`
- Focus：`1px solid #D8B36C`
- Error：`1px solid #D0645D`
- 分隔线优先于阴影，用于建立内容层次。

## Shadow

- 页面和普通组件默认不使用阴影。
- Drawer 或浮层最多使用：`0 12px 32px rgba(0, 0, 0, 0.24)`。
- 不使用大面积发光、霓虹投影或玻璃拟态阴影。

## Breakpoints and Responsive Rules

- `> 1024px`：使用 Desktop 双幕结构。
- `≤ 1024px`：切换为单列结构，视觉内容进入正文流。
- `390px`：移动端标准设计视口，水平边距 `20px`。
- `375px`：紧凑移动端视口，水平边距 `16px`。
- 所有布局必须避免水平溢出。
- Code Block 在 Mobile 内部横向滚动，不得撑宽页面。
- 图片保持内容宽度和 `16:10` 预览比例。
- Mobile Composer 处理 iOS Safe Area、Android Chrome、微信内置浏览器和软键盘顶起。

## Composer

Composer 是当前 MVP 中视觉和交互优先级最高的组件。

### States

- Empty
- Focus
- Typing
- Image Attached
- Sending
- Disabled
- Error

### Desktop implementation rules

- 默认高度约 `96–104px`，不直接使用细节图中较高的展示样例作为默认高度。
- 支持自动增长。
- 最大高度约 `240–280px`，超过后输入区内部滚动。
- 添加图片后可以根据预览自然增高。
- 内边距 `16px`，内部 gap `12px`，Radius `6px`。
- 上传和发送按钮的实际交互目标至少为 `44 × 44px`。
- `Enter` 发送。
- `Shift + Enter` 换行。
- IME composing 期间禁止误发送；只有 composition 结束后才处理 Enter 发送。
- Sending 期间禁止重复提交。
- 发送失败时保留草稿和已选图片。
- 不加入模型选择器、复杂工具栏或虚构的“搜剧模式”开关。

### Mobile implementation rules

- 使用内容宽度：390px 下为 `calc(100% - 40px)`，375px 下为 `calc(100% - 32px)`。
- 输入区最小高度约 `72px`，图片状态可自然增高。
- 使用显式发送按钮；不依赖移动端 Enter 发送。
- 底部间距包含 `env(safe-area-inset-bottom)`。
- 软键盘打开时 Composer 跟随可视视口移动，消息内容保持可滚动。

## Message

- 用户消息右对齐，使用浅暖石墨色表面；最大宽度 Desktop `78%`、Mobile `84%`。
- AI 消息左对齐、开放排版，不给整段回答套大气泡。
- 支持 Heading、Paragraph、List、Bold、Link、Inline Code 和 Code Block。
- Desktop AI 正文建议阅读宽度 `480–560px`。
- 用户图片使用内容宽度、`16:10` 比例和 `6px` Radius。
- 图片分析由图片、状态、标题、正文、关键词和故事方向组成。
- System Notice 使用安静的全宽提示，不使用大型弹窗。
- 历史恢复不得重复插入消息，也不恢复“AI 正在思考”等临时状态。

## Drama Result Card

Drama Search 和 Drama Result Card 是未来功能预留。可以在实现阶段建立基础组件，但不得使用假数据让用户误以为搜剧已经上线。

### Variants

- Featured Desktop：`2:3` 海报约 `240 × 360px`
- Standard Desktop：海报约 `120 × 180px`
- Compact：海报 `96 × 144px`
- Mobile：海报 `112 × 168px`

### Fields

- 竖版海报
- 剧名
- 年份、集数
- 2–3 个标签
- 一句话简介
- AI 匹配理由
- 官方来源
- “查看详情”与“前往官方平台”

### Rules

- 标签高度约 `28px`，Radius `4px`。
- 标题默认一行。
- Desktop 简介最多两行。
- Compact 的 AI 匹配理由最多两行；详情页可完整展开。
- “查看详情”进入产品内详情。
- “前往官方平台”是明确的外部官方链接。
- 不使用评分、免费播放、盗版入口或真实平台 Logo 作为主要层级。

## Loading, Error and Motion

### Loading

- AI Thinking 立即显示“AI 正在思考…”。
- 超过 8 秒显示“仍在处理中”，但不使用虚假百分比。
- 图片分析时图片继续可见，并显示“正在分析图片…”。
- 历史恢复使用轻量 Skeleton，不阻塞 Composer。
- 用户消息可以乐观插入，并显示低权重 pending 状态。

### Error and recovery

- 网络错误：“网络连接失败，请稍后重试。”
- AI 不可用：“AI 暂时无法回复，请稍后再试。”
- 限频：“消息发送太频繁，请稍后再试。”
- 图片异常：“图片格式或大小不符合要求。”
- Session 刷新失败：“登录状态已失效，请重新进入。”
- 错误就近显示，不暴露后端原始异常。
- 错误不得清除用户草稿或已选择的图片。
- 清空记忆成功后显示低权重 System Notice。

### Motion

- Hover：`160ms`
- Drawer / Panel：`180ms`
- Result Reveal：`240ms`
- Scroll to Latest：`240ms`
- Easing：`cubic-bezier(0.2, 0, 0, 1)`
- Reduced Motion：仅保留透明度变化，取消位移和装饰动画。

## Clear Memory

- 清空记忆属于低频、不可逆感较强的操作，应降低视觉权重。
- Desktop 优先放入菜单或其他低权重位置，不与发送按钮竞争。
- Mobile 放入汉堡菜单。
- 点击后必须二次确认。
- 成功后同时清空服务端上下文和当前页面消息，并回到 Empty State。

## Prototype Flow

### Text chat

Empty → Composer Focus → User Message → AI Thinking → AI Response

- Sending 阶段阻止重复提交。
- 成功后清空草稿并滚动到最新回复。
- 429、503 和网络错误保留当前内容并提供重试。

### Image analysis

Choose Image → Image Attached → Uploading → Analysing → Image Response

- 选择图片后立即显示。
- 401 最多自动刷新 Session 并重试一次。
- 失败时移除分析占位，但保留用户图片和恢复入口。
- 当前页面展示真实临时图片；历史恢复只显示服务端保存的文字描述。

### Drama discovery — future

Natural-language Prompt → Interpret Constraints → Loading Results → Featured / Standard Results → Drama Detail

- 该流程只作为未来功能设计预留。
- 当前 MVP 不接入假数据，也不向用户展示伪造结果。
- 卡片点击进入产品内详情；官方平台链接是独立外部动作。

### Mobile shell

Open Page → Restore History Quietly → Single-column Stream → Open Drawer → Close Drawer → Composer / Keyboard

- 历史恢复失败时页面仍然可聊天。
- Composer 随软键盘调整位置。
- Drawer 不是后台侧边栏。

### Clear memory

Menu Action → Confirm → Success Notice → Empty State

### Session recovery

Session Expired → Automatic Refresh Once → Retry Original Request

- 如果第二次仍然失败，停止自动重试并给出明确的重新进入提示。

## Current MVP Boundary

当前 MVP 真正实现且允许在前端展示的能力：

- Empty
- Chat
- Image
- History
- Clear Memory
- Loading
- Error
- Session 恢复

未来设计预留：

- Drama Search
- Drama Result Card
- Drama Detail

未来组件可以先建立静态基础，但不能在真实产品入口中使用假数据冒充已上线搜剧功能。

## Design QA Result

已修正：

- Desktop Empty 原稿左右区域偏平均，最终稿明确强化非对称双幕结构。
- Desktop Drama Search 原稿首卡更接近横向剧照，最终稿改为明确的 `2:3` 竖版海报。

已验证：

- 产品没有偏成 ChatGPT Clone、后台或流媒体首页。
- 没有使用廉价紫色渐变、满屏霓虹、玻璃拟态和电影道具堆砌。
- 长中文回答、代码块、图片分析具有稳定阅读宽度。
- Composer 状态、IME、移动键盘和 Safe Area 有明确实现规则。
- Drama Result 能自然进入未来 AI 搜剧流程，但与当前 MVP 能力边界清晰隔离。
- Mobile 是独立单列体验，并覆盖 390px、375px、Android Chrome 和微信内置浏览器场景。
- Loading、Error、Session 恢复和清空记忆都有可恢复路径。

## Implementation Acceptance Rule

下一阶段必须严格根据本目录的最终页面和本文规格实现，不重新自行设计另一套 UI。

视觉验收顺序：

1. 实现 Desktop Empty。
2. 在目标视口截取浏览器截图。
3. 与 `01-desktop-empty.png` 并排比较。
4. 修正明显的布局、字体、间距、边框、色彩和 Composer 偏差。
5. 通过后再实现 Desktop Chat。
6. 完成 Desktop 后再实现 Mobile。
7. 最后接入真实 Web API。

`npm build` 成功只代表工程构建通过，不能替代视觉验收。
