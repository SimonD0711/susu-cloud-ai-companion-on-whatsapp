# Susu Cloud - AI Companion on WhatsApp

[![Release v1.0.0](https://img.shields.io/badge/Release-v1.0.0-brightgreen.svg)](https://github.com/SimonD0711/susu-cloud-ai-companion-on-whatsapp/releases)

---

### 🌐 Language Selection / 語言選擇 / 语言选择
- [繁體中文/粵語](#-繁體中文粵語)
- [简体中文/普通话](#-简体中文普通话)
- [English](#-english)

---

### 🇭🇰 [繁體中文/粵語] 蘇蘇雲端 AI 伴侶
Susu Cloud 係一個專為 WhatsApp 而設嘅智能 AI 伴侶，透過 Brain Bridge 架構，將 AI 變成好似真人一樣咁自然、貼心。

#### 版本 1.0.0 更新內容 (v0.1.5 -> v1.0.0)
*   **Brain Bridge 架構**：全面取代過時嘅 SillyTavern 整合，改用更穩定、更靈活嘅 Brain Bridge 架構。
*   **智能記憶級聯 (Bucket Cascade)**：引入 24 小時/3天/7天/歸檔分層機制，配合自動 Q&A 合成，對話銜接更自然。
*   **任務智能路由**：識分學業 Quiz、assignment 截止日期、定係日常閒聊，回覆更到位。
*   **代碼清理**：徹底移除了歷史遺留嘅檔案與舊版本架構殘留。

#### 功能列表
*   **WhatsApp Webhook 運行時**：實時處理 WhatsApp 訊息，支援文本與圖片識別。
*   **分層記憶系統**：自動將資訊分為長期、短期（24h/3d/7d）及歸檔層，避免資訊過載。
*   **自動知識合成**：系統會自動總結 Q&A 對話，將重要知識保存為短期記憶。
*   **聯網搜索路由**：接入即時資訊，配合審核機制，減少幻覺。
*   **主動訊息推送**：根據靜默時間、當前時段與心率模型，自動發送暖心問候。
*   **網頁版後台管理**：直接透過網頁端檢視聯繫人記憶、提醒及調整運行策略。

---

### 🇨🇳 [简体中文/普通话] Susu Cloud AI 伴侣
Susu Cloud 是专为 WhatsApp 打造的智能 AI 伴侣。通过 Brain Bridge 架构，我们实现了更自然、更具人性化的对话体验。

#### 版本 1.0.0 更新内容 (v0.1.5 -> v1.0.0)
*   **Brain Bridge 架构**：模块化设计，大幅提升了模型通信效率与稳定性。
*   **多层级记忆系统**：支持自动记忆分类与衰减，自动合成关键对话点，实现高效的上下文衔接。
*   **任务智能路由**：优化了学术安排与日常任务的处理逻辑，确保优先匹配上下文。
*   **仓库深度重构**：移除了所有无关的历史代码，实现了真正的 v1.0.0 纯净发布。

#### 功能列表
*   **WhatsApp 运行时**：响应 Meta WhatsApp Cloud API，处理多媒体信息，实现连贯的上下文合并回复。
*   **多层级存储**：SQLite 后端管理长期记忆与短期记忆 bucket，支持过期自动归档。
*   **智能知识提炼**：自动将对话中的交互转化为知识点，提升模型对用户习惯的理解力。
*   **联网与搜索**：针对即时需求进行联网检索，配合 Query Reviewer 降低幻觉风险。
*   **主动策略机制**：根据活跃度评估、时间策略，实现低干扰的主动关怀。
*   **Web 控制台**：集成了联系人管理、记忆库编辑、参数调试的轻量级后台界面。

---

### 🇺🇸 [English] Susu Cloud AI Companion
Susu Cloud is an advanced AI companion tailored for WhatsApp. Built on the Brain Bridge architecture, it offers a human-like, memory-rich conversational experience.

#### Release 1.0.0 Highlights (v0.1.5 -> v1.0.0)
*   **Brain Bridge Integration**: Migrated from legacy SillyTavern to a robust, decoupled bridge-backed brain.
*   **Memory Cascade System**: Implemented bucket-based storage (24h/3d/7d/archive) with automatic Q&A synthesis.
*   **Context-Aware Routing**: Specialized logic for academic schedule queries and assignments to ensure precision.
*   **Repository Cleanliness**: Full architectural reset, purging historical files and standardizing the codebase.

#### Key Features
*   **WhatsApp Webhook Runtime**: Handles events, text/image processing, and merges messages into a unified reply context.
*   **Layered Memory Database**: Persistent SQL storage for long-term profiles, session contexts, and archives.
*   **Autonomous Knowledge Extraction**: Automatically distills Q&A turns into permanent memory.
*   **Proactive Engagement**: Triggers non-intrusive messages based on silence time and time-of-day style profiles.
*   **Browser-based Admin UI**: Manage memories, system prompts, and reminders via a dedicated local admin interface.

---

### 🛠 Setup & Deployment
1. **Config**: `Copy-Item .env.example .env`
2. **Password**: `python .\tools\hash_password.py "password"`
3. **Run**: `python .\wa_agent.py` & `python .\susu_admin_server.py`

---
*Developed with ❤️ for WhatsApp.*
