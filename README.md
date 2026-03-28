# Susu Cloud: AI Companion on WhatsApp

[![Release](https://img.shields.io/github/v/release/SimonD0711/susu-cloud-ai-companion-on-whatsapp)](https://github.com/SimonD0711/susu-cloud-ai-companion-on-whatsapp/releases)
[![Package](https://img.shields.io/badge/GHCR-container-blue)](https://github.com/SimonD0711/susu-cloud-ai-companion-on-whatsapp/pkgs/container/susu-cloud-ai-companion-on-whatsapp)

Susu Cloud: AI Companion on WhatsApp 是一个独立的开源仓库，包含：

- `wa_agent.py`: WhatsApp webhook runtime，负责收消息、调模型、写入长期/短期/归档记忆和提醒，并从数据库读取运行时设置
- `susu_admin_server.py`: 轻量管理 API，支持记忆、提醒和运行设置读写
- `susu-memory-admin.html`: 记忆、提醒与运行设置后台


## Features

- WhatsApp Webhook runtime
  接收 Meta WhatsApp Cloud API webhook 事件，处理文本与图片消息，写入本地 SQLite，并在短暂等待窗口后把连续消息合并成一次回复上下文。

- 分层记忆系统
  内建长期记忆 `wa_memories`、短期记忆 `wa_session_memories`、归档记忆 `wa_memory_archive` 和提醒事项 `wa_reminders`。短期记忆会按 `24 小时 / 3 天 / 7 天` 自动分桶，超过 7 天后自动转入归档层。

- 自动记忆提取
  会从聊天内容里抽取适合长期保存的信息，以及只在最近几天内有价值的短期信息，减少每次都要重新提供用户背景。

- 归档记忆检索
  超过 7 天的短期记忆默认不进入日常 prompt，只有当用户追问「之前 / 上星期 / 上個月」这类旧事时，才会按关键词从归档层检索相关内容。

- 提醒与主动消息能力
  支持从聊天中解析提醒请求并定时触发，也支持根据静默时长、回复窗口和时段策略生成主动消息，不只是被动问答。

- 多模型路由与回退
  支持 Relay、Gemini、MiniMax、Groq 多个提供方。可以按顺序自动降级，在某个模型或 API 不可用时继续服务。

- 图片消息处理
  对 WhatsApp 图片消息做下载、分类和输入拼装，让回复逻辑能结合图片内容，而不只依赖纯文本。

- 更像即时聊天的回复输出
  支持气泡拆分、夜间/白天语气差异、引用回复、消息 reaction 和后续补句，输出形态更接近真实 WhatsApp 对话节奏。

- 独立后台管理
  `susu_admin_server.py` 提供轻量管理 API，`susu-memory-admin.html` 提供联系人、长期记忆、短期记忆、归档记忆、提醒事项的查看、编辑、删除和创建能力，也支持直接修改 `wa_susu_settings` 中的人设、Primary User Memory、模型路由和主动消息参数。

- 独立部署，不依赖大型框架
  整个项目基于 Python 标准库 HTTP 服务和 SQLite，可直接作为轻量服务运行，适合先快速部署、再逐步演进。

- 配置与隐私解耦
  用户画像、管理员密码哈希、cookie secret、数据库路径、端口、模型 key 都通过 `.env` 注入，仓库本身不再携带个人资料或生产凭据；运行中的核心设定则可通过后台写入数据库，避免反复改代码或重启服务。

## Quick Start

1. 复制配置模板

```powershell
Copy-Item .env.example .env
```

2. 生成后台密码哈希

```powershell
python .\tools\hash_password.py "your-admin-password"
```

把输出填进 `.env` 里的：

- `SUSU_ADMIN_PASSWORD_SALT_B64`
- `SUSU_ADMIN_PASSWORD_HASH_B64`
- `SUSU_ADMIN_SESSION_SECRET`

3. 启动 WhatsApp runtime

```powershell
python .\wa_agent.py
```

4. 启动后台

```powershell
python .\susu_admin_server.py
```

默认地址：

- Runtime webhook: `http://127.0.0.1:9100/whatsapp/webhook`
- Admin UI: `http://127.0.0.1:9000/`

## Notes

- 数据库默认写到 `./data/wa_agent.db`
- `.env`、数据库文件和 `data/` 目录默认不会提交到 Git
- `WA_PRIMARY_USER_MEMORY` / `WA_PRIMARY_USER_MEMORY_FILE` 用来注入你自己的用户画像，仓库本身不再带个人资料
- `WA_CLAUDE_WA_ID` 对应的 Claude Code 流式代理能力是可选能力，依赖本机安装的 `claude` CLI 和相应运行环境

## Files

- `wa_agent.py`
- `susu_admin_server.py`
- `susu-memory-admin.html`
- `tools/hash_password.py`
- `.env.example`
- `PUBLIC_DEV_NOTES.md`
- `Dockerfile`

## License

MIT. See [LICENSE](./LICENSE).

## Release And Package

- GitHub Releases are published from tags like `v0.1.0`
- GitHub Packages publishes a GHCR container image for this repository
- Releases page: [GitHub Releases](https://github.com/SimonD0711/susu-cloud-ai-companion-on-whatsapp/releases)
- Package page: [GHCR Container](https://github.com/SimonD0711/susu-cloud-ai-companion-on-whatsapp/pkgs/container/susu-cloud-ai-companion-on-whatsapp)
- Image tags include version tags like `v0.1.0` and `latest`

```bash
docker pull ghcr.io/simond0711/susu-cloud-ai-companion-on-whatsapp:latest
docker run --rm -p 9100:9100 --env-file .env ghcr.io/simond0711/susu-cloud-ai-companion-on-whatsapp:latest
```
