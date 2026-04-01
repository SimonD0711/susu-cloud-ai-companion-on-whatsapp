# Susu Cloud 统一 AI 能力层重构计划

最后更新：2026-04-01

---

## 背景与目标

把 `wa_agent.py`（6877 行单体）拆分为模块化统一 AI 能力层，支持多 Provider 切换。

### 重构目标
1. 所有 AI 能力（LLM、TTS、Whisper、搜索路由）统一入口
2. wa_agent.py 从 6877 行瘦身为纯入口文件（~50 行）
3. 删除 `susu_brain_bridge.py` / `susu_brain_backend.py` 两个独立服务（功能并入统一层）
4. 合并删除 `brain_adapter.py` / `agnai_backend_adapter.py`
5. 完整的单元测试 + Tokyo 冒烟测试覆盖

### 当前架构
```
wa_agent.py
  ├── 直接 Relay LLM 调用
  ├── MiniMax TTS 调用
  ├── Groq Whisper 调用
  ├── 12 种搜索 API 分散调用
  ├── should_use_brain_bridge() → brain_adapter.py → :9102
  │                                          └── susu_brain_bridge.py
  │                                              └── upstream_mode=agnai → :9103
  │                                                                      └── susu_brain_backend.py
  │                                                                          └── relay API
  └── 所有记忆/主动消息/提醒逻辑混杂
```

### 重构后架构
```
wa_agent.py (入口，~50行)
  └── src/wa_agent/
          ├── server.py, brain.py, memory.py, proactive.py, reminders.py,
          │   voice.py, whatsapp.py, db.py, auth.py, utils.py
          └── src/ai/
                  ├── config.py        ← 所有 AI 配置单点管理
                  ├── llm/            ← 统一 LLM 调用（Relay）
                  ├── tts/            ← 统一 TTS（MiniMax）
                  ├── whisper/        ← 统一 Whisper（Groq）
                  └── search/         ← 统一搜索路由 + 各搜索源
```

---

## PR 划分（按依赖顺序）

| PR | 内容 | 风险 | 状态 |
|----|------|------|------|
| #1 | `src/ai/config.py` + `src/ai/llm/` | 低 | 待做 |
| #2 | `src/ai/tts/` + `src/ai/whisper/` | 低 | 待做 |
| #3 | `src/ai/search/` | 中 | 待做 |
| #4 | `src/wa_agent/db.py` + `src/wa_agent/auth.py` | 低 | 待做 |
| #5 | `src/wa_agent/brain.py` + `src/wa_agent/memory.py` | 高 | 待做 |
| #6 | `src/wa_agent/proactive.py` + `reminders.py` + `voice.py` + `whatsapp.py` | 中 | 待做 |
| #7 | `src/wa_agent/server.py` + `utils.py`，wa_agent.py 改为入口 | 中 | 待做 |
| #8 | 删除 `susu_brain_bridge.py` + `susu_brain_backend.py` + 相关 systemd | 低 | 待做 |
| #9 | 删除 `brain_adapter.py` + `agnai_backend_adapter.py` | 零 | 待做 |

---

## 测试框架

### 安装
```bash
pip install pytest pytest-mock
```

### 目录结构
```
tests/
├── conftest.py                  # 全局 fixtures，强制测试环境变量
├── ai/
│   ├── test_config.py
│   ├── test_llm_manager.py
│   ├── test_prompts.py
│   ├── test_tts.py
│   ├── test_whisper.py
│   ├── test_search_router.py
│   ├── test_weather.py
│   ├── test_news.py
│   ├── test_music.py
│   └── test_web.py
├── wa_agent/
│   ├── test_db.py
│   ├── test_auth.py
│   ├── test_brain.py
│   ├── test_memory.py
│   ├── test_proactive.py
│   ├── test_reminders.py
│   ├── test_voice.py
│   ├── test_whatsapp.py
│   └── test_server.py
└── smoke/
    └── test_smoke_tokyo.py      # Tokyo 部署后冒烟测试
```

