# 苏苏（Susu）WhatsApp 聊天机器人 — 运维手册

> **最后更新：2026-04-03** | 架构版本：v3（含日历系统 + UI全面优化）

---

## 项目架构

### Tokyo 生产环境（实际运行的代码）

Tokyo VPS 上运行的是单体版 `wa_agent.py`（~7200 行），**不是** modular src/ 分支。目录结构：

```
/var/www/html/
├── wa_agent.py              # 单体主文件（HTTP webhook + reply pipeline + proactive loop）
├── wa_agent.db              # SQLite 数据库
├── src/                     # 模块包（存在于本地 Git 仓库，Tokyo 上可能不存在）
├── susu_admin_server.py     # 管理后台（端口 9001）
├── susu_admin_core.py        # 管理后台核心库
└── susu-memory-admin.html   # 苏苏记忆管理页面

C:\Users\ding7\Documents\susu-cloud\   # 本地开发目录（monolith + modular 混合）
├── wa_agent.py              # 与 Tokyo 同步的单体文件
├── susu-memory-admin.html   # 记忆管理页面（与 Tokyo 同步）
├── susu_admin_core.py       # 管理后台核心
├── susu_admin_server.py     # 管理后台服务
└── src/                    # 模块包（本地测试用，Tokyo 生产不用）
```

### 模块速查（wa_agent.py 关键函数）

| 函数 | 行号 | 用途 |
|------|------|------|
| `extract_text_messages` | ~3200 | 从 Webhook payload 提取消息事件 |
| `fetch_whatsapp_audio` | ~3109 | 从 WhatsApp 下载音频文件 |
| `groq_whisper_transcribe` | ~3142 | Whisper 转写（走 Cloudflare Worker） |
| `build_runtime_context` | ~6060 | 构建 LLM prompt 上下文（**日历系统在此接入**） |
| `build_structured_context_from_runtime_context` | ~6258 | 生成 system prompt（**日期在此注入**） |
| `extract_location_from_text` | ~1005 | LLM 提取用户位置（**已改简体中文 Prompt**） |
| `maybe_update_user_location` | ~971 | 检测并更新 current_location（**含放假记忆触发**） |
| `record_batch_side_effects` | ~6165 | 回复后副作用（记忆 + 位置 + 提醒） |
| `process_pending_replies_for_contact` | ~6192 | Reply worker 主循环 |
| `spawn_reply_generation_subprocess` | ~6500 | 启动 reply subprocess |
| `ensure_reply_worker_running` | ~6446 | 触发 reply worker 线程 |
| `recover_pending_reply_contacts_once` | ~6475 | 恢复扫描（包含 audio 联系人） |
| `maybe_extract_memories` | ~4587 | LLM 抽取长期记忆 |
| `generate_model_text` | ~4492 | LLM 文本生成入口 |
| `parse_ical_events` | ~1028 | 解析 iCal（含 RRULE 展开、EXDATE 排除） |
| `get_calendar_events_cached` | ~1166 | 获取日历事件（每日缓存逻辑） |
| `detect_semester_period` | ~1205 | 从课程事件推断学期状态 |
| `get_today_holiday` | ~1050 | 判断今天是否 HK 公众假期 |
| `hk_now` | ~649 | 香港时区当前时间 |
| `hk_today` | ~1046 | 香港时区今日日期 |

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

```powershell
cd C:\Users\ding7\Documents\susu-cloud

# 修改代码
git add .
git commit -m "描述改动"
git push
```

**Step 2：SCP 部署到 Tokyo + 重启**

```powershell
# wa_agent.py
scp -P 2222 C:\Users\ding7\Documents\susu-cloud\wa_agent.py root@Tokyo:/var/www/html/wa_agent.py

# 管理后台文件（如有改动）
scp -P 2222 C:\Users\ding7\Documents\susu-cloud\susu_admin_core.py root@Tokyo:/var/www/html/
scp -P 2222 C:\Users\ding7\Documents\susu-cloud\susu_admin_server.py root@Tokyo:/var/www/html/
scp -P 2222 C:\Users\ding7\Documents\susu-cloud\susu-memory-admin.html root@Tokyo:/var/www/html/

# SSH 到 Tokyo 重启
ssh -p 2222 root@Tokyo
systemctl restart wa-agent
systemctl restart susu-admin-api
systemctl status wa-agent
```

