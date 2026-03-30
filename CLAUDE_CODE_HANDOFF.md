# Susu WhatsApp Agent Handoff For Claude Code

Last updated: 2026-03-30 HKT

## 1. Project Background

This project is an actively used WhatsApp-based AI companion called "Susu".

Primary product goal:

- make Susu feel like a believable WhatsApp girlfriend / companion
- preserve strong WhatsApp-native behavior
- keep memory, reminders, proactive messaging, search, and admin tooling under operator control

This is not just a chat demo. It already has:

- real WhatsApp runtime behavior
- message persistence
- memory layers
- reminders
- proactive messages
- admin UI
- grounded live search
- reply worker recovery

Current core weakness:

- the runtime / product shell is relatively mature
- the "conversation brain" is still too prompt-driven
- Susu is often weak at implicit intent tracking and multi-turn task state

Because of that, the current recommended direction is:

- keep the WhatsApp runtime shell
- gradually swap or augment the chat brain
- current exploration target: a switchable SillyTavern-based brain layer

## 2. Main Workspace

- Main workspace:
  - `C:\Users\ding7\Documents\gpt-susu-cloud`
- Current branch:
  - `codex/susu-cloud`
- Current local commit:
  - `caee46d`
- Main runtime file:
  - `C:\Users\ding7\Documents\gpt-susu-cloud\wa_agent.py`
- Admin API:
  - `C:\Users\ding7\Documents\gpt-susu-cloud\api_server.py`
- Admin UI:
  - `C:\Users\ding7\Documents\gpt-susu-cloud\susu-memory-admin.html`

Public open-source mirror:

- `C:\Users\ding7\Documents\susu-cloud`
- GitHub:
  - [SimonD0711/susu-cloud-ai-companion-on-whatsapp](https://github.com/SimonD0711/susu-cloud-ai-companion-on-whatsapp)

## 3. Authority / Deployment Model

Important:

- the authority production runtime is on Tokyo, not in another local worktree
- local development should continue in:
  - `C:\Users\ding7\Documents\gpt-susu-cloud`
- then deploy to Tokyo

Authoritative production files:

- `/var/www/html/wa_agent.py`
- `/var/www/html/api_server.py`
- `/var/www/html/susu-memory-admin.html`

Operational expectations for code changes:

1. edit locally in `C:\Users\ding7\Documents\gpt-susu-cloud`
2. run local `py_compile`
3. backup Tokyo target files before overwrite
4. upload
5. restart:
   - `wa-agent.service`
   - `cheungchau-api.service`

Do not assume any other worktree is the authority runtime.

## 4. Product Capabilities That Must Be Preserved

These are considered core and should not be broken during refactors.

### WhatsApp runtime behavior

- webhook-based inbound processing
- SQLite-backed message ledger
- quote / reply-context handling
- read receipt pacing
- fake typing pacing
- multi-bubble reply splitting
- cancellable reply generation
- stale worker recovery

### Memory and operator controls

- long-term memories
- layered short-term memories:
  - `within_24h`
  - `within_3d`
  - `within_7d`
- archive tier for older short-term memories
- reminders
- admin management UI
- editable Susu settings / runtime settings

### Search and grounding

- live search routing
- grounded answer behavior
- answer / refine / abstain review step
- avoid making up unsupported facts from weak search results

### Companion features

- proactive messages
- girlfriend-style tone
- quote-aware replies
- emoji frequency control

Future migration work must preserve all of the above.

## 5. Current Runtime Architecture

### 5.1 `wa_agent.py` responsibilities

This file currently does too much, but it is the real runtime shell.

It handles:

- inbound webhook parsing
- message persistence
- quote context parsing
- media fetch for images
- memory extraction
- search routing and grounding
- reminder parsing / scheduling
- proactive loop
- reply worker state
- subprocess-based cancellable generation
- WhatsApp send / mark-as-read / typing / reactions

### 5.2 Reply worker model

Current behavior:

- one reply worker per contact
- if a new message arrives before send:
  - old local reply generation job is terminated
  - pending inbound messages are recombined
  - a fresh reply is generated

This is already better than most simple WhatsApp bot examples online.

### 5.3 Read / typing behavior

Current design:

- first inbound message in a cycle gets a short read delay
- follow-up messages inside that initial delay share the same read deadline
- later messages in the same cycle are immediate
- typing appears only if generation is not ready quickly
- typing is periodically refreshed while generation is still running

### 5.4 Quote context

Inbound quoted replies are parsed from WhatsApp `context.id`.

The runtime can:

- detect which earlier message was quoted
- expose quote context to prompt/history
- send a real quoted outbound reply when the generated text starts with:
  - `QUOTE:<message_id>`

## 6. Current Model / Brain State

### Active default brain

Normal chat currently still uses:

- `claude-opus-4-6`

The shell around the model is more mature than the model orchestration itself.

### Current weakness

Susu is often weak at:

- implicit intent tracking
- understanding clue-based turns
- maintaining explicit multi-turn task state

Example pattern:

- user gives a clue like a course code
- human would infer "this is probably the answer"
- Susu often keeps chatting at surface level instead of solving the immediate task

### Current strategy direction

Do not replace the WhatsApp runtime.

Instead:

- keep `wa_agent.py` as the WhatsApp shell
- make the "brain" switchable
- first target brain integration: SillyTavern

## 7. New SillyTavern Brain Scaffold

This work has already started locally.

Relevant files:

- `C:\Users\ding7\Documents\gpt-susu-cloud\wa_agent.py`
- `C:\Users\ding7\Documents\gpt-susu-cloud\sillytavern_adapter.py`
- `C:\Users\ding7\Documents\gpt-susu-cloud\sillytavern_bridge_server.py`
- `C:\Users\ding7\Documents\gpt-susu-cloud\susu_brain_backend.py`
- `C:\Users\ding7\Documents\gpt-susu-cloud\susu-brain-backend.service`
- `C:\Users\ding7\Documents\gpt-susu-cloud\sillytavern-bridge.service`
- `C:\Users\ding7\Documents\gpt-susu-cloud\SILLYTAVERN_BRIDGE.md`

Current local commit:

- `caee46d` `Add switchable SillyTavern brain scaffold`
- `bbb7796` `Organize structured context handoff changes`

What was added:

- a new switchable `brain provider` concept
- a minimal HTTP adapter for a bridge-backed brain endpoint
- a guarded path so only ordinary text chat is eligible for SillyTavern
- fallback to the legacy Opus path if SillyTavern fails
- a structured multi-turn context payload builder for the SillyTavern path
- a local bridge server that exposes an OpenAI-style `/v1/chat/completions` endpoint
- a bridge service file so Tokyo can run the bridge as a separate process
- a local pure backend service that accepts Agnai-style structured payloads and calls the relay model

New env vars already supported in code:

- `WA_BRAIN_PROVIDER`
- `WA_BRAIN_FALLBACK_ON_ERROR`
- `WA_SILLYTAVERN_API_URL`
- `WA_SILLYTAVERN_API_KEY`
- `WA_SILLYTAVERN_MODEL`
- `WA_SILLYTAVERN_TIMEOUT_SECONDS`
- `WA_ST_BRIDGE_HOST`
- `WA_ST_BRIDGE_PORT`
- `WA_ST_BRIDGE_API_KEY`
- `WA_ST_BRIDGE_UPSTREAM_MODE`
- `WA_ST_BRIDGE_UPSTREAM_URL`
- `WA_ST_BRIDGE_UPSTREAM_API_KEY`
- `WA_ST_BRIDGE_UPSTREAM_MODEL`
- `WA_ST_BRIDGE_TIMEOUT_SECONDS`
- `WA_ST_BRIDGE_UPSTREAM_AUTH_HEADER`
- `WA_SUSU_BRAIN_HOST`
- `WA_SUSU_BRAIN_PORT`
- `WA_SUSU_BRAIN_API_KEY`
- `WA_SUSU_BRAIN_TIMEOUT_SECONDS`
- `WA_SUSU_BRAIN_MODEL`

Current default behavior:

- still `legacy`
- no production behavior changes unless the provider is explicitly switched

Current gating logic for SillyTavern path:

- only ordinary text chat
- not image replies
- not live-search-triggered requests
- not Claude Code special-route traffic

This is intentionally conservative for phase 1.

### 7.1 Current bridge contract

The current Phase 2 bridge contract is:

- `wa_agent.py` sends OpenAI-style chat payloads to `WA_SILLYTAVERN_API_URL`
- the bridge accepts:
  - `POST /v1/chat/completions`
  - `POST /chat/completions`
- the bridge returns an OpenAI-style response with:
  - `choices[0].message.content`

The bridge is intentionally generic.

It can sit in front of:

- an Agnai-style backend
- another OpenAI-compatible backend
- a future custom structured-chat service

SQLite remains the single runtime source of truth. The backend is expected to consume structured context only, and must not take ownership of `wa_messages`, `wa_reminders`, or other business tables.

## 8. Why Not Replace The Whole Runtime

SillyTavern should not replace the entire system.

Reasons:

- the SQLite message ledger is not just "memory"; it is runtime state
- reminders are product/business state, not just LLM memory
- reply workers, quote sending, read pacing, typing, and recovery loops are runtime behaviors
- the admin UI depends on the current database model

Recommended split:

- keep WhatsApp shell + DB + scheduling in this project
- move only the chat-brain / context-generation layer to SillyTavern

## 9. Database Guidance

### Tables / data that should remain the truth source here

- `wa_messages`
- `wa_reminders`
- contact state / runtime state
- operator-managed Susu settings

### Data that can be mirrored or partly consumed by SillyTavern

- long-term memory
- short-term memory summaries
- profile / persona material
- world/lore style knowledge

Recommended rule:

- SQLite remains the operational truth source
- SillyTavern consumes structured context, not raw operational ownership

## 10. Important Recent Fixes Already Landed

These are worth knowing before making larger changes.

### Quote handling

- inbound quote context is parsed and surfaced
- outbound `QUOTE:<message_id>` directive is handled before send

### Emoji frequency

- replies no longer keep emojis on nearly every sentence
- inline emoji count is trimmed

### Reply worker recovery

- stale workers can be recovered
- recovery loop exists so pending replies do not silently stall forever

### Read receipt pacing

- first read in a burst is delayed slightly
- subsequent messages after that first read become immediate in the same cycle

### Live search short-term memory insertion removed

- the runtime no longer stores:
  - `對方啱啱問過：...`
  as explicit short-term memory entries

### Public repo sync

The public repository has already been updated to release `v0.1.2` for share-safe runtime improvements.

## 11. Current Search State

Current search behavior is grounded, but not yet "mature assistant" level.

Search currently includes:

- weather
- news
- music
- web

The shell already added multi-source groundwork, but not all external providers are always configured.

Important principle:

- do not let weak evidence become a confident answer
- preserve abstain / refine behavior

If integrating SillyTavern more deeply, keep the search/tool layer outside the brain where possible, then pass structured evidence into the brain for tone shaping.

## 12. Current Voice State

Do not assume voice STT is already implemented in this runtime.

The current runtime has discussed "voice mode" and message style behavior, but does not yet have a full inbound audio-to-text pipeline wired in as a finished product feature.

Future desired direction:

- inbound `audio` / `ptt`
  - download media
  - STT
  - store transcript
  - feed transcript into normal reply flow
- optional outbound TTS

## 13. Recommended Next Steps

Priority order:

### Phase 1

Finish the SillyTavern bridge path for ordinary text chat.

Specifically:

- define the exact bridge protocol
- confirm the target endpoint
- validate payload/response shape
- test with local `WA_BRAIN_PROVIDER=sillytavern`

### Phase 2

Add a context payload builder specifically for the SillyTavern brain.

The current scaffold still sends a prompt-like payload.
This should become more structured over time.

### Phase 3

Improve state tracking for implicit tasks.

Examples:

- clue-following
- guessing tasks
- "you asked me what course I am in"
- carrying explicit unresolved user prompts across multiple turns

### Phase 4

Add STT / TTS without disturbing the runtime shell.

### Phase 5

Optionally make proactive and reminder content generation use the new brain after ordinary chat is stable.

## 14. Do / Do Not

### Do

- continue editing in `C:\Users\ding7\Documents\gpt-susu-cloud`
- preserve the WhatsApp-native behavior shell
- keep fallbacks during migration
- prefer additive migration over destructive replacement
- use local `py_compile` before deployment

### Do not

- do not replace the whole runtime with a generic chat frontend
- do not move reminders or runtime truth entirely into SillyTavern
- do not remove SQLite message history
- do not assume public GitHub code is the full production authority
- do not leak secrets into docs or commits

## 15. Suggested First Task For Claude Code

Recommended immediate handoff task:

- continue the SillyTavern migration in a safe phase-1 way
- keep current runtime behavior unchanged by default
- make ordinary text chat switchable to a SillyTavern bridge endpoint
- add a more explicit structured payload builder instead of sending the full prompt as a single user string
- keep automatic fallback to legacy Opus replies

If more specificity is needed, the first implementation target should be:

1. design `build_sillytavern_context_payload(...)`
2. keep search/image/Claude-route out of the SillyTavern path
3. add local-only integration test probes
4. do not deploy until the bridge protocol is confirmed
