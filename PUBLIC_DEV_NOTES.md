# Susu Cloud Public Development Notes

Last updated: 2026-03-28

## Scope

This note is share-safe.

It covers:

- current reply architecture
- active model routing
- live-search behavior
- typing and batching behavior
- key files for development

It intentionally excludes:

- production hostnames
- service names
- deployment commands
- backup file paths
- environment secrets

## Active Reply Model

- Susu normal chat generation is currently locked to `claude-opus-4-6`
- Normal reply generation does not use runtime fallback models
- Legacy helper code for other providers may still exist in the codebase, but the active reply path is Opus-only

## Current Reply Architecture

### 1. Reply worker model

- Each contact is handled by a reply worker
- The old fixed inbound delay was removed
- Reply generation runs in a cancellable subprocess
- If a second or third inbound message arrives before send:
  - the old generation job is terminated locally
  - pending inbound messages are recombined
  - a fresh reply is generated from the combined input

### 2. Read and typing pacing

- The latest inbound message is marked as read immediately
- Typing is not shown if a reply is ready within `0.5s`
- If generation exceeds `0.5s`, typing starts
- Typing is refreshed every `4.0s` until the outbound reply is about to send
- Typing refresh stops immediately if the reply job is superseded by newer inbound messages

Relevant env knobs:

- `WA_TYPING_INDICATOR_DELAY_SECONDS`
- `WA_TYPING_INDICATOR_REFRESH_SECONDS`
- `WA_REPLY_JOB_POLL_SECONDS`
- `WA_REPLY_JOB_TERMINATE_GRACE_SECONDS`

### 3. Bubble splitting

- Reply text is split into WhatsApp bubbles by sentence punctuation and line breaks
- There is no fixed bubble count cap in the current implementation

## Live Search Design

Current live-search modes:

- `weather`
- `news`
- `music`
- `web`

Current flow:

1. A lightweight router decides whether live search is needed.
2. Results are fetched from the selected mode.
3. A lightweight reviewer decides one of:
   - `answer`
   - `refine`
   - `abstain`
4. If needed, the query is refined and searched one more time.
5. If evidence is still weak, Susu refuses cleanly instead of filling gaps.
6. If evidence is good enough, the final answer is summarized in Susu's own tone.

## Search Safety Rules

- Search answers must stay grounded in returned results
- Weak or incomplete evidence should produce a conservative answer, not a guessed one
- Ranking, list, and count questions are intentionally stricter than ordinary latest-info questions
- Short follow-up prompts like "search again" can inherit the previous search topic from recent inbound history

## Recent Behavior Themes

### Generic live-search grounding

High-level effect:

- live search no longer jumps straight from noisy results into freeform summarization
- query refinement and abstention are now first-class paths
- chart and ranking questions became stricter, but the hardening applies to `news`, `music`, and `web` generally

### Persistent typing refresh

High-level effect:

- typing no longer appears once and then disappears during longer generations
- typing now stays alive by periodic refresh while generation is still active

## Key Files

- Runtime logic:
  - `wa_agent.py`
- Admin API:
  - `susu_admin_server.py`
- Admin UI:
  - `susu-memory-admin.html`

## Development Workflow

Recommended local workflow:

1. Make changes in this repository.
2. Run `python -m py_compile wa_agent.py` before wider testing.
3. Verify the target behavior with small direct probes before deployment.

## Git Note

- Keep public and local-only operational notes separate
- Do not commit secrets, production-only paths, or rollback inventories into the public repository