### 紧急回滚

```bash
cd /var/www/html
git log --oneline -5
cd /var/www/html && git revert HEAD && systemctl restart wa-agent
```

---

## 常用运维命令

### 服务管理

```bash
systemctl status wa-agent
systemctl status susu-admin-api
systemctl restart wa-agent
systemctl restart susu-admin-api
journalctl -u wa-agent --no-pager -n 50
journalctl -u wa-agent --since '1 hour ago'
```

### 健康检查

```bash
curl http://127.0.0.1:9100/health
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

-- 查看当前用户位置
SELECT * FROM wa_memories WHERE memory_key='current_location' AND wa_id='85259576670';

-- 查看日历缓存
SELECT * FROM wa_memories WHERE memory_key='calendar_cache_date';
SELECT * FROM wa_memories WHERE memory_key='calendar_cache_events';

-- 查看待触发提醒
SELECT * FROM wa_reminders WHERE fired=0 ORDER BY remind_at;

-- 查看最近消息
SELECT id, direction, body, created_at FROM wa_messages ORDER BY id DESC LIMIT 10;
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
- **修复：** 包裹 try/except
- **commit：** `b895583`

#### 4. Location 自动更新
- **文件：** `wa_agent.py` `extract_location_from_text` + `maybe_update_user_location`（~907-971行）
- **修复：** LLM 判断消息中是否透露位置 → 存入 `wa_memories` (memory_key=`current_location`)
- **commit：** `b6916f3`

#### 5. Memory Admin Page P1 UI 优化（已上线）
- **文件：** `susu-memory-admin.html`
- **commit：** `135f73f`
- **内容：** 重要性星级选择器、展开/折叠、批量选择删除、搜索高亮

### 2026-04-03 修复（已上线）

#### 1. normalize_key 过度规范化（已修复）
- **文件：** `wa_agent.py` `normalize_key`（~4314行）
- **问题：** `re.sub(r"[^\w\u4e00-\u9fff]+", "", value)` 把 "I love you" 和 "IloveYou" 都变成 "iloveyou"
- **修复：** 只合并空格和常见分隔符 `[\s\-_.,!?~]+`
- **commit：** `6ebd660`

#### 2. Memory Extraction 节流（已修复）
- **文件：** `wa_agent.py` `maybe_extract_memories`
- **问题：** 每次回复都触发 LLM 抽取记忆，浪费资源
- **修复：** 加 `_last_memory_extraction` + `_MEMORY_EXTRACTION_COOLDOWN=300s`
- **commit：** `6ebd660`

#### 3. Location 归档查询时间标记（已扩展）
- **文件：** `wa_agent.py` `ARCHIVE_LOOKUP_TIME_MARKERS`（~489行）
- **已添加：** 上次系列（上次/上次到/上次去）、广东话/普通话过去时（尋晚/尋日/琴晚/琴日/頭先）、大陆用语（昨天/前天/大前天/前几日/前幾天）
- **commit：** `5883876`

#### 4. Location Prompt 改为简体中文 + Bug 修复
- **文件：** `wa_agent.py` `extract_location_from_text` + `maybe_update_user_location`
- **问题 1：** Prompt 是繁体粤语，用户说普通话，LLM 被混合语言干扰
- **修复 1：** Prompt 改简体中文，加入常见位置变化表达示例
- **问题 2：** `current == detected` 比较 dict 和 string，永不相等
- **修复 2：** 改为 `current.get("content") == detected`
- **问题 3：** `clean_text(None)` 返回 "None" 字符串发给 LLM
- **修复 3：** 函数开头加 `if not text: return None`
- **commit：** `620cae2`

#### 5. 放假记忆自动触发
- **文件：** `wa_agent.py` `maybe_update_user_location`
- **逻辑：** 当用户位置不是香港/深圳时，自动追加一条 `kind='holiday'` 的长期记忆
- **内容：** "用戶在放假期，目前在外地：{地點}"
- **条件：** `detected not in HK_LOCATION_ALIASES and detected not in ("深圳", "香港", "澳門")`
- **commit：** `7846fd6`

#### 6. Session Memory Renewal（手动续期）
- **文件：** `susu_admin_core.py` + `susu_admin_server.py` + `susu-memory-admin.html`
- **新 API：** `POST /memory/renew-session` — 将 session 记忆的 `expires_at` 往后推 7 天
- **UI：** 卡片操作栏 🔄 按钮 + 批量「续期所选」按钮（仅短期记忆 tab 显示）
- **commit：** `5b44951`

#### 7. Archive → Long-term Promotion（归档提升为长期）
- **文件：** `susu_admin_core.py` + `susu_admin_server.py` + `susu-memory-admin.html`
- **新 API：** `POST /memory/promote-archive` — 从 `wa_memory_archive` 读取 → 写入 `wa_memories` → 删除 archive
- **UI：** 卡片操作栏 ⬆ 按钮 + 批量「提升为长期」按钮（仅归档 tab 显示）
- **commit：** `5b44951`

#### 8. Memory Admin UI 全面改版（已上线）
- **文件：** `susu-memory-admin.html`
- **卡片结构重组：** 顶栏（checkbox + importance + source badge）+ 分隔线 + 内容预览 + 底部时间
- **响应式：** 500px breakpoint（summary 2列、按钮44×44px、batch toolbar flex-wrap）+ 360px breakpoint（summary 1列、batch toolbar 竖向堆叠）
- **内容摘录：** 超过 150 字符自动截断 + 「全文」按钮展开/收起
- **Special Badges：** 🎙️語音模式（紫色）+ 📍位置（绿色）用于 `memory_key='voice_mode'` 和 `current_location`
- **commit：** `c648a0f`

#### 9. Google Calendar 日历系统（已上线）
- **文件：** `wa_agent.py`
- **新增函数：**
  - `parse_ical_events(ical_text)` — iCal 解析，含 RRULE 每周展开 + EXDATE 排除
  - `get_calendar_events_cached(conn, wa_id)` — 每日缓存（wa_memories 里检查日期）
  - `detect_semester_period(events)` — 从课程事件推断（考試週 > 學期中 > 假期中）
  - `get_today_holiday()` — HK 公众假期判断
- **统一接口：** `memory_block` 新增 `calendar_events`、`today_holiday`、`semester_period`、`today_date`
- **System Prompt 效果：**
  ```
  IMPORTANT SYSTEM DATE: Today is 2026-04-03 (星期五).
  學期狀態：學期中
  今日公眾假期：無
  今日日程：
    📅 今日 13:00 MNE2029
    📅 今日 20:00 MNE2110
  未來日程（7天）：
    📅 4/6（一）12:00 MNE2036
  ```
- **HK 公众假期：** `_HK_HOLIDAYS_2026` + `_HK_HOLIDAYS_2027`（繁体，来源：Google HK Holiday Calendar iCal）
- **环境变量：** `WA_USER_ICAL_URL`（见下方环境变量章节）
- **commit：** `686bb3d`

#### 10. 今日日期注入 System Prompt（持续修复中）
- **文件：** `wa_agent.py` `build_structured_context_from_runtime_context`（~6258行）
- **目标：** 让 Susu 始终知道今天是几号，不会乱猜
- **注入位置：** System prompt 第一行，用 `IMPORTANT SYSTEM DATE` 前缀 + ISO 格式 + 中英双语
- **历史修复：**
  - `7ef012b`：首次加入日期（放在 style_window_text，位置错误）
  - `f77c3de`：移到统一接口（calendar system 里，memory_block.today_date）
  - `4cfe961`：日期移到第一行 + 强制指令
  - `c91910a`：用 ISO 格式 + IMPORTANT 前缀 + MUST instruction

---

## 苏苏记忆管理页面

**访问：** `http://{Tokyo IP}/susu-memory-admin.html`

