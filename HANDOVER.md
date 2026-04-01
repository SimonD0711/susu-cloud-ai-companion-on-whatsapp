# 苏苏（Susu）WhatsApp 聊天机器人 — 运维手册

> **最后更新：2026-04-01** | 架构版本：模块化重构后（v2）

---

## 项目架构

```
susu-cloud/
├── wa_agent.py              # HTTP 服务入口（~50行），调用 src/wa_agent/server.py
├── susu_admin_server.py     # 管理后台（独立服务，端口 9001）
├── susu_admin_core.py       # 管理后台核心库
├── src/
│   ├── ai/                  # AI 能力层
│   │   ├── config.py        # 所有环境变量（AIConfig dataclass）
│   │   ├── base.py          # LLMProvider ABC / LLMMessage / LLMResponse
│   │   ├── llm/
│   │   │   ├── relay.py     # RelayProvider（带重试）
│   │   │   ├── manager.py   # LLMManager（chat / chat_text / chat_with_fallback）
│   │   │   └── prompts.py   # 系统 prompt 集中管理
│   │   ├── tts/
│   │   │   └── minimax.py   # MiniMax TTS
│   │   ├── whisper/
│   │   │   └── groq.py      # Groq Whisper 转文字
│   │   └── search/          # 搜索路由
│   │       ├── router.py     # SearchRouter / SearchPlan / SearchResult
│   │       ├── weather.py    # 香港天文台 / OpenWeatherMap
│   │       ├── news.py       # Tavily / Google News / Bing News / Reddit / X
│   │       ├── music.py      # iTunes / Spotify / YouTube
│   │       └── web.py        # Tavily Web / Bing / DuckDuckGo / Reddit
│   └── wa_agent/            # WhatsApp 业务层
│       ├── brain.py          # ReplyBrain + normalize_reply / looks_fragmentary / split_reply_bubbles 等
│       ├── memory.py         # MemoryManager + memory extraction prompts
│       ├── db.py            # MemoryDB（SQLite wrapper，context manager）
│       ├── auth.py          # 认证（PBKDF2 210000 iterations）
│       ├── proactive.py     # 主动消息生成 + 评分 + proactive_loop
│       ├── reminders.py     # 提醒检测 + firing + reminder_loop
│       ├── voice.py        # TTS 语音 pipeline
│       ├── whatsapp.py     # WhatsApp Business API 封装
│       ├── server.py       # HTTP server 入口
│       └── utils.py        # 工具函数
├── tests/                   # pytest 测试（190 个）
├── wa_agent.db            # SQLite 数据库
└── REFACTOR-PLAN.md       # 重构计划文档（可归档）
```

---

## Tokyo 服务

| 服务 | 端口 | 进程文件 | 用途 |
|------|------|----------|------|
| wa-agent | 9100 | wa_agent.py | WhatsApp 主服务 |
| susu-admin-api | 9001 | susu_admin_server.py | 管理后台 API |
| cheungchau-api | - | /var/www/simond-photo-api/ | 长洲照片 API |

---

## 部署流程

### 日常更新代码

**Step 1：本地开发 + 测试**

```bash
cd C:\Users\ding7\Documents\susu-cloud

# 修改代码后运行测试
python -m pytest tests/ -v

# 推送 GitHub
git add .
git commit -m "描述改动内容"
git push
```

**Step 2：Tokyo 拉取 + 重启**

```bash
ssh root@Tokyo

# 拉取最新 main 分支 + 重启所有服务
cd /var/www/html && git pull && systemctl restart wa-agent && systemctl restart susu-admin-api
```

### Git 分支策略

- `main` — 生产环境分支，代码稳定
- `refactor/unified-ai-layer` — 重构开发分支（已合并到 main）

**禁止直接在 main 上开发**。所有改动先在本地测试，再推 GitHub。

### 紧急回滚

```bash
# Tokyo 查看最近提交
cd /var/www/html && git log --oneline -5

# 回滚到上一个版本
cd /var/www/html && git revert HEAD && systemctl restart wa-agent
```

### 新功能/重构流程

1. 从 `main` 新建功能分支
2. 本地开发 + 测试通过
3. PR review 后合并到 `main`
4. Tokyo `git pull` 拉取

---

## 常用运维命令

### 服务管理

```bash
# 查看服务状态
systemctl status wa-agent
systemctl status susu-admin-api

# 重启服务
systemctl restart wa-agent
systemctl restart susu-admin-api

# 查看日志
journalctl -u wa-agent --no-pager -n 50
journalctl -u wa-agent --since '1 hour ago'
journalctl -u susu-admin-api --no-pager -n 50
```

### 健康检查

```bash
# wa-agent
curl http://127.0.0.1:9100/health

# 管理后台
curl http://127.0.0.1:9001/healthz
```

### 语法检查

```bash
cd /var/www/html
python3 -m py_compile wa_agent.py
python3 -m py_compile src/wa_agent/brain.py
python3 -m py_compile src/wa_agent/proactive.py
python3 -m py_compile src/wa_agent/reminders.py
```

### 数据库操作

```bash
sqlite3 /var/www/html/wa_agent.db

-- 查看 voice mode 状态
SELECT * FROM wa_memories WHERE memory_key='voice_mode';

-- 查看最近消息
SELECT id, direction, body, created_at FROM wa_messages ORDER BY id DESC LIMIT 10;

-- 查看主动消息事件
SELECT * FROM wa_proactive_events ORDER BY id DESC LIMIT 10;

-- 查看待触发提醒
SELECT * FROM wa_reminders WHERE fired=0 ORDER BY remind_at;

-- 查看 contact 列表
SELECT wa_id, profile_name, updated_at FROM wa_contacts ORDER BY updated_at DESC;
```

