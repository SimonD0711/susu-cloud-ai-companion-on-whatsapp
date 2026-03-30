# Susu Brain Bridge

This bridge is the Phase 2 runtime layer between `wa_agent.py` and a structured chat backend.

## Purpose

- keep `wa_agent.py` stable
- expose one local HTTP endpoint for Susu brain calls
- allow the downstream backend to change without editing `wa_agent.py`

## Local endpoint

- `POST /v1/chat/completions`
- `GET /health`

The request and response shape are OpenAI-style chat completions.

## Recommended wiring

`wa_agent.py`:

- `WA_BRAIN_PROVIDER=sillytavern`
- `WA_SILLYTAVERN_API_URL=http://127.0.0.1:9102/v1/chat/completions`
- `WA_SILLYTAVERN_API_KEY=<same as WA_ST_BRIDGE_API_KEY>`

Bridge service:

- `WA_ST_BRIDGE_HOST=127.0.0.1`
- `WA_ST_BRIDGE_PORT=9102`
- `WA_ST_BRIDGE_API_KEY=<local bridge secret>`
- `WA_ST_BRIDGE_UPSTREAM_MODE=<agnai|openai>`
- `WA_ST_BRIDGE_UPSTREAM_URL=<Agnai-style backend or OpenAI-compatible endpoint>`
- `WA_ST_BRIDGE_UPSTREAM_API_KEY=<upstream secret if needed>`
- `WA_ST_BRIDGE_UPSTREAM_MODEL=<optional default model>`

Local pure backend service:

- `WA_SUSU_BRAIN_HOST=127.0.0.1`
- `WA_SUSU_BRAIN_PORT=9103`
- `WA_SUSU_BRAIN_API_KEY=<local backend secret>`
- `WA_SUSU_BRAIN_MODEL=claude-opus-4-6`

## Upstream expectation

For `WA_ST_BRIDGE_UPSTREAM_MODE=openai`, the upstream should accept an OpenAI-style `chat/completions` payload with:

- `messages`
- `temperature`
- `max_tokens`
- optional `model`

For `WA_ST_BRIDGE_UPSTREAM_MODE=agnai`, the bridge will translate the OpenAI-style request from `wa_agent.py` into an Agnai-style structured payload containing:

- `system_prompt`
- `conversation`
- `latest_user_message`
- `temperature`
- `max_tokens`
- optional `model`

This makes the bridge compatible with:

- an Agnai-style pure backend
- OpenAI-compatible proxy layers
- a future custom structured-chat backend

The repo now also includes a minimal local pure backend service, `susu_brain_backend.py`, which accepts that Agnai-style payload and calls the existing relay model. This gives Tokyo a browser-free end-to-end chain:

`wa_agent.py -> Susu brain bridge -> Susu brain backend -> relay model`

## Deployment outline

1. Copy `sillytavern_bridge_server.py` to Tokyo
2. Copy `sillytavern-bridge.service` to `/etc/systemd/system/`
3. Add `WA_ST_BRIDGE_*` env vars to `/etc/wa-agent.env`
4. `systemctl daemon-reload`
5. `systemctl enable --now sillytavern-bridge.service`
6. Copy `susu_brain_backend.py` and `susu-brain-backend.service`
7. `systemctl enable --now susu-brain-backend.service`
8. Point `WA_ST_BRIDGE_UPSTREAM_MODE=agnai`
9. Point `WA_ST_BRIDGE_UPSTREAM_URL` to the local backend endpoint
10. Point `WA_SILLYTAVERN_API_URL` to the local bridge endpoint

## Current safety model

- If `WA_BRAIN_PROVIDER` is still `legacy`, the bridge is unused
- If the bridge or upstream fails, `wa_agent.py` can still fall back when `WA_BRAIN_FALLBACK_ON_ERROR=1`
