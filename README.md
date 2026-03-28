# Susu Cloud

Susu Cloud 是一个独立的开源仓库，包含：

- `wa_agent.py`: WhatsApp webhook runtime，负责收消息、调模型、写入长期/短期记忆和提醒
- `susu_admin_server.py`: 轻量管理 API 和管理页面静态托管
- `susu-memory-admin.html`: 记忆与提醒后台


## Features

- WhatsApp Webhook 接入
- 长期记忆、短期记忆、提醒事项三类 SQLite 数据
- 多模型回退链路
- 基于 cookie 的本地后台登录
- 纯 Python 标准库运行

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

## License

MIT. See [LICENSE](./LICENSE).
