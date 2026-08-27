# wechat-ai Development Context

最后归档日期：2026-08-26

本文用于在其他电脑或后续开发任务中恢复项目上下文。不得在本文记录 API Key、Cookie Token、AppSecret、真实 `.env` 内容或其他凭据。

## Current Product State

- 微信小程序路线已经删除，不再继续维护小程序前端或小程序 API。
- 微信公众号继续保留，现有文字、图片和语音能力不得因 Web 开发而被重构或破坏。
- Web 匿名 HttpOnly Cookie Session 已经完成。
- Web API 已经完成。
- DeepSeek 文字能力已经真实联调成功。
- Qwen 图片理解已经真实联调成功。
- Redis 的 `web` / `wechat` namespace 隔离已经完成。
- AI Provider 架构已经完成。
- 当前后端测试已经通过。
- Direction 2.5 Web 设计已经最终批准并归档。
- 下一阶段目标是 React + Vite Web 前端。
- 下一阶段必须严格根据 `docs/design/direction-2.5/` 实现。
- 不要重新自行设计另一套 UI。

## Current Web API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/web/v1/session` | 创建或恢复匿名 Web Session |
| `GET` | `/api/web/v1/me` | 验证当前 Session |
| `GET` | `/api/web/v1/history` | 获取当前 Web 用户的最近历史 |
| `POST` | `/api/web/v1/chat` | 文字 AI 聊天 |
| `POST` | `/api/web/v1/image` | 上传图片并进行 AI 分析 |
| `DELETE` | `/api/web/v1/memory` | 清空当前 Web 用户的聊天记忆 |

Web 身份由服务端可信 Session 决定。前端不得提交或信任 OpenID、user ID、Redis Key 或其他身份字段。

## Approved Design Source

- Design Spec：`docs/design/direction-2.5/README.md`
- Desktop Empty：`docs/design/direction-2.5/01-desktop-empty.png`
- Desktop Chat + Image：`docs/design/direction-2.5/02-desktop-chat-image.png`
- Desktop Drama Search：`docs/design/direction-2.5/03-desktop-drama-search.png`
- Mobile Empty：`docs/design/direction-2.5/04-mobile-empty.png`
- Mobile Chat + Image：`docs/design/direction-2.5/05-mobile-chat-image.png`
- Mobile Drama Search：`docs/design/direction-2.5/06-mobile-drama-search.png`
- Composer States：`docs/design/direction-2.5/07-composer-states.png`
- Drama Result Card：`docs/design/direction-2.5/08-drama-result-card.png`
- Message & System States：`docs/design/direction-2.5/09-message-system-states.png`
- Prototype Flow：`docs/design/direction-2.5/10-prototype-flow.png`

Desktop Empty 和 Desktop Drama Search 已经是 Design QA 修正后的版本。不要从聊天记录或生成目录中恢复被替代的旧稿。

## MVP Capability Boundary

当前 MVP 前端只真正实现：

- Empty State
- 文字 Chat
- Image Analysis
- History Restore
- Clear Memory
- Loading States
- Error and Recovery States
- Anonymous Session 恢复

Drama Search、Drama Result Card 和 Drama Detail 目前属于未来设计预留。可以建立不暴露给用户的组件基础，但不能使用假数据冒充已经上线的搜剧功能。

## Next Phase Goal

创建 React + Vite Web 前端，并按以下顺序推进：

1. 实现 Desktop Empty。
2. 使用浏览器在目标视口截图。
3. 将截图与 `docs/design/direction-2.5/01-desktop-empty.png` 比较。
4. 修正布局、字号、间距、色彩、边框和 Composer 偏差。
5. Desktop Empty 视觉验收通过后，实现 Desktop Chat。
6. 完成 Desktop 图片与消息状态。
7. 实现独立 Mobile 单列布局。
8. 完成视觉与响应式验收后，再接入真实 Web API。

不能以 `npm build` 成功代替视觉验收。构建、类型检查和测试通过后，仍必须进行浏览器截图对比。

## Implementation Principles

- 不重构或改变微信公众号业务行为。
- 不恢复已删除的微信小程序路线。
- 不重新设计 Direction 2.5。
- 不把未来 Drama 功能伪装成已上线能力。
- Desktop 使用非对称双幕结构；Mobile 使用独立单列结构。
- Desktop Composer：Enter 发送，Shift+Enter 换行，IME composing 期间禁止误发送。
- Composer 默认高度约 `96–104px`，自动增长，最大约 `240–280px`；图片状态允许自然增高。
- 清空记忆降低视觉权重：Desktop 放菜单或低权重位置，Mobile 放汉堡菜单，并进行二次确认。
- 不依赖 Google Fonts 等在线字体服务，使用 Design Spec 中的中国大陆可靠系统字体栈。
- 前端不得包含或输出任何服务端密钥、Cookie Token、AppSecret 或真实环境配置。

## First Step When Resuming

先读取本文和 `docs/design/direction-2.5/README.md`，确认 Git 工作区状态，然后只实现 Desktop Empty 页面骨架和 Composer 静态状态。完成后立即进行浏览器截图对比，不要先扩展 Chat、Mobile 或 Drama 功能。