### 功能总览

| Tab | 功能 |
|-----|------|
| 長期記憶 | 查看/编辑/删除/批量删除长期记忆，importance 选择器 |
| 短期記憶 | 查看/续期/删除，批量续期（🔄）+ 批量删除 |
| 歸檔記憶 | 查看/提升为长期（⬆）+ 批量提升 + 批量删除 |
| 提醒事項 | 查看/编辑/删除提醒 |
| 苏苏設定 | Susu 系统设置 |

### API 端点

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/susu-admin/memory` | GET | 获取所有记忆数据 |
| `/memory/update` | POST | 更新记忆（content + importance） |
| `/memory/delete` | POST | 删除记忆（支持 type=memory/session/archive） |
| `/memory/create` | POST | 创建新记忆 |
| `/memory/deduplicate` | POST | 合并重复长期记忆 |
| `/memory/renew-session` | POST | 续期短期记忆 7 天 |
| `/memory/promote-archive` | POST | 将归档记忆提升为长期 |

### UI 快捷操作

- **展开全文：** 点击 ⬇ 按钮或「全文」文字按钮
- **编辑记忆：** 点击 ✏️ 按钮（弹窗可修改内容 + importance 星级）
- **Importance 星级：** 点击 1-5 个星星（满星 5 星）
- **系统记忆 Badge：** 🎙️語音模式（紫色）+ 📍位置（绿色）
- **批量选择：** 勾选卡片左侧复选框，底部出现批量操作栏
- **搜索高亮：** 输入关键词匹配的文本会高亮显示

---

## 历史修复

### GROQ API Key 问题
- **旧 Key（已失效）**
- **新 Key：** 在 `/etc/wa-agent.env` 中的 `WA_GROQ_API_KEY`

### Whisper 请求绕过 Cloudflare WARP 拦截
- **问题：** Tokyo VPS 通过 WARP TUN 模式时 GROQ 被 403
- **解决：** Whisper 改走 Cloudflare Worker `https://relay-proxy.simonding711.workers.dev/openai/v1/audio/transcriptions`

