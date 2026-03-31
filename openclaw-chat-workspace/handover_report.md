# 苏苏 WhatsApp Agent 交接报告
**编写时间**：2026-03-30 19:06 GMT+8
**编写人**：OpenClaw 本地 Agent

---

## 一、系统概览

- **Tokyo 服务器**（139.180.196.141）
- **WhatsApp Agent**：`/var/www/html/wa_agent.py`（主程序）+ SQLite 数据库 `/var/www/html/wa_agent.db`
- **系统服务**：`wa-agent`（systemd，配置文件 `/etc/systemd/system/wa-agent.service`）
- **环境变量**：`/etc/wa-agent.env`
- **Claude Code 配置**：`/home/claude-runner/.claude/settings.json`

---

## 二、今天完成的主要修改

### 1. Claude Code 模型配置（Tokyo 服务器）

**文件**：`/home/claude-runner/.claude/settings.json`

**现状**：Claude Code 已配置直连 MiniMax-M2.7，**不再使用 relay**。

```json
{
  "effortLevel": "high",
  "env": {
    "ANTHROPIC_API_KEY": "sk-cp-LBPSaJK0uyc8g6_bhF1Ui2roUMFQ_O8LvkUB9Q0XhrIYtlsAe_q4Qu4wktgMCJBxfYgbPN8Kim5VVS44LjAYMcHX3Ll62x0OT4ks9l6pZo1DuDBULW7-I3I",
    "ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic",
    "ANTHROPIC_MODEL": "MiniMax-M2.7",
    "ANTHROPIC_VERSION": "2023-06-01"
  }
}
```

**注意**：
- `api.minimaxi.com/anthropic` 端点支持 Claude API 格式，MiniMax-M2.7 可用
- Claude Code 进程如需重启：`sudo -u claude-runner bash -c 'cd ~ && nohup claude --no-input > /home/claude-runner/.claude/claude-restart.log 2>&1 &'`
- Claude Code 进程如需停止：`kill $(ps aux | grep 'claude.*-p' | grep -v grep | awk '{print $2}')`

---

### 2. 苏苏语音模式多次发送问题

**文件**：`/var/www/html/wa_agent.py`

**问题**：语音模式下每次回复会调用 `generate_model_text` 两次，导致连发多条语音。

**修复位置**：`generate_reply()` 函数（约 line 5721）
- 如果第一次回复已经完整（非碎片化），直接进入语音模式处理，跳过第二次模型调用
- 碎片判断逻辑大幅放宽：`looks_fragmentary()` 只在真正碎片（< 4 字符、以连接词开头等）时才触发 repair

---

### 3. 长期记忆误存语音模式偏好

**文件**：`/var/www/html/wa_agent.py`

**问题**：用户说"想关掉语音模式"被存为长期记忆，不应该。

**修复**：在 `is_long_term_memory_candidate()` 加了黑名单过滤：
```python
ephemeral_markers = ("語音模式", "voice mode", "關掉語音", "開語音", "語音回覆", "語音回復", "語音畀", "AI講", "AI發語音")
if any(m in value for m in ephemeral_markers):
    return False
```

同时删除了数据库里已有的错误记忆。

---

### 4. Recovery Loop 无限刷屏 Bug

**文件**：`/var/www/html/wa_agent.py`

**问题根因**：`load_pending_inbound_batch` 判断"最新 outbound ID"时，只算 `message_type='text'`，不包含 `claude_code` 类型的 streaming 消息。导致每次 recovery scan 都认为有未处理消息，无限循环。

**两处修复**：

1. `load_pending_inbound_batch()`：查询改成 `message_type IN ('text', 'streaming_done')`
2. `recover_pending_reply_contacts_once()`：同样把 `message_type = 'text'` 改为 `message_type IN ('text', 'streaming_done')`
3. streaming 完成后：将 `claude_code` 消息标记为 `streaming_done`

---

### 5. Susu Memory Admin 后台——置顶记忆

**文件**：`/var/www/html/susu-memory-admin.html`

**功能**：在"长期记忆"标签页，`memory_key` 为 `current_location` 和 `voice_mode` 的记忆条目：
- 显示"置頂"绿色标签
- 编辑按钮替换为 🔒（不可编辑）
- 删除按钮直接隐藏