---

## 模块速查

| 模块 | 关键函数/类 | 用途 |
|------|------------|------|
| `src/ai/config.py` | `AIConfig()` | 所有环境变量的 dataclass |
| `src/ai/llm/manager.py` | `LLMManager().chat()` | LLM 对话调用入口 |
| `src/ai/llm/relay.py` | `RelayProvider` | 带重试的 relay LLM 调用 |
| `src/ai/tts/minimax.py` | `MiniMaxTTS().speak()` | 文字转语音 |
| `src/ai/whisper/groq.py` | `GroqWhisper().transcribe()` | 语音转文字 |
| `src/ai/search/router.py` | `SearchRouter().route()` | 搜索意图路由 |
| `src/wa_agent/brain.py` | `ReplyBrain().generate()` / `normalize_reply()` / `split_reply_bubbles()` | 回复生成大脑 |
| `src/wa_agent/db.py` | `MemoryDB()` | SQLite CRUD，context manager 协议 |
| `src/wa_agent/whatsapp.py` | `send_whatsapp_text()` / `send_whatsapp_audio()` | WhatsApp API 封装 |
| `src/wa_agent/proactive.py` | `run_proactive_scan_once()` / `evaluate_proactive_candidate()` | 主动消息评分 |
| `src/wa_agent/reminders.py` | `detect_reminder()` / `parse_reminder_from_text()` / `fire_reminder()` | 提醒检测 + 触发 |
| `src/wa_agent/voice.py` | `generate_and_send_voice_reply()` | TTS 语音 pipeline |
| `src/wa_agent/auth.py` | `verify_admin_password()` | PBKDF2 认证 |

---

## 测试

```bash
# 运行全部测试
python -m pytest tests/ -v

# 只跑 ai 层测试
python -m pytest tests/ai/ -v

# 只跑 wa_agent 测试
python -m pytest tests/wa_agent/ -v

# 运行特定文件
python -m pytest tests/wa_agent/test_brain.py -v
```

**注意：** 测试使用 `tests/conftest.py` 中的 `default_env` fixture，会自动 monkeypatch 所有环境变量。如果测试需要修改 env 变量后再读 `AIConfig()`，需要 `importlib.reload(src.ai.config)` 或使用 `DummyConfig` / `MagicMock`。

---

## 环境变量

所有关键环境变量定义在 `src/ai/config.py` 的 `AIConfig` dataclass 中：

| 变量 | 用途 |
|------|------|
| `WA_ACCESS_TOKEN` | WhatsApp API Token |
| `WA_PHONE_NUMBER_ID` | WhatsApp Phone Number ID |
| `WA_RELAY_API_KEY` | LLM Relay API Key |
| `WA_RELAY_MODEL` | LLM 模型名（默认 claude-opus-4-6）|
| `WA_MINIMAX_API_KEY` | MiniMax API Key |
| `WA_GROQ_API_KEY` | Groq API Key |
| `WA_TAVILY_API_KEY` | Tavily 搜索 Key |
| `WA_PROACTIVE_ENABLED` | 主动消息开关（1/0）|
| `WA_ADMIN_WA_ID` | 管理员 WhatsApp ID |

---

## 故障排查

### wa-agent 无响应

```bash
# 1. 检查端口
curl http://127.0.0.1:9100/health

# 2. 查看日志
journalctl -u wa-agent --no-pager -n 50

# 3. 语法检查
python3 -m py_compile /var/www/html/wa_agent.py

# 4. 重启
systemctl restart wa-agent
```

### 主动消息没有触发

```bash
# 1. 检查 proactive 事件
sqlite3 /var/www/html/wa_agent.db "SELECT * FROM wa_proactive_events ORDER BY id DESC LIMIT 5;"

# 2. 检查配置
curl http://127.0.0.1:9100/health | grep proactive

# 3. 检查服务是否 active
systemctl status wa-agent
```

### TTS 不发语音

```bash
# 1. 检查日志
journalctl -u wa-agent --no-pager | grep -i audio

# 2. 本地测试 TTS（服务器上）
cd /var/www/html && python3 -c "
import sys; sys.path.insert(0, '.')
from src.ai.tts.minimax import MiniMaxTTS
from src.ai.config import AIConfig
tts = MiniMaxTTS(AIConfig())
print(tts.speak('测试'))
"
```

### 数据库锁定

```bash
# 检查进程
lsof /var/www/html/wa_agent.db

# 强制解锁
sqlite3 /var/www/html/wa_agent.db "SELECT 1;"
```

---

## 项目联系人

| 角色 | 联系方式 |
|------|----------|
| 用户 | Simon（通过 WhatsApp 联系苏苏）|
| 苏苏号码 | 85259576670 |
| 管理员号码 | 8196853612 |
| 服务器 | Tokyo VPS (103.147.185.18) |
| 本地开发 | Lenovo 笔记本 |

---

## 长洲照片 API（独立服务）

**仓库：** `SimonD0711/simond-photo-api`
**部署路径：** `/var/www/simond-photo-api/`
**服务名：** `cheungchau-api`

```bash
# 重启
systemctl restart cheungchau-api

# 查看状态
systemctl status cheungchau-api

# 日志
journalctl -u cheungchau-api --no-pager -n 50
```