### conftest.py
```python
import os, pytest

os.environ["WA_RELAY_API_KEY"] = "test-key-for-unit-test"
os.environ["WA_RELAY_MODEL"] = "claude-opus-4-6"
os.environ["WA_RELAY_FALLBACK_MODEL"] = "claude-sonnet-4-6"
os.environ["WA_MINIMAX_API_KEY"] = "test-key"
os.environ["WA_GROQ_API_KEY"] = "test-key"
os.environ["WA_ADMIN_WA_ID"] = "85259576670"
os.environ["SUSU_BASE_DIR"] = "/tmp/susu-test"

@pytest.fixture
def ai_config():
    from src.ai.config import AIConfig
    return AIConfig()
```

### Tokyo 冒烟测试（每次 PR 合入后运行）
```python
# tests/smoke/test_smoke_tokyo.py
import urllib.request, json, subprocess

TOKYO = "your-tokyo-ip"
BASE_URL = f"http://{TOKYO}:9000"
ADMIN_URL = f"http://{TOKYO}:9001"

def test_wa_agent_health():
    resp = urllib.request.urlopen(f"{BASE_URL}/healthz")
    assert resp.status == 200

def test_susu_admin_login():
    data = json.dumps({"password": "Dingding0616"}).encode()
    req = urllib.request.Request(
        f"{ADMIN_URL}/api/susu-admin/login",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    resp = urllib.request.urlopen(req)
    assert json.loads(resp.read())["authenticated"] == True

def test_all_services_active():
    result = subprocess.run(
        ["ssh", "root@"+TOKYO, "systemctl", "is-active",
         "wa-agent", "susu-admin-api", "cheungchau-api"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert all(line == "active" for line in result.stdout.strip().split("\n"))
```

---

## PR #1：AI 配置层 + LLM 统一调用

### 目标
wa_agent.py 所有 LLM 调用改走 `AIConfig` + `LLMManager`，零业务逻辑改动。

### 新增文件
```
src/ai/__init__.py
src/ai/config.py         # 所有 AI 环境变量单点读取
src/ai/base.py           # 抽象基类
src/ai/llm/__init__.py
src/ai/llm/manager.py    # LLMManager：统一入口 + 重试 + 降级
src/ai/llm/relay.py      # RelayProvider
src/ai/llm/openai_compat.py  # 通用 OpenAI 兼容 Provider
src/ai/llm/prompts.py    # 所有 system prompt 集中管理
tests/ai/test_config.py
tests/ai/test_llm_manager.py
tests/ai/test_prompts.py
```

### wa_agent.py 改动点映射
| 原代码位置 | 改动 |
|-----------|------|
| wa_agent.py L78-79: `os.environ["WA_RELAY_API_KEY"]` | 删除，改从 `AIConfig` 读取 |
| wa_agent.py L4406: `generate_model_text()` 直接调用 relay | 改为 `LLMManager().chat(messages, model=RELAY_MODEL, ...)` |
| wa_agent.py L4432: `generate_lightweight_router_text()` | 同上 |
| wa_agent.py L4984: proactive LLM 调用 | 同上 |
| wa_agent.py L5234: reminder LLM 调用 | 同上 |
| wa_agent.py L4624: memory extraction LLM 调用 | 同上 |
| wa_agent.py L4726: session memory extraction LLM 调用 | 同上 |
| wa_agent.py L6105: QA turn memory synthesis | 同上 |
| wa_agent.py L6704: final retry | 同上 |
| wa_agent.py L65: `SUSU_LOCKED_RELAY_MODEL = "claude-opus-4-6"` 硬编码 | 删除，改从 `AIConfig.RELAY_MODEL` 读取 |

### 测试
```python
tests/ai/test_config.py          # 环境变量读取、默认值、缺失 Key 抛异常
tests/ai/test_llm_manager.py       # chat() 返回值、重试逻辑、fallback 模型切换
tests/ai/test_prompts.py           # 所有 prompt 字符串非空、不含敏感信息
```

