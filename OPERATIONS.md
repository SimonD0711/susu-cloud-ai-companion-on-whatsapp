# 苏苏（Susu）WhatsApp 聊天机器人 — 生产运维手册

> **最后更新：2026-04-04** | 架构版本：v4（含短期记忆全面重构 + 反馈机制 + 时间桶修复）

**定位：** 本文件是当前项目唯一的人工维护生产运维手册。生产部署、链路切换、回滚、排障、后台入口与关键环境变量，统一以本文件为准。

---

## 当前生产链路

### 回复链路（线上实际状态）

- **普通聊天：** `relay + claude-opus-4-6`
- **联网搜索：** `Cloudflare AI Gateway + Anthropic native /messages + claude-opus-4-6 + web_search`
- **搜索意图判断：** `MiniMax Router (MiniMax-M2.5-highspeed)`
- **语音转写：** `Groq Whisper via Cloudflare Worker`
- **语音回复：** `MiniMax TTS`

### 回复控制机制

- 每个 `wa_id` 有一个 reply worker
- 每轮正式生成回复时会拉起一个独立 reply subprocess
- 如果回复发出前又收到同联系人新消息，旧 subprocess 会被标记过时并终止，再按最新上下文重算
- 这保证不会发出明显过期回复，但对慢模型/搜索链路会增加重算成本
- 回复子进程现已加总超时保护：默认 `WA_REPLY_GENERATION_TIMEOUT_SECONDS=55`，超时会终止子进程并返回 fallback，避免单次回复卡十几分钟
- 聊天档案回填已移出热路径：`get_db()` 不再每次顺手扫历史库，改成后台 `archive_backfill_loop()` 线程异步回填/补链接

### 上下文增强（线上实际开启）

- **MiniMax Router：** 每条文本消息先判断 `should_search` / `use_previous_context` / `needs_history_recall`
- **历史回看：** 命中时会把 recent history 从 12 条扩大到 36 条，并从 `wa_messages` 中召回更相关旧对话
- **引用消息展开：** 如果用户引用较早消息，会把该条被引用消息的完整正文直接注入 prompt
- **回复质检：** 最终回复前会做一层轻量质检，优先修正第三人称称呼、奇怪标点、过早装不知道

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
| `record_batch_side_effects` | ~6725 | 回复后副作用（含轮次触发提取） |
| `process_pending_replies_for_contact` | ~7050 | Reply worker 主循环 |
| `spawn_reply_generation_subprocess` | ~6500 | 启动 reply subprocess |
| `ensure_reply_worker_running` | ~7084 | 触发 reply worker 线程 |
| `recover_pending_reply_contacts_once` | ~7091 | 恢复扫描（包含 audio 联系人） |
| `maybe_extract_memories` | ~5074 | LLM 抽取长期记忆（含全局冷却） |
| `maybe_extract_session_memories` | ~5258 | LLM 抽取短期记忆（追加每日日志，含轮次触发） |
| `upsert_daily_log` | ~5211 | 追加句子到每日日志，按句去重 |
| `promote_to_long_term` | ~5240 | 提升到长期记忆（含相似度去重） |
| `_should_trigger_session_extraction` | ~6711 | 轮次触发判断（每3轮/20分钟） |
| `heuristic_extract_session_memories` | ~5135 | 启发式短期记忆回退（已修复碎片化 + infer_observed_at） |
| `infer_observed_at_from_text` | ~4058 | 从时间词推断事件实际发生时间 |
| `bump_session_memory_use_count` | ~4630 | 追踪记忆被引用次数，>=5次延长TTL |
| `upsert_session_memory` | ~4599 | 写入短期记忆（支持 memory_type + use_count） |
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

### 当前运行文件与真实配置

- **主进程文件：** `/var/www/html/wa_agent.py`
- **数据库：** `/var/www/html/wa_agent.db`
- **生产环境变量：** `/etc/wa-agent.env`
- **日志：** `/var/log/wa_agent.log`
- **systemd 名称：** 文档内习惯写 `wa-agent`，但现场也可能是手动 nohup 进程；以 `ps aux | grep wa_agent.py` 结果为准

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

### 当前推荐部署步骤（以现场为准）