### REDSOCKS iptables 规则导致 HTTPS 失败
- **问题：** redsocks 装的 iptables 规则在 WARP 关闭后仍拦截 TCP 流量
- **解决：** 清除了 REDSOCKS 的 iptables 规则

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
| `WA_USER_ICAL_URL` | 用户 Google Calendar iCal URL（2026-04-03 新增）|

---

## 故障排查

### wa-agent 无响应

```bash
curl http://127.0.0.1:9100/health
journalctl -u wa-agent --no-pager -n 50
python3 -m py_compile /var/www/html/wa_agent.py
systemctl restart wa-agent
ps aux | grep wa_agent.py | grep -v grep
```

### 语音消息没有回复

1. 检查 DB：`SELECT * FROM wa_messages WHERE message_type='audio' ORDER BY id DESC LIMIT 5;`
2. 检查 outbound：`SELECT * FROM wa_messages WHERE direction='outbound' ORDER BY id DESC LIMIT 10;`
3. 检查日志：`journalctl -u wa-agent --no-pager | grep -i audio`

### 主动消息没有触发

```bash
curl http://127.0.0.1:9100/health | grep proactive
systemctl status wa-agent
```

### 数据库锁定

```bash
lsof /var/www/html/wa_agent.db
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
| Cloudflare Worker | `https://relay-proxy.simonding711.workers.dev` | Whisper 路由 |
| Google Calendar iCal | `simonding711@gmail.com` 私人日历（WA_USER_ICAL_URL）|

---

## 长洲照片 API（独立服务）

**仓库：** `SimonD0711/simond-photo-api`
**部署路径：** `/var/www/simond-photo-api/`
**服务名：** `cheungchau-api`

```bash
systemctl restart cheungchau-api
systemctl status cheungchau-api
journalctl -u cheungchau-api --no-pager -n 50
```