### 验收标准
- [ ] `python -m py_compile src/ai/*.py src/ai/**/*.py` 无报错
- [ ] `pytest tests/ai/test_config.py tests/ai/test_llm_manager.py -v` 全部通过
- [ ] Tokyo `systemctl restart wa-agent` 无报错
- [ ] 发一条 WhatsApp 消息，Susu 正常回复

---

## PR #2：TTS + Whisper 统一层

### 新增文件
```
src/ai/tts/__init__.py
src/ai/tts/minimax.py     # MiniMaxTTS
src/ai/tts/voices.py      # 语音配置常量
src/ai/whisper/__init__.py
src/ai/whisper/groq.py    # GroqWhisper
tests/ai/test_tts.py
tests/ai/test_whisper.py
```

### wa_agent.py 改动点映射
| 原代码位置 | 改动 |
|-----------|------|
| wa_agent.py L2977: `minimax_tts()` | 改为 `MiniMaxTTS(ai_config).speak(text)` |
| wa_agent.py L3144: `groq_whisper_transcribe()` | 改为 `GroqWhisper(ai_config).transcribe(audio_bytes)` |

### 测试
```python
tests/ai/test_tts.py      # speak() 返回 bytes，voice 参数传递正确
tests/ai/test_whisper.py  # transcribe() 返回字符串，language 参数正确
```

### 验收标准
- [ ] `pytest tests/ai/test_tts.py tests/ai/test_whisper.py -v` 全部通过
- [ ] Tokyo 语音消息正常转文字并回复

---

## PR #3：搜索路由统一层

### 新增文件
```
src/ai/search/__init__.py
src/ai/search/router.py   # SearchRouter：LLM 判断 + 并行执行 + 结果审核
src/ai/search/weather.py  # HK Observatory + OpenWeatherMap
src/ai/search/news.py     # Tavily + Google News + Bing + Reddit + X
src/ai/search/music.py    # iTunes + Spotify + YouTube
src/ai/search/web.py      # Tavily + Bing + DuckDuckGo + Reddit
tests/ai/test_search_router.py
tests/ai/test_weather.py
tests/ai/test_news.py
tests/ai/test_music.py
tests/ai/test_web.py
```

### wa_agent.py 改动点映射
| 原代码位置 | 改动 |
|-----------|------|
| wa_agent.py L1652-2091: 所有 `search_*` 函数 | 迁移到 `src/ai/search/` |
| wa_agent.py L1435: `route_live_search_with_model()` | 改为 `SearchRouter(llm).route()` |
| wa_agent.py L2272: `review_live_search_results()` | 改为 `SearchRouter(llm).review()` |
| wa_agent.py L758: `fetch_hko_weather_dataset()` | 迁移到 `weather.py` |
| wa_agent.py L896: `search_openweather()` | 迁移到 `weather.py` |

### 测试
```python
tests/ai/test_search_router.py  # 天气/新闻/音乐/网页路由判断，结果审核逻辑
tests/ai/test_weather.py         # HK Observatory API mock，OpenWeatherMap fallback
tests/ai/test_news.py           # 各新闻源并行，timeout 处理
tests/ai/test_music.py          # iTunes/Spotify 返回格式解析
tests/ai/test_web.py            # Tavily/Bing 返回结构化解析
```

### 验收标准
- [ ] `pytest tests/ai/test_search_*.py -v` 全部通过
- [ ] "今日天气" 搜索返回香港天气数据

---

## PR #4：DB + Auth 封装

### 新增文件
```
src/wa_agent/db.py    # MemoryDB 类：所有 SQLite 操作封装
src/wa_agent/auth.py  # Admin auth 相关函数
tests/wa_agent/test_db.py
tests/wa_agent/test_auth.py
```

### wa_agent.py 改动点映射
| 原代码位置 | 改动 |
|-----------|------|
| wa_agent.py L90-400+: 所有 SQLite `conn.execute()` 调用 | 改为 `MemoryDB(ai_config).xxx()` |
| wa_agent.py L4400+: 所有 DB 读取 | 同上 |
| wa_agent.py L900+: auth 相关函数 | 迁移到 `auth.py` |

