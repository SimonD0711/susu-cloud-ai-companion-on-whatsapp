![Susu Cloud banner](https://raw.githubusercontent.com/${REPOSITORY}/${REF_NAME}/assets/susu-cloud-banner.svg)

## Overview

Susu Cloud is an open-source WhatsApp AI companion runtime with layered memory, live search, and a lightweight admin UI.

## Included In This Release

- `wa_agent.py` for the WhatsApp webhook runtime
- `susu_admin_server.py` for the lightweight admin API
- `susu-memory-admin.html` for the browser-based memory and settings console

## Quick Start

```bash
cp .env.example .env
python tools/hash_password.py "your-admin-password"
python wa_agent.py
```

## Container Package

- `docker pull ghcr.io/${REPOSITORY}:${REF_NAME}`
- `docker run --rm -p 9100:9100 --env-file .env ghcr.io/${REPOSITORY}:${REF_NAME}`

## Notes

- Configure your own `.env` before running the runtime or admin server.
- Production-specific IDs, paths, and private operator notes are intentionally not included in this public repository.