```powershell
# 本地改完后直接 SCP 覆盖
scp -P 2222 C:\Users\ding7\Documents\susu-cloud\wa_agent.py root@Tokyo:/var/www/html/wa_agent.py

# SSH 到 Tokyo 检查语法并重启
ssh -p 2222 root@Tokyo
python3 -m py_compile /var/www/html/wa_agent.py
pkill -f wa_agent.py
nohup /usr/bin/python3 /var/www/html/wa_agent.py > /var/log/wa_agent.log 2>&1 &
ps aux | grep wa_agent.py | grep -v grep
```

### 不要依赖的假设

- 不要假设 Tokyo 可访问 GitHub
- 不要假设 `systemctl restart wa-agent` 一定存在
- 不要假设 `src/` 模块化代码就是生产实际运行代码
- 生产真实行为以 `/var/www/html/wa_agent.py` 为准

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

## v2.1.0 改动记录（2026-04-03）

### 1. 短期记忆时间桶分类修复（「昨天吃了包子」问题）
- **文件：** `wa_agent.py` `classify_recent_memory_bucket` + `infer_observed_at_from_text`（新增 ~4058行）
- **问题：** "昨天吃了包子" 被错误分到 `within_24h`，而非正确的 `within_3d`
- **修复：**
  - LLM 提示词强化：明确告诉模型时间词指事件发生时间而非说话时间
  - 新增 `infer_observed_at_from_text()` 从时间词推断事件实际发生时间
  - `split_memory_clauses()` 不再拆分含时间标记的完整句子（避免碎片化）
  - `upsert_session_memory()` 支持传入 `observed_at` 参数

### 2. normalize_key 规范化统一
- **文件：** `wa_agent.py` `normalize_key`（~3041行）、`proactive.py` `_normalize_key`、`db.py` `_normalize_key`
- **修复：** `re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]", "", value)` 移除中文标点，避免「今日約咗朋友。」和「今日約咗朋友」被识别为不同记忆

### 3. 死代码清理
- **文件：** `wa_agent.py`
- **删除：** `extract_live_search_question_memory`（从未被调用）

### 4. Rate Limiting
- **文件：** `wa_agent.py` `maybe_extract_session_memories`
- ~~新增 per-wa-id 冷却机制~~ → 已移除，提取为后台副作用不阻塞对话，每条消息均可触发

### 5. 记忆反馈机制
- **文件：** `wa_agent.py` `bump_session_memory_use_count`、`select_relevant_memories`、`proactive.py` `_bump_use_count`
- **DB：** 新增列 `memory_type`（DEFAULT 'event'）、`use_count`（DEFAULT 0）
- **行为：** 被引用 ≥5 次的记忆自动延长 TTL 至 2 倍

### 6. 记忆应用闭环
- **文件：** `wa_agent.py`（回复 prompt）、`proactive.py`（主动提示 prompt）
- **回复：** 新增指令优先引用短期记忆（24h > 3d > 7d）
- **主动：** 明确优先用 24h 记忆，避免重复用同一条

### 7. 管理页面统计
- **文件：** `susu-memory-admin.html`、`susu_admin_core.py`
- **新增：** 本周新增记忆数、平均引用次数、未使用记忆数

### 8. 统一 memory.py
- **文件：** `src/wa_agent/memory.py` 全面更新，`RECENT_MEMORY_EXTRACTOR_PROMPT` 同步更新
- **新增：** `RECENT_24H_MARKERS`、`RECENT_3D_MARKERS`、`RECENT_7D_MARKERS`、`infer_observed_at_from_text`、`MemoryManager.infer_observed_at`

### 9. 测试覆盖
- **文件：** `tests/wa_agent/test_memory.py`
- **新增：** `infer_observed_at` / `classify_recent_memory_bucket` / `normalize_key` 集成测试

### 10. 数据库清理 SQL
- **文件：** `cleanup_session_memories.sql`
- 用途：查看/删除噪音短期记忆（超短内容、纯问候句、重复记忆、过期记忆）

### 11. Phase 3 Bug 修复：`get_date_offset` 未定义
- **文件：** `wa_agent.py` `maybe_extract_session_memories`
- **问题：** Prompt f-string 中引用 `get_date_offset()` 但该函数不存在，导致 `NameError`
- **修复：** 新增 `_date_offset(date_str, days)` 辅助函数（行 ~5199），替换 prompt 中的所有调用

