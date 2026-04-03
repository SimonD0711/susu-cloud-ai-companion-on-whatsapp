# Susu Cloud Wiki

Welcome to the Susu Cloud documentation! Susu Cloud is an AI companion for WhatsApp with human-like memory, proactive engagement, and calendar integration.

## Quick Links

| Page | Description |
|------|-------------|
| **[Home](Home)** | This page — project overview |
| **[Architecture](Architecture)** | System architecture, data flow, module breakdown |
| **[Deployment](Deployment)** | Setup guides — local, Docker, production |

## What is Susu Cloud?

Susu Cloud is a Python-based WhatsApp AI chatbot that:

- **Responds to WhatsApp messages** via Meta WhatsApp Business Cloud API webhooks
- **Maintains layered memory** across multiple time buckets (24h / 3d / 7d / archive / long-term)
- **Proactively reaches out** based on silence time, time-of-day, and memory hooks
- **Synthesizes knowledge** from conversations into Q&A memories
- **Integrates with Google Calendar** via iCal for schedule awareness
- **Routes queries** to live search providers (Tavily, Bing, OpenWeather, YouTube, Spotify, Reddit, X)
- **Provides a browser-based admin UI** for memory management and settings

## Key Technologies

- **Python 3.11+** — no external web framework, uses `http.server`
- **SQLite** — persistent storage for memories, messages, reminders
- **Claude (via Relay API)** — primary LLM for reply generation and memory extraction
- **MiniMax TTS** — voice message synthesis
- **Groq Whisper** — voice message transcription
- **Docker** — containerized deployment

## Repository Structure

```
susu-cloud/
├── wa_agent.py              # Main WhatsApp agent (monolith)
├── susu_admin_server.py     # Admin web API server (port 9001)
├── susu-memory-admin.html   # Admin web UI
├── src/
│   ├── ai/                 # Unified AI layer (LLM, TTS, Whisper, Search)
│   └── wa_agent/          # Modular agent components (refactor target)
├── tests/                  # pytest test suite
└── .github/               # CI/CD, issue/PR templates
```

## Contributing

See [.github/CONTRIBUTING.md](https://github.com/SimonD0711/susu-cloud-ai-companion-on-whatsapp/blob/main/.github/CONTRIBUTING.md) for how to set up a dev environment and submit changes.

## License

MIT License — see [LICENSE](https://github.com/SimonD0711/susu-cloud-ai-companion-on-whatsapp/blob/main/LICENSE).
