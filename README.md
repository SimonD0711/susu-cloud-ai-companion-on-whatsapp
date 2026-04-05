# Susu Cloud — AI Companion on WhatsApp

[![Release v2.1.0](https://img.shields.io/badge/Release-v2.1.0-brightgreen.svg)](https://github.com/SimonD0711/susu-cloud-ai-companion-on-whatsapp/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/SimonD0711/susu-cloud-ai-companion-on-whatsapp/actions/workflows/ci.yml/badge.svg)](https://github.com/SimonD0711/susu-cloud-ai-companion-on-whatsapp/actions)
[![Code style: ruff](https://img.shields.io/badge/Code%20style-ruff-red.svg)](https://github.com/astral-sh/ruff)

> A human-like AI companion for WhatsApp with layered memory, proactive engagement, and calendar integration.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [Environment Variables](#environment-variables)
- [Development](#development)
- [License](#license)

---

## Features

| | | |
|---|---|---|
| 🧠 **Layered Memory** | 🗓️ **Calendar Integration** | 💬 **Proactive Messaging** |
| Long-term + session buckets (24h / 3d / 7d / archive) with automatic Q&A synthesis | Google Calendar iCal sync, HK public holidays, CityU semester states | Non-intrusive greetings based on silence time, time-of-day style profiles |
| 📍 **Smart Location** | 🔍 **Live Search** | 🎛️ **Admin Web UI** |
| LLM-powered location extraction, auto holiday detection | Tavily, Bing, OpenWeather, YouTube, Spotify, Reddit, X search routing | Browser-based memory management, reminders, and settings control |

---

## Architecture

```
 WhatsApp Cloud API
        │
        ▼
┌───────────────────┐
│  wa_agent.py      │  Webhook Receiver + Reply Engine
│  (port 9100)      │  • Extract messages from webhook payload
└────────┬──────────┘  • Spawn reply subprocess
         │              • Trigger proactive messaging loop
         ▼
┌───────────────────┐     ┌─────────────────────────┐
│  Brain Bridge     │────▶│  LLM (Claude via Relay)│
│  (build_runtime_  │     └─────────────────────────┘
│   context)        │
│                   │     ┌─────────────────────────┐
│  Memory Cascade   │────▶│  SQLite Database       │
│  (Bucket System)  │     │  wa_agent.db           │
└───────────────────┘     └─────────────────────────┘
         │
         ▼
┌───────────────────┐     ┌─────────────────────────┐
│  Admin Web Server │────▶│  Browser Admin UI       │
│  (port 9001)      │     │  susu-memory-admin.html │
└───────────────────┘     └─────────────────────────┘
```

**Memory Bucket Cascade:**

```
 Message → LLM Extraction
   ├── 24h bucket     (very recent — highest priority)
   ├── 3-day bucket   (within 3 days)
   ├── 7-day bucket   (within 1 week)
   ├── Archive bucket (older, queryable by time markers)
   └── Long-term      (permanent profile knowledge)
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- WhatsApp Business Cloud API account ([Meta Developer Console](https://developers.facebook.com/apps/))
- Relay API key (Claude-compatible endpoint)
- MiniMax API key (for voice synthesis)

### 1. Clone & Install

```bash
git clone https://github.com/SimonD0711/susu-cloud-ai-companion-on-whatsapp.git
cd susu-cloud-ai-companion-on-whatsapp
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
# Copy the environment template
cp .env.example .env

# Edit .env and fill in your keys
# Required: WA_VERIFY_TOKEN, WA_ACCESS_TOKEN, WA_PHONE_NUMBER_ID
# Required: WA_RELAY_API_KEY, WA_MINIMAX_API_KEY
```

### 3. Set Admin Password

```bash
python tools/hash_password.py "your-secure-password"
# Copy the output salt and hash into your .env:
# SUSU_ADMIN_PASSWORD_SALT_B64=...
# SUSU_ADMIN_PASSWORD_HASH_B64=...
# SUSU_ADMIN_SESSION_SECRET=...
```

### 4. Run

```bash
# Terminal 1 — WhatsApp agent (port 9100)
python wa_agent.py

# Terminal 2 — Admin web server (port 9001)
python susu_admin_server.py
```

### 5. Set Up WhatsApp Webhook

1. Go to [Meta Developer Console](https://developers.facebook.com/apps/)
2. Create a WhatsApp Business app
3. Add the **Webhook** product
4. Set callback URL to `https://your-domain.com/webhook`
5. Set verify token to match `WA_VERIFY_TOKEN` in `.env`
6. Subscribe to `messages` field

### Docker Deployment

```bash
# Build
docker build -t susu-cloud .

# Run
docker run -d \
  --name susu-cloud \
  -p 9100:9100 \
  -p 9001:9001 \
  --env-file .env \
  -v $(pwd)/wa_agent.db:/var/www/html/wa_agent.db \
  susu-cloud
```

---

## Project Structure

```
susu-cloud/
├── wa_agent.py                    # Main agent (monolith) — HTTP server, webhook, reply pipeline
├── susu_admin_server.py           # Admin API server (port 9001)
├── susu_admin_core.py             # Admin backend — memory CRUD, settings, auth
├── susu-memory-admin.html         # Admin web UI (single-page, no framework)
├── requirements.txt               # Dev dependencies (pytest, ruff)
├── .env.example                  # Environment variables template
├── Dockerfile                    # Docker container definition
├── docker-entrypoint.sh          # Container startup script
│
├── src/
│   ├── ai/                       # Unified AI capability layer
│   │   ├── config.py             # AIConfig dataclass (all AI env vars)
│   │   ├── base.py               # Abstract LLMProvider base class
│   │   ├── llm/
│   │   │   ├── manager.py         # LLMManager with fallback logic
│   │   │   ├── relay.py           # RelayProvider (Claude via relay)
│   │   │   └── prompts.py         # Centralized system prompts
│   │   ├── tts/
│   │   │   ├── minimax.py         # MiniMax TTS wrapper
│   │   │   └── voices.py
│   │   ├── whisper/
│   │   │   └── groq.py           # Groq Whisper transcription
│   │   └── search/               # Unified search router + providers
│   │       ├── router.py          # LLM-driven search routing
│   │       ├── weather.py         # HK Observatory + OpenWeatherMap
│   │       ├── news.py            # Tavily, Google News, Bing, Reddit, X
│   │       ├── music.py           # iTunes, Spotify, YouTube
│   │       └── web.py             # Tavily, Bing, DuckDuckGo, Reddit
│   │
│   └── wa_agent/                 # Modular agent components (refactor in progress)
│       ├── server.py              # HTTP server entry point
│       ├── brain.py               # Reply generation
│       ├── memory.py              # Memory extraction + storage
│       ├── proactive.py           # Proactive messaging engine
│       ├── reminders.py           # Reminder detection + delivery
│       ├── voice.py               # Voice message processing
│       ├── whatsapp.py            # WhatsApp Business API wrapper
│       ├── db.py                  # MemoryDB SQLite wrapper
│       ├── auth.py                # Admin authentication
│       └── utils.py               # Utility functions
│
├── tests/                         # pytest test suite
│   ├── conftest.py               # Global fixtures
│   ├── ai/                       # AI layer tests
│   └── wa_agent/                 # Agent module tests
│
├── OPERATIONS.md                # Operations manual (production details)
├── REFACTOR-PLAN.md              # Architecture refactor plan
└── .github/
    ├── workflows/ci.yml         # CI/CD pipeline
    ├── CONTRIBUTING.md          # Contribution guide
    ├── ISSUE_TEMPLATE/          # Bug report & feature request templates
    └── PULL_REQUEST_TEMPLATE.md  # PR template
```

---

## Environment Variables

See [`.env.example`](.env.example) for the full list with descriptions. Key variables:

| Variable | Required | Description |
|---|---|---|
| `WA_VERIFY_TOKEN` | Yes | WhatsApp webhook verify token |
| `WA_ACCESS_TOKEN` | Yes | Meta long-lived user access token |
| `WA_PHONE_NUMBER_ID` | Yes | WhatsApp Phone Number ID |
| `WA_RELAY_API_KEY` | Yes | Relay API key for Claude requests |
| `WA_MINIMAX_API_KEY` | Yes | MiniMax API key for TTS |
| `WA_PROACTIVE_ENABLED` | No | Enable proactive messaging (default: 1) |
| `WA_USER_ICAL_URL` | No | Google Calendar iCal URL |
| `SUSU_ADMIN_PASSWORD_HASH_B64` | Yes | Admin password hash (base64) |

Generate admin credentials:

```bash
python tools/hash_password.py "your-password"
```

---

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
pytest tests/ -v

# Lint code
ruff check .

# Auto-fix lint issues
ruff check . --fix
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Language Versions

- [English (above)](#susu-cloud--ai-companion-on-whatsapp)
- [简体中文](README.md#-简体中文普通话-susu-cloud-ai-伴侣)
- [繁體中文/粵語](README.md#-繁體中文粵語-蘇蘇雲端-ai-伴侶)

---

## Changelog

### v2.1.0 (2026-04-03)

**Session Memory System Overhaul**
- "昨天吃了包子" now correctly classified as 3-day bucket (not wrongly tagged as today)
- LLM extraction prompt strengthened: explicit time-word→bucket mapping, passes existing memories for deduplication
- Heuristic fallback no longer fragments sentences; new `infer_observed_at_from_text()` infers event time from time markers
- Unified `normalize_key()` removes Chinese punctuation — prevents false memory merging
- Removed dead code `extract_live_search_question_memory`

**Rate Limiting**
- Extraction runs as background side-effect after reply — no blocking, every message triggers

**Feedback Mechanism**
- New `use_count` tracks memory reference count
- Memories referenced ≥5 times automatically get 2× TTL extension
- Admin UI new stats: weekly new memories, avg reference count, unused memories

**Memory Application Loop**
- Proactive prompt explicitly prioritizes 24h memories as conversation hooks
- Reply engine actively references relevant session memories

### v2.0.0 (2026-04-01)

- Google Calendar iCal sync with daily caching
- HK public holidays 2026/2027 auto-detected
- CityU semester state auto-inferred
- System prompt date enforcement
- Smart location system with holiday detection
- Memory admin UI redesign (mobile-first)
- Batch operations (delete/renew/promote)
- Memory Extraction LLM throttling

### v1.0.0

- Brain Bridge architecture — migrated from SillyTavern
- Memory Cascade System (24h/3d/7d/archive buckets)
- Context-Aware Routing for academic and daily tasks
- Full repository clean-up

---

*Developed with ❤️ for WhatsApp.*