### 测试
```python
tests/wa_agent/test_db.py   # 记忆增删改查、bucket 分类、TTL 过期
tests/wa_agent/test_auth.py # session cookie 验证、密码验证
```

---

## PR #5：Brain + Memory（高风险）

### 新增文件
```
src/wa_agent/brain.py   # generate_reply() + 所有 prompt 构建函数
src/wa_agent/memory.py  # 记忆提取、存储、Q&A 合成
tests/wa_agent/test_brain.py
tests/wa_agent/test_memory.py
```

### wa_agent.py 改动点映射
| 原代码位置 | 改动 |
|-----------|------|
| wa_agent.py L4400-4700: `generate_reply()` | 迁移到 `brain.py` |
| wa_agent.py L4593: `maybe_extract_memories()` | 迁移到 `memory.py` |
| wa_agent.py L4705: `maybe_extract_session_memories()` | 迁移到 `memory.py` |
| wa_agent.py L6105: `maybe_extract_qa_turn_memory()` | 迁移到 `memory.py` |
| wa_agent.py L4831: `build_proactive_prompt()` | 迁移到 `brain.py` |
| wa_agent.py L4406-4450: 所有 prompt 构建函数 | 迁移到 `brain.py` |

### 测试
```python
tests/wa_agent/test_brain.py    # generate_reply() 返回字符串，prompt 包含正确上下文
tests/wa_agent/test_memory.py   # 记忆提取触发条件、bucket 分配、重要性评分
```

### 验收标准
- [ ] `pytest tests/wa_agent/test_brain.py tests/wa_agent/test_memory.py -v` 全部通过
- [ ] 连续 5 条对话上下文衔接正常（记忆层包含正确）

---

## PR #6：Proactive + Reminders + Voice + WhatsApp

### 新增文件
```
src/wa_agent/proactive.py   # proactive_loop + 评分算法
src/wa_agent/reminders.py   # reminder 检测 + 解析 + 发送
src/wa_agent/voice.py      # 语音消息处理流水线
src/wa_agent/whatsapp.py    # WhatsApp API 封装（发消息/媒体/音频）
tests/wa_agent/test_proactive.py
tests/wa_agent/test_reminders.py
tests/wa_agent/test_voice.py
tests/wa_agent/test_whatsapp.py
```

### wa_agent.py 改动点映射
| 原代码位置 | 改动 |
|-----------|------|
| wa_agent.py L4984: `send_proactive_message()` | 迁移到 `proactive.py` |
| wa_agent.py L5099: `proactive_loop()` | 迁移到 `proactive.py` |
| wa_agent.py L5234: `run_reminder_scan_once()` | 迁移到 `reminders.py` |
| wa_agent.py L5184: `_is_reminder_task()` | 迁移到 `reminders.py` |
| wa_agent.py L3061: `generate_and_send_voice_reply()` | 迁移到 `voice.py` |
| wa_agent.py L3300+: WhatsApp API 调用函数 | 迁移到 `whatsapp.py` |

---

## PR #7：入口整合

### 改动
1. 新增 `src/wa_agent/server.py`：HTTP server 入口，组合所有模块
2. 新增 `src/wa_agent/utils.py`：工具函数
3. `wa_agent.py` 简化为：
```python
#!/usr/bin/env python3
from src.wa_agent.server import main
if __name__ == "__main__":
    main()
```

### 测试
```python
tests/wa_agent/test_server.py  # HTTP handler 单元测试
tests/smoke/test_smoke_tokyo.py # 完整冒烟测试
```

### 验收标准
- [ ] `pytest tests/ -v --ignore=tests/smoke/` 全部通过
- [ ] Tokyo 所有服务正常，WhatsApp 对话正常

---

## PR #8：删除 Bridge/Backend 服务

### 删除文件
```
susu_brain_bridge.py    # systemd service：停止并删除 unit
susu_brain_backend.py    # systemd service：停止并删除 unit
```