### 12. Phase 4：轮次触发机制
- **文件：** `wa_agent.py` `record_batch_side_effects`、`_should_trigger_session_extraction`
- **行为：** `maybe_extract_session_memories` 改为按轮次触发（每 3 轮 OR 每 20 分钟）
- **状态变量：** `_session_extraction_state = {wa_id: {"turns": N, "last_at": timestamp}}`

### 13. Phase 5：句子级打分
- **文件：** `wa_agent.py` `score_memory_text`、`_score_text`（新增）
- **行为：** 多句子记忆按句拆分后取最高分，避免整段低分句拉低有效句子

### 14. Phase 6：Promote 相似度去重
- **文件：** `wa_agent.py` `promote_to_long_term`
- **行为：** 提升前检查与现有长期记忆的相似度（Jaccard 阈值 0.65），相似则跳过

### 15. 管理页面短期记忆显示修复
- **文件：** `susu_admin_core.py`、`susu-memory-admin.html`
- **问题：** `fetch_susu_memory` 把 `daily_log` 条目的 `bucket` 覆盖为时间计算的 `within_7d`，导致显示错误标签
- **修复：**
  - `SESSION_BUCKET_LABELS` 新增 `"daily_log": "每日日誌"`
  - `bucket` 赋值逻辑优先保留 `daily_log`
  - 统计新增 `daily_log_count`；前端显示加入日志计数

### 16. 每日日志排除 Q&A 对话
- **文件：** `wa_agent.py` `maybe_extract_session_memories` prompt
- **问题：** 苏苏的问题和 Simon 的回答被当成事件存入每日日志
- **修复：** Prompt 新增排除规则，Q&A 类型对话不存入每日日志

### 17. 每日日志每条带时间码
- **文件：** `wa_agent.py` `upsert_daily_log`
- **行为：** 每条存入日志的句子带 `HH:MM` 前缀，如 `14:32 對方啱啱食咗蛋糕`

### 18. 废弃 `maybe_extract_qa_turn_memory`
- **文件：** `wa_agent.py` `record_batch_side_effects`
- **原因：** Q&A 记忆产生碎片化记录，已由每日日志替代

### 19. 修复 `upsert_daily_log` 支持旧格式
- **文件：** `wa_agent.py` `upsert_daily_log`
- **问题：** 查询用 `memory_key='daily:xxx'`，但旧记录 `memory_key='within_7d:xxx'`，导致每日日志一直新开记录
- **修复：** 查询兼容旧格式 `memory_key LIKE 'daily:%'`，找到后更新并统一 bucket

### 20. 全局时区改为 HKT（+08:00）
- **涉及文件：** `wa_agent.py`、`db.py`、`memory.py`、`susu_admin_core.py`
- **改动：** `utc_now()` 改为返回 HKT；所有业务逻辑时间比较从 UTC 统一为 HKT；`observed_at`/`created_at`/`expires_at` 存储为 `+08:00`
- **DB migration：** `migrate_timezone.py` — 所有表时间列 +8h，`+00:00` → `+08:00`；`fix_tz2.py` — 修正时区后缀

### 2026-04-04 改动

#### 1. LLM Provider 切换为 OpenRouter
- **变更：** Relay API Key 从旧 relay key 改为 OpenRouter key（均已脱敏，不在文档中记录明文）
- **Base URL：** 从 `https://apiapipp.com/v1` 改为 `https://openrouter.ai/api/v1`
- **模型：** 改用 OpenRouter 格式 ID
  - Primary：`claude-opus-4-6` → `anthropic/claude-opus-4.6`
  - Fallback：`claude-sonnet-4-6` → `anthropic/claude-sonnet-4`
- **配置文件：** `/etc/wa-agent.env`（生产）、`.env.openrouter` / `.env.relay`（本地 Git）
- **切换方法：** `cp .env.openrouter .env` 或 `cp .env.relay .env`，然后重启服务