**CSS 也已加入**：
```css
.entry-tokens.pinned { background: rgba(17,108,77,0.15); color: var(--success); }
.entry-card.pinned { border-color: rgba(17,108,77,0.35); background: rgba(17,108,77,0.04); }
```

**注意**：`current_location` 记忆的 `memory_key` 之前存的是 `'香港九龙九龙塘'`（内容本身），已修复为 `'current_location'`。

---

### 6. 引用消息时 Susie 完全不回消息

**文件**：`/var/www/html/wa_agent.py`

**问题**：
1. `load_pending_inbound_batch` 没有调用 `enrich_rows_with_quote_context`，导致 Susie 看不到被引用的原始消息内容
2. `build_combined_user_input` 里引用了未定义的变量名（`pending_rows` 应为 `rows`）

**修复**：
1. `load_pending_inbound_batch` 返回前调用 `enrich_rows_with_quote_context(conn, wa_id, rows)`
2. 修正变量名：`pending_rows` → `rows`
3. 在 prompt 里加了对被引用消息的描述：`format_quote_context_tag(latest)` 输出 `[对方呢句係回覆緊 {内容}]`

---

### 7. 联网搜索——DuckDuckGo 替换为 Tavily

**文件**：`/var/www/html/wa_agent.py`

**变化**：
- `search_duckduckgo_web()` → `search_tavily_web()`
- Tavily API Key 从 `/etc/wa-agent.env` 读取（`TAVILY_API_KEY=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`）
- 添加了辅助函数 `_load_env_var()` 直接读 `/etc/wa-agent.env`
- `fetch_live_search_results()` 里的 `provider_loaders` 也从 DuckDuckGo 改为 Tavily

---

### 8. 天气查询关键词——加入"打風/颱風/台风"

**文件**：`/var/www/html/wa_agent.py`

**变化**：`WEATHER_QUERY_KEYWORDS` 加入：
- "打風"、"打风"、"颱風"、"台风"

之前"而家香港有冇打風"不被识别为天气查询，错误走 Tavily 搜索。

---

### 9. SQLite 并发锁问题（database is locked）

**文件**：`/var/www/html/wa_agent.py`

**问题**：`sqlite3.connect()` 默认 `busy_timeout=0`，多线程并发读写时直接报 `database is locked`，`process_pending_replies_for_contact` 线程直接崩溃，导致 Susie 完全不回消息。

**修复**：三处数据库连接都加了：
```python
conn.execute("PRAGMA busy_timeout = 5000")
```
受影响的位置：
- `load_runtime_settings_from_db()`（line ~505）
- `get_db()`（line ~2325）
- `get_latest_inbound_id_for_wa()`（line ~3585）

---

## 三、待处理 / 观察中

1. **Opus 联网搜索**：Claude Opus 4 有原生 `WebSearch` 工具，但 MiniMax relay 可能不支持。如需在 Susie 上启用，需要加 MCP 或其他方案。

2. **Claude Code 重启后新 session 才生效配置**：改了 `settings.json` 后需要重启 Claude Code 进程才能读取新配置。

---

## 四、快速参考

### 重启 wa-agent
```bash
systemctl restart wa-agent
```

### 查看 wa-agent 状态和日志
```bash
systemctl status wa-agent --no-pager
journalctl -u wa-agent --no-pager -n 50
```

### 停止 Claude Code
```bash
kill $(ps aux | grep 'claude' | grep -v grep | awk '{print $2}')
```

### 重启 Claude Code（后台常驻）
```bash
sudo -u claude-runner bash -c 'cd ~ && nohup claude --no-input > /home/claude-runner/.claude/claude-restart.log 2>&1 &'
```

### 数据库查询示例（查看最新消息）
```bash
python3 -c "
import sys; sys.path.insert(0, '/var/www/html')
from wa_agent import *
conn = get_db()
rows = conn.execute('SELECT id, direction, body FROM wa_messages ORDER BY id DESC LIMIT 10').fetchall()
for r in rows: print(r)
conn.close()
"
```

### 读取 wa-agent 环境变量
```bash
cat /etc/wa-agent.env
```
