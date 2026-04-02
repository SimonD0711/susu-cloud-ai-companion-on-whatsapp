# 苏苏（Susu）WhatsApp 聊天机器人 — 运维手册

> **最后更新：2026-04-02** | 架构版本：v2（含关键 Bug 修复 + Location 自动检测）

---

## 项目架构

### Tokyo 生产环境（实际运行的代码）

Tokyo VPS 上运行的是单体版 `wa_agent.py`（~6800 行），**不是** modular src/ 分支。目录结构：

```
/var/www/html/
├── wa_agent.py              # 单体主文件（HTTP webhook + reply pipeline + proactive loop）
├── wa_agent.db              # SQLite 数据库
├── src/                     # 模块包（存在于本地 Git 仓库，Tokyo 上可能不存在）
├── susu_admin_server.py     # 管理后台（端口 9001）
└── susu_admin_core.py      # 管理后台核心库

C:\Users\ding7\Documents\susu-cloud\   # 本地开发目录（monolith + modular 混合）
├── wa_agent.py              # 与 Tokyo 同步的单体文件
└── src/                    # 模块包（本地测试用，Tokyo 生产不用）
```

### 模块速查（wa_agent.py 关键函数）

| 函数 | 行号 | 用途 |
|------|------|------|
| `extract_text_messages` | ~3200 | 从 Webhook payload 提取消息事件 |
| `fetch_whatsapp_audio` | ~3109 | 从 WhatsApp 下载音频文件 |
| `groq_whisper_transcribe` | ~3142 | Whisper 转写（走 Cloudflare Worker） |
| `build_runtime_context` | ~5719 | 构建 LLM prompt 上下文 |
| `extract_location_from_text` | ~907 | LLM 提取用户位置 |
| `maybe_update_user_location` | ~922 | 检测并更新 current_location |
| `record_batch_side_effects` | ~6165 | 回复后副作用（记忆 + 位置 + 提醒） |
| `process_pending_replies_for_contact` | ~6192 | Reply worker 主循环 |
| `spawn_reply_generation_subprocess` | ~6500 | 启动 reply subprocess |
| `ensure_reply_worker_running` | ~6446 | 触发 reply worker 线程 |
| `recover_pending_reply_contacts_once` | ~6475 | 恢复扫描（包含 audio 联系人） |
| `maybe_extract_memories` | ~4587 | LLM 抽取长期记忆 |
| `generate_model_text` | ~4492 | LLM 文本生成入口 |

---

## Tokyo 服务

| 服务 | 端口 | 进程文件 | 用途 |
|------|------|----------|------|
| wa-agent | 9100 | wa_agent.py | WhatsApp 主服务 |
| susu-admin-api | 9001 | susu_admin_server.py | 管理后台 API |
| cheungchau-api | - | /var/www/simond-photo-api/ | 长洲照片 API |

**SSH 连接：** `ssh -p 2222 root@Tokyo`

---

## 部署流程

### Tokyo 网络限制

**Tokyo VPS 无法访问 GitHub**（被某墙拦截），所以部署分两步：

### 日常更新

**Step 1：本地开发 + GitHub**

```bash
cd C:\Users\ding7\Documents\susu-cloud

# 修改代码
# 测试（如果有测试的话）

git add .
git commit -m "描述改动"
git push   # GitHub 端更新
```

**Step 2：SCP 部署到 Tokyo + 重启**

```powershell
# 本地执行（PowerShell）
scp -P 2222 C:\Users\ding7\Documents\susu-cloud\wa_agent.py root@Tokyo:/var/www/html/wa_agent.py

# SSH 到 Tokyo 重启
ssh -p 2222 root@Tokyo
systemctl restart wa-agent
systemctl status wa-agent
```

### 紧急回滚

```bash
# Tokyo 上查看最近提交
cd /var/www/html && git log --oneline -5

# 回滚到上一个版本
cd /var/www/html && git revert HEAD && systemctl restart wa-agent
```

---

## 常用运维命令

### 服务管理

```bash
# 查看服务状态
systemctl status wa-agent
systemctl status susu-admin-api

# 重启
systemctl restart wa-agent
systemctl restart susu-admin-api

# 查看日志
journalctl -u wa-agent --no-pager -n 50
journalctl -u wa-agent --since '1 hour ago'

# 查看最新日志
journalctl -u wa-agent --no-pager -n 10
```

### 健康检查

```bash
# wa-agent（必须走 localhost，因为有 Nginx 反向代理）
curl http://127.0.0.1:9100/health

# 管理后台
curl http://127.0.0.1:9001/healthz
```

### 语法检查

```bash
cd /var/www/html
python3 -m py_compile wa_agent.py
```

### 数据库操作

```bash
sqlite3 /var/www/html/wa_agent.db

-- 查看 voice mode 状态
SELECT * FROM wa_memories WHERE memory_key='voice_mode';

-- 查看最近消息
SELECT id, direction, body, created_at FROM wa_messages ORDER BY id DESC LIMIT 10;

-- 查看 outbound 回复
SELECT id, direction, message_type, body, created_at FROM wa_messages WHERE direction='outbound' ORDER BY id DESC LIMIT 10;

-- 查看主动消息事件
SELECT * FROM wa_proactive_events ORDER BY id DESC LIMIT 10;

-- 查看待触发提醒
SELECT * FROM wa_reminders WHERE fired=0 ORDER BY remind_at;

-- 查看当前用户位置
SELECT * FROM wa_memories WHERE memory_key='current_location' AND wa_id='85259576670';

-- 查看 contact 列表
SELECT wa_id, profile_name, updated_at FROM wa_contacts ORDER BY updated_at DESC;
```