#### 2. Relay 请求头改为可配置
- **变更：** `wa_agent.py` 与 `src/ai/llm/relay.py` 支持自定义主认证头、额外认证头、可选 `User-Agent`
- **新增环境变量：** `WA_RELAY_AUTH_HEADER`、`WA_RELAY_AUTH_TOKEN`、`WA_RELAY_EXTRA_AUTH_HEADER`、`WA_RELAY_EXTRA_AUTH_TOKEN`、`WA_RELAY_USER_AGENT`
- **用途：** 为 Cloudflare AI Gateway 这类要求 `cf-aig-authorization` 的兼容网关预留接入位，不再硬编码 `Authorization: Bearer ...`
- **现状：** 当前生产普通聊天继续走原 relay；Cloudflare Anthropic native 改走独立搜索链路

#### 3. 主聊天链路支持 Anthropic Native + Claude Web Search
- **变更：** `wa_agent.py` 新增 Cloudflare AI Gateway Anthropic native `/messages` 调用，主模型可切到 `claude-opus-4-6`
- **当前实际用法：** 普通聊天继续走 `relay + claude-opus-4-6`；联网搜索改走 `Cloudflare AI Gateway + Anthropic native /messages + claude-opus-4-6 + web_search`
- **搜索策略：** 搜索分流命中后，Claude 原生 `web_search_20250305` tool 由 Opus 自行判断是否真的搜索
- **旁路：** 旧 Tavily/Bing/DuckDuckGo 搜索执行链路已被 Anthropic native 搜索优先替代，但本地搜索规划/回退逻辑仍保留

#### 4. MiniMax Router 接管搜索意图判断
- **变更：** 每条文本消息现在先走 `MiniMax` 轻量 Router，而不是先靠关键词规则判定是否搜索
- **接口：** `https://api.minimaxi.com/v1/text/chatcompletion_v2`
- **当前模型：** `MiniMax-M2.5-highspeed`
- **作用：** Router 负责输出 `should_search`、`mode`、`use_previous_context`、`needs_history_recall`、`reply_task_type`，搜索分流和上下文回看由它驱动
- **回退：** 如果 MiniMax Router 超时、返回坏 JSON 或失败，会回退到旧规则逻辑

#### 5. 历史回看与引用消息增强
- **变更：** 当 Router 判断 `needs_history_recall` 或 `use_previous_context` 时，`build_runtime_context()` 会把 recent history 窗口从 12 条扩到 36 条，并从 `wa_messages` 中挑选相关旧对话注入 `Recovered older chat context`
- **引用消息：** 如果用户引用一条较早消息，系统会读取该条被引用消息的完整正文，而不只是短 preview，再注入 prompt
- **效果：** 处理「昨天那个呢」「你帮我搜嘛」「引用昨天消息再追问」这类上下文依赖场景时，不再只依赖短期记忆

#### 6. 本地聊天档案层（原话优先）
- **模块：** `chat_archive.py`
- **表：** `wa_message_archive`、`wa_message_links`
- **写入：** 新消息入站/出站会双写到档案表；旧 `wa_messages` 会自动回填到档案表
- **用途：** 回复前优先按 `message_id`、日期、原话记录查询，而不是先看摘要
- **日期回看：** 用户说 `昨天/前天/今日/噚日/昨日` 时，会优先注入当天原话；现已支持 `4.3`、`4/3`、`4月3号` 这类显式日期
- **限制：** 如果 WhatsApp webhook 当时没有给出 `context.id`，而且原话本身也不在本地库里，就无法做到 100% 精确还原

#### 7. 搜索回复格式与轻量质检
- **变更：** `normalize_live_search_reply()` 不再把多行硬拼成大量 `；`，会收敛成更自然的逗号/空格句式
- **代词修正：** 搜索提示与回复质检会尽量把对用户的称呼固定成 `你`，避免把用户说成 `佢`
- **Reply Critic：** 主回复结束后会经过一层轻量质检，优先修复：奇怪标点、把用户说成第三人称、明明可接住语境却过早装不知道

#### 8. 记忆层改为轻量 LLM 主导
- **长期记忆提取：** `maybe_extract_memories()` 现改走 `MiniMax Router` 级别的轻量调用，不再用主回复模型做后台记忆分类
- **短期记忆 / 每日日志提取：** `maybe_extract_session_memories()` 与 `backfill_daily_log_for_date()` 也改走轻量模型
- **关键改动：** 已停掉 `daily log -> promote_to_long_term()` 这条污染链路；每日日志不再自动升长期
- **当前策略：** 轻量模型负责判断“该不该记 / 记到哪一层”，本地规则只保留去重、敏感过滤、时间性事件兜底
- **已清理的伪长期记忆：** 例如“噚日中午飲咗白酒”“在外地长岭”“闯红灯”等最近事件，已从长期记忆移除