### systemd 操作（Tokyo 上执行）
```bash
systemctl stop susu-brain-bridge susu-brain-backend
systemctl disable susu-brain-bridge susu-brain-backend
rm /etc/systemd/system/susu-brain-bridge.service
rm /etc/systemd/system/susu-brain-backend.service
systemctl daemon-reload
```

### wa_agent.py 改动
- 删除 `should_use_brain_bridge()` 函数（及其所有调用）
- 删除 `generate_brain_bridge_reply()` 函数
- 删除 `brain_adapter.py` import
- 删除所有 `WA_BRAIN_BRIDGE_*` 环境变量读取

### 验收标准
- [ ] `:9102` 和 `:9103` 端口无进程监听
- [ ] `systemctl list-units | grep brain` 无结果
- [ ] WhatsApp 对话正常（无需 brain bridge）

---

## PR #9：清理 Adapter 文件

### 删除文件
```
brain_adapter.py
agnai_backend_adapter.py
```

---

## GitHub Actions CI

### `.github/workflows/ci.yml`
```yaml
name: CI

on:
  push:
    branches: [main, 'refactor/**']
  pull_request:
    branches: [main]

jobs:
  syntax:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python -m py_compile src/ai/config.py src/ai/**/*.py src/wa_agent/*.py

  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install pytest pytest-mock
      - run: python -m pytest tests/ --ignore=tests/smoke/ -v

  smoke-tokyo:
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - name: Deploy to Tokyo and smoke test
        env:
          TOKYO_HOST: ${{ secrets.TOKYO_HOST }}
          TOKYO_SSH_KEY: ${{ secrets.TOKYO_SSH_KEY }}
        run: |
          ssh -o StrictHostKeyChecking=no -i $TOKYO_SSH_KEY root@$TOKYO_HOST \
            '/var/www/scripts/deploy-and-test.sh'
```

### Tokyo 部署脚本（`/var/www/scripts/deploy-and-test.sh`）
```bash
#!/bin/bash
set -e

WEB_ROOT="/var/www/html"
BACKUP_DIR="/var/www/html-$(date +%Y%m%d%H%M%S)"
TESTS_DIR="$WEB_ROOT/tests"

echo "[1/6] Backing up..."
cp -r $WEB_ROOT $BACKUP_DIR

echo "[2/6] Pulling latest main..."
cd $WEB_ROOT && git pull origin main

echo "[3/6] Restarting services..."
systemctl restart wa-agent susu-admin-api cheungchau-api

echo "[4/6] Waiting 10s..."
sleep 10

echo "[5/6] Running smoke tests..."
python3 -m pytest $TESTS_DIR/smoke/test_smoke_tokyo.py -v --tb=short

echo "[6/6] Service status..."
systemctl status wa-agent --no-pager | grep "Active:"
systemctl status susu-admin-api --no-pager | grep "Active:"

echo "=== All checks passed ==="
```

---

## 回滚方案

### 一键回滚（Tokyo 上执行）
```bash
# 用最近一次 backup 恢复
cp -r /var/www/html-refactor-YYYYMMDDHHMMSS /var/www/html
systemctl restart wa-agent susu-admin-api
```

### 紧急回滚（30 秒内）
```bash
# 切回 git tag
cd /var/www/html && git checkout backup-before-refactor
systemctl restart wa-agent susu-admin-api
```

---

## 关键环境变量参考（迁移前必读）

### LLM（必须）
```bash
WA_RELAY_API_KEY=...
WA_RELAY_MODEL=claude-opus-4-6
WA_RELAY_FALLBACK_MODEL=claude-sonnet-4-6
WA_RELAY_BASE_URL=https://apiapipp.com/v1
WA_RELAY_RETRY_COUNT=2
```

### TTS
```bash
WA_MINIMAX_API_KEY=...
WA_MINIMAX_BASE_URL=https://api.minimaxaxi.com/v1
WA_TTS_VOICE_ID=Cantonese_CuteGirl
```

### Whisper
```bash
WA_GROQ_API_KEY=...   # 或 GROQ_API_KEY
```