---

## 关键 Bug 修复记录

### 2026-04-02 修复（已上线）

#### 1. Recovery Query 漏掉音频联系人
- **文件：** `wa_agent.py` `recover_pending_reply_contacts_once`（~6475行）
- **问题：** 查询只扫描 `message_type IN ('text', 'image')`，音频联系人被漏掉
- **修复：** 添加 `'audio'` 到 IN 列表
- **commit：** `b895583`

#### 2. GROQ Whisper 无法处理 WhatsApp 音频
- **文件：** `wa_agent.py` `groq_whisper_transcribe`（~3142行）
- **问题：** WhatsApp 音频只有 3-5KB，GROQ Whisper 拒绝处理
- **修复：** 加了 User-Agent 绕过 Cloudflare Worker 403，并加了下限 Fallback 消息
- **Fallback 消息：** "收到語音了，不過我暫時翻唔到內容，下次可以試下send文字比我"
- **触发条件：** `has_audio=True AND audio_transcribe_attempted=True AND combined_text=''`
- **commit：** `b895583`

#### 3. fetch_whatsapp_audio 异常未捕获
- **文件：** `wa_agent.py` `fetch_whatsapp_audio`（~3109行）
- **问题：** `graph_get_json` 抛异常时直接崩溃
- **修复：** 包裹 try/except
- **commit：** `b895583`

#### 4. Location 自动更新
- **文件：** `wa_agent.py` `extract_location_from_text` + `maybe_update_user_location`（~907-950行）
- **问题：** 用户说 "我到長春啦" 后存的是普通记忆，不是 `current_location`
- **修复：** LLM 判断消息中是否透露位置 → `normalize_location` 规范化 → 存入 `wa_memories` (memory_key=`current_location`)
- **位置别名：** 香港区域、内地城市、CityU、九龍城 等均有规范化映射
- **Prompt 注入：** `current_location` 被加入 LLM prompt 的 "User's known location" 字段
- **System Persona：** 加了"要留意對方嘅即時位置"指示
- **commit：** `b6916f3`

### 历史修复

#### GROQ API Key 问题（已切换到新 Key）
- **旧 Key（已失效）：** `<旧 Key 在 /etc/wa-agent.env 中>`
- **新 Key：** `<新 Key 在 /etc/wa-agent.env 中>`
- **配置：** `/etc/wa-agent.env` 中的 `WA_GROQ_API_KEY`

#### Whisper 请求绕过 Cloudflare WARP 拦截
- **问题：** Tokyo VPS 通过 WARP TUN 模式时 GROQ 被 403
- **解决：** Whisper 改走 Cloudflare Worker `https://relay-proxy.simonding711.workers.dev/openai/v1/audio/transcriptions`
- **groq-proxy.js：** `/opt/librechat/groq-proxy.js` 已修改支持 multipart/form-data

#### REDSOCKS iptables 规则导致 HTTPS 失败
- **问题：** redsocks 装的 iptables 规则在 WARP 关闭后仍拦截 TCP 流量
- **解决：** 清除了 REDSOCKS 的 iptables 规则
- **状态：** WARP 已 disable，REDSOCKS 规则已清除

---

## 已知限制

### Whisper 语音转写
WhatsApp 音频文件太小（3-5KB），GROQ Whisper 拒绝处理。语音消息目前：
- 可以收到
- 会记录到 DB（body=''）
- 会触发 proactive 回复（voice mode）
- 但无法自动转写文字

### Cloudflare Worker
Worker 地址：`https://relay-proxy.simonding711.workers.dev`
- 目前只路由 Whisper 请求到 GROQ
- 如果 Worker 挂了，语音转写完全不可用

---

## 环境变量

关键配置在 `/etc/wa-agent.env`（systemd 读取）：

| 变量 | 用途 |
|------|------|
| `WA_ACCESS_TOKEN` | WhatsApp API Token |
| `WA_PHONE_NUMBER_ID` | WhatsApp Phone Number ID |
| `WA_GRAPH_VERSION` | Graph API 版本（当前 v22.0）|
| `WA_RELAY_API_KEY` | LLM Relay API Key |
| `WA_RELAY_MODEL` | LLM 模型名（默认 claude-opus-4-6）|
| `WA_GROQ_API_KEY` | Groq API Key（当前有效）|
| `WA_MINIMAX_API_KEY` | MiniMax TTS API Key |
| `WA_GEMINI_API_KEY` | Gemini API Key |
| `WA_PROACTIVE_ENABLED` | 主动消息开关 |
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

# 5. 检查进程
ps aux | grep wa_agent.py | grep -v grep
```

### 语音消息没有回复

1. 检查 DB：`SELECT * FROM wa_messages WHERE message_type='audio' ORDER BY id DESC LIMIT 5;`
2. 检查 outbound：`SELECT * FROM wa_messages WHERE direction='outbound' ORDER BY id DESC LIMIT 10;`
3. 检查日志：`journalctl -u wa-agent --no-pager | grep -i audio`
4. 测试 GROQ Whisper：

```bash
curl -s -X POST 'https://relay-proxy.simonding711.workers.dev/openai/v1/audio/transcriptions' \
  -H 'Authorization: Bearer $WA_GROQ_API_KEY' \
  -F 'file=@/tmp/test_audio.ogg;type=audio/ogg' \
  -F 'model=whisper-large-v3'
```

### 主动消息没有触发

```bash
# 检查配置
curl http://127.0.0.1:9100/health | grep proactive

# 检查服务
systemctl status wa-agent
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
| Cloudflare Worker | `https://relay-proxy.simonding711.workers.dev` | Whisper 路由

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