#### 9. 位置理解优先保留具体地点
- **变更：** 位置抽取 prompt 改为优先保留用户原话中的最具体层级位置，避免把 `长岭县太平山镇` 简化成 `长岭` 或 `姥姥家`
- **覆盖策略：** 如果新识别到的位置更泛，不会降级覆盖当前更具体的位置
- **主号相对地点规则：**
  - `姥姥家` -> `长岭县太平山镇`
  - `太奶家` -> `长岭县`
  - `我家`：前文讲长春时 -> `长春市南关区`；前文讲珠海时 -> `珠海市金湾区`
  - `宿舍` / `学校` -> `香港九龙塘`

#### 10. 主动消息改成规则 + LLM 决策
- **修复：** `src/wa_agent/proactive.py` 现改为优先从环境变量读取 `WA_ACCESS_TOKEN / WA_PHONE_NUMBER_ID`，不再因为数据库设置缺失而整条主动消息链路失效
- **触发逻辑：** 保留硬规则门槛（静默时间、cooldown、每日上限、是否仍在等待对方回复）
- **去掉随机抽签：** eligible 后不再按 `probability` 随机发
- **LLM 决策：** 由 `MiniMax Router` 判断 `should_send / confidence / topic / tone / reason`
- **正文生成：** 最终 draft 仍然交给 `relay + claude-opus-4-6`

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

关键配置在 `/etc/wa-agent.env`（systemd 读取）。

**LLM Provider 切换：** 本地 Git 仓库有切换脚本和配置文件：
- `.env.openrouter` — OpenRouter 配置
- `.env.relay` — 原 relay 配置
- 切换方法：`cp .env.openrouter .env` 或 `cp .env.relay .env`，然后重启服务

| 变量 | 用途 |
|------|------|
| `WA_ACCESS_TOKEN` | WhatsApp API Token |
| `WA_PHONE_NUMBER_ID` | WhatsApp Phone Number ID |
| `WA_GRAPH_VERSION` | Graph API 版本（当前 v22.0）|
| `WA_RELAY_API_KEY` | LLM Relay API Key |
| `WA_RELAY_AUTH_HEADER` | Relay 主认证头名，默认 `Authorization` |
| `WA_RELAY_AUTH_TOKEN` | Relay 主认证头值，留空时自动使用 `Bearer ${WA_RELAY_API_KEY}` |
| `WA_RELAY_EXTRA_AUTH_HEADER` | Relay 额外认证头名（如 `cf-aig-authorization`） |
| `WA_RELAY_EXTRA_AUTH_TOKEN` | Relay 额外认证头值 |
| `WA_RELAY_USER_AGENT` | Relay 自定义 User-Agent |
| `WA_RELAY_MODEL` | LLM 模型名（默认 claude-opus-4-6）|
| `WA_ANTHROPIC_GATEWAY_BASE_URL` | Cloudflare AI Gateway Anthropic base URL，形如 `https://gateway.ai.cloudflare.com/v1/<account>/<gateway>/anthropic/v1` |
| `WA_ANTHROPIC_GATEWAY_TOKEN` | Cloudflare AI Gateway token（用于 `cf-aig-authorization`） |
| `WA_ANTHROPIC_MODEL` | Anthropic native 主模型，当前建议 `claude-opus-4-6` |
| `WA_ANTHROPIC_VERSION` | Anthropic API version，默认 `2023-06-01` |
| `WA_ANTHROPIC_USER_AGENT` | Anthropic native 请求使用的 User-Agent |
| `WA_ANTHROPIC_WEB_SEARCH_ENABLED` | 是否默认为每次主聊天请求附带 Claude web_search tool |
| `WA_ANTHROPIC_WEB_SEARCH_MAX_USES` | Claude web_search 单次请求最大搜索次数 |
| `WA_ROUTER_ENABLED` | 是否启用 MiniMax 轻量 Router |
| `WA_ROUTER_API_KEY` | MiniMax Router API Key |
| `WA_ROUTER_BASE_URL` | MiniMax Router base URL，当前 `https://api.minimaxi.com` |
| `WA_ROUTER_MODEL` | MiniMax Router 模型，当前线上为 `MiniMax-M2.5-highspeed` |
| `WA_GROQ_API_KEY` | Groq API Key（当前有效）|
| `WA_MINIMAX_API_KEY` | MiniMax TTS API Key |
| `WA_GEMINI_API_KEY` | Gemini API Key |
| `WA_PROACTIVE_ENABLED` | 主动消息开关 |
| `WA_ADMIN_WA_ID` | 管理员 WhatsApp ID |
| `WA_USER_ICAL_URL` | 用户 Google Calendar iCal URL（2026-04-03 新增）|

