# Deployment

## Prerequisites

- Python 3.11+
- WhatsApp Business Cloud API account ([Meta Developer Console](https://developers.facebook.com/apps/))
- [Relay API](https://your-relay-provider.com) key (Claude-compatible)
- MiniMax API key (for TTS voice synthesis)
- Groq API key (for Whisper transcription, optional but recommended)
- Git

## Local Development Setup

### 1. Clone the Repository

```bash
git clone https://github.com/SimonD0711/susu-cloud-ai-companion-on-whatsapp.git
cd susu-cloud-ai-companion-on-whatsapp
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

| Variable | Description |
|---|---|
| `WA_VERIFY_TOKEN` | Webhook verify token (set in Meta Developer Console) |
| `WA_ACCESS_TOKEN` | Meta long-lived user access token |
| `WA_PHONE_NUMBER_ID` | WhatsApp Phone Number ID |
| `WA_RELAY_API_KEY` | Relay API key for Claude requests |
| `WA_MINIMAX_API_KEY` | MiniMax API key for TTS |
| `SUSU_ADMIN_PASSWORD_HASH_B64` | Admin password hash (see below) |
| `SUSU_ADMIN_SESSION_SECRET` | Session cookie secret (base64) |

### 4. Generate Admin Credentials

```bash
python tools/hash_password.py "your-secure-password"
```

Copy the output salt and hash into your `.env`:

```
SUSU_ADMIN_PASSWORD_SALT_B64=<output-salt>
SUSU_ADMIN_PASSWORD_HASH_B64=<output-hash>
SUSU_ADMIN_SESSION_SECRET=<output-secret>
```

### 5. Run

```bash
# Terminal 1 — WhatsApp agent (port 9100)
python wa_agent.py

# Terminal 2 — Admin web server (port 9001)
python susu_admin_server.py
```

- WhatsApp agent: http://localhost:9100
- Admin UI: http://localhost:9001 (default login: display name from `SUSU_ADMIN_DISPLAY_NAME`)

### 6. Set Up WhatsApp Webhook

1. Go to [Meta Developer Console](https://developers.facebook.com/apps/)
2. Create a **WhatsApp Business app**
3. Add the **Webhook** product
4. Callback URL: `https://your-public-domain.com/webhook`
5. Verify token: match `WA_VERIFY_TOKEN` in `.env`
6. Subscribe to fields: `messages`

> **Note:** Your server must be publicly accessible (not localhost) for WhatsApp to reach it. Use a reverse proxy (nginx) or ngrok for local testing.

## Docker Deployment

### Build

```bash
docker build -t susu-cloud .
```

### Run

```bash
docker run -d \
  --name susu-cloud \
  -p 9100:9100 \
  -p 9001:9001 \
  --env-file .env \
  -v $(pwd)/wa_agent.db:/var/www/html/wa_agent.db \
  susu-cloud
```

### Docker Environment Variables

All variables from `.env.example` can be passed via `--env-file` or `-e` flags.

### Production Checklist

- [ ] Use a reverse proxy (nginx) with HTTPS
- [ ] Set `SUSU_ADMIN_HOST=0.0.0.0` to allow remote admin access (with firewall)
- [ ] Use a strong `SUSU_ADMIN_SESSION_SECRET` (minimum 32 random chars)
- [ ] Set `WA_VERIFY_TOKEN` to a long random string
- [ ] Consider running admin on a separate port with basic auth

## Environment Variables Reference

### WhatsApp API

| Variable | Default | Description |
|---|---|---|
| `WA_VERIFY_TOKEN` | *(none)* | **Required.** Webhook verify token |
| `WA_ACCESS_TOKEN` | *(none)* | **Required.** Meta access token |
| `WA_PHONE_NUMBER_ID` | *(none)* | **Required.** Phone Number ID |
| `WA_GRAPH_VERSION` | `v22.0` | WhatsApp Graph API version |

### LLM / Relay

| Variable | Default | Description |
|---|---|---|
| `WA_RELAY_API_KEY` | *(none)* | **Required.** Relay API key |
| `WA_RELAY_MODEL` | `claude-opus-4-6` | Primary Claude model |
| `WA_RELAY_FALLBACK_MODEL` | `claude-sonnet-4-6` | Fallback model |
| `WA_RELAY_BASE_URL` | `https://apiapipp.com/v1` | Relay API endpoint |

### TTS (MiniMax)

| Variable | Default | Description |
|---|---|---|
| `WA_MINIMAX_API_KEY` | *(none)* | **Required.** MiniMax API key |
| `WA_TTS_VOICE_ID` | `Cantonese_CuteGirl` | TTS voice identifier |
| `WA_TTS_SPEED` | `1.0` | Playback speed (0.5–2.0) |

### Whisper (Groq)

| Variable | Default | Description |
|---|---|---|
| `WA_GROQ_API_KEY` | *(none)* | Groq API key |
| `GROQ_API_KEY` | *(none)* | Alternative Groq key env var |

### Search Providers

| Variable | Description |
|---|---|
| `WA_TAVILY_API_KEY` | Tavily web search (recommended) |
| `WA_BING_API_KEY` | Bing Search |
| `WA_YOUTUBE_API_KEY` | YouTube Data API v3 |
| `WA_X_BEARER_TOKEN` | X (Twitter) Bearer Token |
| `WA_OPENWEATHER_API_KEY` | OpenWeatherMap |
| `WA_SPOTIFY_CLIENT_ID` | Spotify app client ID |
| `WA_SPOTIFY_CLIENT_SECRET` | Spotify app client secret |

### Proactive Messaging

| Variable | Default | Description |
|---|---|---|
| `WA_PROACTIVE_ENABLED` | `1` | Enable/disable (0=off) |
| `WA_PROACTIVE_SCAN_SECONDS` | `300` | Scan interval (seconds) |
| `WA_PROACTIVE_MIN_SILENCE_MINUTES` | `45` | Min silence before proactive |
| `WA_PROACTIVE_COOLDOWN_MINUTES` | `180` | Cooldown between messages |
| `WA_PROACTIVE_MAX_PER_SERVICE_DAY` | `2` | Max proactive per day |

### Calendar

| Variable | Description |
|---|---|
| `WA_USER_ICAL_URL` | Google Calendar iCal URL (leave empty to disable) |

### Admin Server

| Variable | Default | Description |
|---|---|---|
| `SUSU_ADMIN_HOST` | `127.0.0.1` | Bind host |
| `SUSU_ADMIN_PORT` | `9001` | Bind port |
| `SUSU_ADMIN_DISPLAY_NAME` | `Admin` | Login page name |
| `SUSU_ADMIN_SESSION_COOKIE` | `susu_admin_session` | Cookie name |
| `SUSU_ADMIN_SESSION_TTL` | `2592000` | Session TTL (30 days) |

### Paths

| Variable | Default | Description |
|---|---|---|
| `WA_BASE_DIR` | `/var/www/html` | Application base directory |
| `WA_DB_PATH` | `WA_BASE_DIR/wa_agent.db` | Database path |

## Troubleshooting

### WhatsApp webhook not receiving messages

1. Check your server is publicly accessible (not behind NAT)
2. Verify `WA_VERIFY_TOKEN` matches exactly
3. Check nginx logs for blocked requests
4. Use `ngrok http 9100` for local testing

### Admin UI not loading

1. Ensure `susu_admin_server.py` is running
2. Check `SUSU_ADMIN_HOST` allows your IP
3. Verify credentials in `.env`

### Memory not being extracted

1. Check `WA_RELAY_API_KEY` is valid
2. Look at `wa_agent.py` logs for extraction errors
3. Verify `WA_PROACTIVE_MIN_SILENCE_MINUTES` is not too high

## See Also

- [Home](Home) — Project overview
- [Architecture](Architecture) — System design details
- [OPERATIONS.md](https://github.com/SimonD0711/susu-cloud-ai-companion-on-whatsapp/blob/main/OPERATIONS.md) — Production operations manual
