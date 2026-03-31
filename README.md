# Susu Cloud - AI Companion on WhatsApp

[![Release v1.0.0](https://img.shields.io/badge/Release-v1.0.0-brightgreen.svg)](https://github.com/SimonD0711/susu-cloud-ai-companion-on-whatsapp/releases)

---

### 🌐 Language Selection / 語言選擇 / 语言选择
- [繁體中文/粵語](#-繁體中文粵語)
- [简体中文/普通话](#-简体中文普通话)
- [English](#-english)

---

### 🇭🇰 [繁體中文/粵語] 蘇蘇雲端 AI 伴侶
Susu Cloud 係一個專為 WhatsApp 而設嘅智能 AI 伴侶。我哋透過 Brain Bridge 架構，將 AI 變成好似真人一樣咁自然、貼心。

#### 版本 1.0.0 更新內容 (v0.1.5 -> v1.0.0)
*   **Brain Bridge 架構**：全面取代過時嘅 SillyTavern 整合，改用更穩定、更靈活嘅 Brain Bridge 架構。
*   **智能記憶級聯 (Bucket Cascade)**：引入 24 小時/3天/7天/歸檔分層機制，配合自動 Q&A 合成，對話銜接更自然。
*   **任務智能路由**：識分學業 Quiz、assignment 截止日期、定係日常閒聊，回覆更到位。
*   **代碼清理**：徹底移除了歷史遺留嘅攝影網站檔案與舊版本架構殘留。

---

### 🇨🇳 [简体中文/普通话] Susu Cloud AI 伴侣
Susu Cloud 是专为 WhatsApp 打造的智能 AI 伴侣。通过 Brain Bridge 架构，我们实现了更自然、更具人性化的对话体验。

#### 版本 1.0.0 更新内容 (v0.1.5 -> v1.0.0)
*   **Brain Bridge 架构**：模块化设计，大幅提升了模型通信效率与稳定性。
*   **多层级记忆系统**：支持自动记忆分类与衰减，自动合成关键对话点，实现高效的上下文衔接。
*   **任务智能路由**：优化了学术安排与日常任务的处理逻辑，确保优先匹配上下文。
*   **仓库深度重构**：移除了所有无关的摄影站历史代码，实现了真正的 v1.0.0 纯净发布。

---

### 🇺🇸 [English] Susu Cloud AI Companion
Susu Cloud is an advanced AI companion tailored for WhatsApp. Built on the Brain Bridge architecture, it offers a human-like, memory-rich conversational experience.

#### Release 1.0.0 Highlights (v0.1.5 -> v1.0.0)
*   **Brain Bridge Integration**: Migrated from legacy SillyTavern to a robust, decoupled bridge-backed brain.
*   **Memory Cascade System**: Implemented bucket-based storage (24h/3d/7d/archive) with automatic Q&A synthesis.
*   **Context-Aware Routing**: Specialized logic for academic schedule queries and assignments to ensure precision.
*   **Repository Cleanliness**: Full architectural reset, purging historical artifacts and standardizing the codebase.

---

## Project Layout
| Area | Description |
| --- | --- |
| Runtime | `wa_agent.py` handles WhatsApp webhooks, memory, reminders, and replies |
| Admin API | `susu_admin_server.py` exposes lightweight management endpoints |
| Admin UI | `susu-memory-admin.html` manages memories, reminders, and settings |

## Quick Start
1. **Copy config template**: `Copy-Item .env.example .env`
2. **Generate admin password hash**: `python .\tools\hash_password.py "your-admin-password"`
   - Set in `.env`: `SUSU_ADMIN_PASSWORD_SALT_B64`, `SUSU_ADMIN_PASSWORD_HASH_B64`, `SUSU_ADMIN_SESSION_SECRET`
3. **Start Runtime**: `python .\wa_agent.py`
4. **Start Admin UI**: `python .\susu_admin_server.py`

*Default URLs: Webhook `http://127.0.0.1:9100/whatsapp/webhook`, Admin UI `http://127.0.0.1:9000/`*

---
*Developed with ❤️ for WhatsApp.*