---

## 第三方服务清单

本节是生产依赖的后台/平台总表。**密钥值本身不写在文档里**，统一以 `/etc/wa-agent.env`、平台控制台或服务器现场为准。

| 服务 | 当前用途 | 当前状态 | 核心入口 / 备注 |
|------|------|------|------|
| WhatsApp Cloud API | 主消息收发 | 生产中 | 依赖 `WA_ACCESS_TOKEN`、`WA_PHONE_NUMBER_ID` |
| 原 relay (`apiapipp.com`) | 普通聊天主链路 | 生产中 | `WA_RELAY_BASE_URL=https://apiapipp.com/v1` |
| Cloudflare AI Gateway | Claude 原生搜索链路 | 生产中 | `https://gateway.ai.cloudflare.com/v1/<account>/<gateway>/anthropic/v1` |
| Anthropic via Cloudflare | `claude-opus-4-6` + `web_search` | 生产中 | 仅搜索分流使用，不是普通聊天主链路 |
| MiniMax Router | 每条消息意图判断 / 上下文回看信号 | 生产中 | `https://api.minimaxi.com/v1/text/chatcompletion_v2`，当前模型 `MiniMax-M2.5-highspeed` |
| Local chat archive | 原话档案 / 引用关系 / 日期回看 | 生产中 | `chat_archive.py` + `wa_message_archive` / `wa_message_links` |
| MiniMax TTS | 语音回复 | 生产中 | `WA_MINIMAX_API_KEY` / `WA_MINIMAX_BASE_URL` |
| Groq Whisper | 语音转写 | 生产中 | 通过 Cloudflare Worker 中转 |
| Cloudflare Worker `relay-proxy` | Whisper 转写代理 | 生产中 | `https://relay-proxy.simonding711.workers.dev/openai/v1/audio/transcriptions` |
| Google iCal | 日历上下文 | 可选 | `WA_USER_ICAL_URL` |
| OpenRouter | 旧实验链路 | 停用 | 账号可用但 Claude provider 受限，不作为生产依赖 |

### Cloudflare 相关后台

- **Account ID：** 已脱敏，现场以 Cloudflare Dashboard 或 `/etc/wa-agent.env` 为准
- **Gateway：** `default`
- **用途：** Anthropic native `/messages` 搜索链路
- **注意：** Cloudflare `compat/chat/completions` 的 Anthropic 模型名映射不稳定；生产搜索链路固定走 Anthropic native `/anthropic/v1/messages`

### MiniMax 相关后台

- **官网：** `https://www.minimaxi.com/`
- **开放平台：** `https://platform.minimaxi.com/`
- **Router 当前确认可用模型：** `MiniMax-M2.5`、`MiniMax-M2.5-highspeed`、`MiniMax-M2.7`、`MiniMax-M2`、`MiniMax-M2.1`（以 OpenAI-compatible 探测结果为准）
- **当前线上 Router：** `MiniMax-M2.5-highspeed`
- **注意：** `MiniMax-M2.5-High-Speed` 这种大小写/连字符写法无效；应使用 `MiniMax-M2.5-highspeed`

### OpenRouter 现状

- 新旧账号都验证过：`/auth/key` 可用，但 Claude provider 仍返回 `403 violation of provider Terms Of Service`
- 结论：OpenRouter 不再作为生产 Claude 路径

### 现场确认顺序

1. 先看 `/etc/wa-agent.env`
2. 再看 `OPERATIONS.md`
3. 最后再看平台控制台（Cloudflare / MiniMax / Meta）

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
| 服务器 | Tokyo VPS（公网 IP 已脱敏，现场以 SSH 配置或服务商控制台为准） |
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