### 搜索
```bash
WA_TAVILY_API_KEY=...
WA_BING_API_KEY=...
WA_YOUTUBE_API_KEY=...
WA_X_BEARER_TOKEN=...
WA_OPENWEATHER_API_KEY=...
WA_SPOTIFY_CLIENT_ID=...
WA_SPOTIFY_CLIENT_SECRET=...
```

### Admin Auth（systemd override）
```bash
# /etc/systemd/system/susu-admin-api.service.d/override.conf
SUSU_ADMIN_PASSWORD_SALT_B64=tobh/z4y+Wy/Qzg/6hpkvQ==
SUSU_ADMIN_PASSWORD_HASH_B64=Bdz3gv5rzCJS5j1rR0GXXoBP5klMkdwCEEtA/98xi7o=
SUSU_ADMIN_SESSION_SECRET=19dc339615ac3d02c1a5b3b0a6cc4ce5111797cecb018263410587f4e9006cb2
密码: Dingding0616
PBKDF2 iterations: 210000
```

### Proactive
```bash
WA_PROACTIVE_ENABLED=1
WA_PROACTIVE_SCAN_SECONDS=300
WA_PROACTIVE_MIN_SILENCE_MINUTES=45
WA_PROACTIVE_COOLDOWN_MINUTES=180
WA_PROACTIVE_REPLY_WINDOW_MINUTES=90
WA_PROACTIVE_CONVERSATION_WINDOW_HOURS=24
WA_PROACTIVE_MAX_PER_SERVICE_DAY=2
WA_PROACTIVE_MIN_INBOUND_MESSAGES=8
```

---

## wa_agent.py 关键函数映射速查

| 函数名 | 当前行号 | 迁移目标 |
|--------|---------|---------|
| `generate_model_text()` | ~4406 | `src.ai.llm.relay.RelayProvider.chat()` |
| `generate_lightweight_router_text()` | ~4432 | 同上 |
| `minimax_tts()` | ~2977 | `src.ai.tts.minimax.MiniMaxTTS.speak()` |
| `groq_whisper_transcribe()` | ~3144 | `src.ai.whisper.groq.GroqWhisper.transcribe()` |
| `generate_reply()` | ~4400 | `src.wa_agent.brain.generate_reply()` |
| `build_proactive_prompt()` | ~4831 | `src.wa_agent.brain.build_proactive_prompt()` |
| `maybe_extract_memories()` | ~4593 | `src.wa_agent.memory.maybe_extract_memories()` |
| `maybe_extract_session_memories()` | ~4705 | `src.wa_agent.memory.maybe_extract_session_memories()` |
| `maybe_extract_qa_turn_memory()` | ~6105 | `src.wa_agent.memory.maybe_extract_qa_turn_memory()` |
| `send_proactive_message()` | ~4984 | `src.wa_agent.proactive.send_proactive_message()` |
| `proactive_loop()` | ~5099 | `src.wa_agent.proactive.proactive_loop()` |
| `run_reminder_scan_once()` | ~5234 | `src.wa_agent.reminders.run_reminder_scan_once()` |
| `generate_and_send_voice_reply()` | ~3061 | `src.wa_agent.voice.generate_and_send_voice_reply()` |
| `route_live_search_with_model()` | ~1435 | `src.ai.search.router.SearchRouter.route()` |
| `review_live_search_results()` | ~2272 | `src.ai.search.router.SearchRouter.review()` |
| `fetch_hko_weather_dataset()` | ~758 | `src.ai.search.weather.HKObservatory.fetch()` |
| `search_openweather()` | ~896 | `src.ai.search.weather.OpenWeatherMap.search()` |
| 所有 `search_*()` 函数 | ~1652-2091 | `src.ai.search/` 各模块 |
| `should_use_brain_bridge()` | ~5894 | **删除（不再需要）** |
| `generate_brain_bridge_reply()` | ~5950 | **删除** |
| 所有 SQLite `conn.execute()` | 分散 | `src.wa_agent.db.MemoryDB` |
| Admin auth 函数 | ~86-93 | `src.wa_agent.auth` |

---

*重构开始前请确认已创建 git tag backup-before-refactor*
