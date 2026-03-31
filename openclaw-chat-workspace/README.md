# Susu Cloud - AI Companion on WhatsApp

An AI-powered WhatsApp companion, now backed by the Brain Bridge architecture.

## Architecture
- **Brain Bridge**: Replaced legacy SillyTavern integration with a robust bridge-backed brain architecture ().
- **Memory System**: Implemented multi-tier memory (within_24h, within_3d, within_7d, and archive) with bucket cascade decay.
- **Task Intelligence**: Enhanced memory retrieval with task-type classification (education, Q&A, emotional support) to prioritize relevant context.

## Repository Status
- **Current Branch**: `codex/susu-cloud`
- **Independent Repo**: Yes (detached from legacy worktrees)
- **Features**:
  - Q&A Synthesis: Automatically extracts and stores meaningful Q&A turns.
  - Bridge Routing: Dynamic model routing for complex vs. casual tasks.
  - Context Anchoring: Refined short-answer resolution via anchor state management.

## Setup
- Environment managed via `/etc/wa-agent.env`.
- Services managed via systemd (`susu-brain-bridge.service`, `wa-agent.service`).
