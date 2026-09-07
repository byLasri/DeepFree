# DeepSeek Web Protocol Documentation

This document describes the actual protocol observed from the DeepSeek web application (`https://chat.deepseek.com`) via browser network captures (Firefox HAR export).

## Primary Endpoint

```
POST https://chat.deepseek.com/api/v0/chat/completion
```

**Response:** `HTTP/2 200` with `Content-Type: text/event-stream; charset=utf-8`

---

## Request Structure

### HTTP Headers

| Header | Value | Required | Notes |
|--------|-------|----------|-------|
| `Accept` | `*/*` | Yes | |
| `Accept-Encoding` | `gzip, deflate, br, zstd` | Yes | |
| `Accept-Language` | `en-US,en;q=0.9` | Yes | |
| `Authorization` | `Bearer <token>` | Yes | Session auth token |
| `Content-Type` | `application/json` | Yes | |
| `Cookie` | `<session cookies>` | Yes | Session cookies (ds_session_id, smidV2) |
| `Host` | `chat.deepseek.com` | Yes | |
| `Origin` | `https://chat.deepseek.com` | Yes | |
| `Referer` | `https://chat.deepseek.com/a/chat/s/<chat_session_id>` | Yes | Must match chat session |
| `User-Agent` | Browser UA string | Yes | |
| `x-client-bundle-id` | `com.deepseek.chat` | Yes | Static |
| `x-client-locale` | `en_US` | Yes | Static |
| `x-client-platform` | `web` | Yes | Static |
| `x-client-timezone-offset` | `-25200` | Yes | Timezone offset in seconds |
| `x-client-version` | `2.4.0` | Yes | Client version |
| `x-ds-pow-response` | `<dynamic>` | **Yes** | Proof-of-Work response (base64 JSON) |
| `x-hif-leim` | `<dynamic>` | **Yes** | Anti-abuse/fingerprint |

### JSON Body

```json
{
  "chat_session_id": "SESSION_ID",
  "parent_message_id": null,
  "model_type": "expert",
  "prompt": "User message",
  "ref_file_ids": [],
  "thinking_enabled": true,
  "search_enabled": false,
  "action": null,
  "preempt": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `chat_session_id` | string | Yes | Chat session identifier from URL |
| `parent_message_id` | integer/null | Yes | Previous message ID for conversation continuity |
| `model_type` | string | Yes | Model variant (`expert`, `chat`, `default`) |
| `prompt` | string | Yes | User input |
| `ref_file_ids` | array | No | Referenced file IDs |
| `thinking_enabled` | boolean | No | Enable reasoning (default: true) |
| `search_enabled` | boolean | No | Enable web search (default: false) |
| `action` | string/null | No | `retry`, `continue`, or `null` |
| `preempt` | boolean | No | Preemptive generation flag |

---

## Response: Server-Sent Events (SSE)

The response is a streaming `text/event-stream` with multiple event types.

### Response Headers of Note

| Header | Value | Description |
|--------|-------|-------------|
| `content-type` | `text/event-stream; charset=utf-8` | SSE stream |
| `cache-control` | `no-cache` | No caching |
| `x-ds-sse-heartbeat-timeout-secs` | `8` | Heartbeat timeout |
| `x-ds-trace-id` | `<trace-id>` | Request tracing ID |

### Event Types

#### 1. `ready` Event
```json
event: ready
data: {"request_message_id":1,"response_message_id":2,"model_type":"expert"}
```
- First event in stream
- Contains message IDs for the exchange

#### 2. `update_session` Event
```json
event: update_session
data: {"updated_at":1788746279.247738}
```
- Session timestamp updates (Unix timestamp)
- Occurs multiple times during stream

#### 3. Data Events (no event name) - Initial Response Object
```json
data: {"v":{"response":{"message_id":2,"parent_id":1,"model":"","role":"ASSISTANT","thinking_enabled":true,"ban_edit":false,"ban_regenerate":false,"status":"WIP","incomplete_message":null,"accumulated_token_usage":0,"feedback":null,"inserted_at":1788746279.238456,"search_enabled":false,"fragments":[{"id":2,"type":"THINK","content":"We","elapsed_secs":null,"references":[],"stage_id":1}],"conversation_mode":"DEFAULT","has_pending_fragment":false,"auto_continue":false,"search_triggered":false}}
```
- Full response object with fragments array
- Includes thinking fragments (`type: "THINK"`) and response fragments (`type: "RESPONSE"`)

#### 4. Data Events - JSON Patch Operations
Path-based JSON Patch operations:
```json
data: {"p":"response/fragments/-1/content","o":"APPEND","v":" need"}
data: {"v":" answer"}
data: {"v":" user"}
data: {"v":" says"}
data: {"v":" \""}
data: {"v":"say"}
data: {"v":" ok"}
data: {"v":"\\\""}
data: {"v":" Need"}
data: {"v":" respond"}
data: {"v":" \""}
data: {"v":"ok"}
data: {"v":"\\\""}
data: {"v":" Simple"}
data: {"v":"."}
data: {"p":"response/fragments/-1/elapsed_secs","o":"SET","v":0.859048815}
data: {"p":"response/fragments","o":"APPEND","v":[{"id":3,"type":"RESPONSE","content":"ok","references":[],"stage_id":1}]}
data: {"p":"response","o":"BATCH","v":[{"p":"accumulated_token_usage","v":36},{"p":"quasi_status","v":"FINISHED"}]}
data: {"p":"response/status","o":"SET","v":"FINISHED"}
```

| Path | Operation | Description |
|------|-----------|-------------|
| `response/fragments/-1/content` | APPEND | Streaming text content (thinking + response) |
| `response/fragments/-1/elapsed_secs` | SET | Generation time in seconds |
| `response/status` | SET | `WIP` → `FINISHED` (also `quasi_status`) |
| `response/fragments` | APPEND | Complete fragment array update |
| `response` | BATCH | Batch update (token usage, status) |

**Note:** Some data events contain only `{"v": "..."}` without `p` and `o` fields - these are continuation fragments for the last path.

#### 5. `title` Event
```json
event: title
data: {"content":"Say ok"}
```
- Auto-generated conversation title

#### 6. `close` Event
```json
event: close
data: {"click_behavior":"none","auto_resume":false}
```
- Stream termination signal

---

## Message ID Flow

### Turn 1 (New Conversation)
```
Request:
  chat_session_id: "abc123"
  parent_message_id: null

Response (ready event):
  request_message_id: 1
  response_message_id: 2
```

### Turn 2 (Continuation)
```
Request:
  chat_session_id: "abc123"
  parent_message_id: 2  ← Previous response_message_id

Response (ready event):
  request_message_id: 2
  response_message_id: 3
```

### Pattern
```
parent_message_id (Turn N) = response_message_id (Turn N-1)
request_message_id (Turn N) = parent_message_id (Turn N)
```

---

## Session/Conversation Management

### Chat Session ID
- Obtained from URL: `https://chat.deepseek.com/a/chat/s/<chat_session_id>`
- Persists across conversation turns
- Created via `POST /api/v0/chat_session/create` (returns new session ID)

### Message IDs
- `request_message_id`: Sequential identifier for user message
- `response_message_id`: Sequential identifier for assistant response
- Both increment monotonically within a chat session

### Fragment Types
- `THINK`: Model's internal reasoning/thinking process
- `RESPONSE`: Final user-visible response content

---

## Authentication & Session Lifecycle

### Observed Flow
```
1. User logs in → Receives session cookies + Authorization token
2. Creates/opens chat session → Gets chat_session_id (via /api/v0/chat_session/create)
3. Sends completion requests with:
   - Authorization: Bearer <token>
   - Cookie: ds_session_id=<...>; smidV2=<...>
   - x-ds-pow-response: <base64 PoW response>
   - x-hif-leim: <fingerprint>
4. Session maintained via cookies + token
```

### Cookies
| Cookie | Description |
|--------|-------------|
| `ds_session_id` | DeepSeek session identifier |
| `smidV2` | Session/device identifier |
| `.thumbcache_...` | Thumbnail cache (empty) |

### Dynamic Headers Investigation

#### `x-ds-pow-response` (Proof-of-Work)
- **Format:** Base64-encoded JSON:
```json
{
  "algorithm": "DeepSeekHashV1",
  "challenge": "018c5d809382c6730c596c0aa750cd584a45139eb92a53c02d57ed257cbf6882",
  "salt": "b9455676eb7a44a1fa47",
  "answer": 113060,
  "signature": "f228a4150c6e3da508dbf3eb5a8af3306e49a57adb26cc1b5029421a44f2b6e9",
  "target_path": "/api/v0/chat/completion"
}
```
- **Source:** Generated by client-side JavaScript (likely WebAssembly)
- **Challenge source:** Unknown - possibly from separate endpoint or embedded in page
- **Variability:** Changes per request (new challenge per request)
- **Algorithm:** `DeepSeekHashV1` - custom PoW hash function
- **Status:** Requires browser JS analysis to reproduce legitimately

#### `x-hif-leim`
- **Format:** Two-part value separated by `.` (e.g., `BgH7I7g1cqigR+8XV+1y+xWQmuypjuhm2usNJqnK47xLG8T2NcJH7jU=.uxA+cpEf4ZqZK7FL`)
- **Source:** Unknown - possibly browser fingerprint / anti-abuse
- **Variability:** Changes per request
- **Status:** Requires further investigation

---

## Tool/Action Protocol

**Current Finding:** `TEXT_ONLY` / `NOT_FOUND`

No structured tool calling (`tool_calls`, `function_calls`, `tools`, `actions`, `plugins`, `mcp`, `command`) observed in:
- Request payloads
- SSE response events
- Client-side network traffic

DeepSeek web appears to use **text-only** streaming with reasoning (`thinking_enabled`) but no native tool protocol.

---

## Streaming Behavior

- **Confirmed:** SSE streaming with incremental content delivery
- **Fragment Types:** `THINK` (reasoning) and `RESPONSE` (final answer)
- **Fragment Reconstruction:** Content arrives via `APPEND` operations on `response/fragments/-1/content` and bare `{"v": "..."}` continuations
- **Completion Signal:** `response/status` set to `FINISHED` (also `quasi_status`)
- **Timing:** `elapsed_secs` tracks generation time
- **Token Usage:** `accumulated_token_usage` in BATCH updates

---

## Known Endpoints

| Endpoint | Method | Purpose | Status |
|----------|--------|---------|--------|
| `/api/v0/chat/completion` | POST | Main completion | ✅ Documented |
| `/api/v0/chat_session/create` | POST | Create chat session | ✅ Documented |
| `/api/v0/chat/sessions` | GET | List sessions | ⬜ Pending |
| `/api/v0/auth/login` | POST | Login | ⬜ Pending |
| `/api/v0/auth/refresh` | POST | Refresh token | ⬜ Pending |
| `/api/v0/pow/challenge` | GET | Get PoW challenge | ⬜ Pending |

---

## Example: Sanitized Request

```http
POST /api/v0/chat/completion HTTP/2
Host: chat.deepseek.com
Authorization: Bearer [REDACTED]
Cookie: ds_session_id=[REDACTED]; smidV2=[REDACTED]
Content-Type: application/json
x-ds-pow-response: [REDACTED]
x-hif-leim: [REDACTED]
Origin: https://chat.deepseek.com
Referer: https://chat.deepseek.com/a/chat/s/[CHAT_SESSION_ID]

{
  "chat_session_id": "[CHAT_SESSION_ID]",
  "parent_message_id": null,
  "model_type": "expert",
  "prompt": "say ok",
  "ref_file_ids": [],
  "thinking_enabled": true,
  "search_enabled": false,
  "action": null,
  "preempt": false
}
```

---

## Example: Sanitized SSE Response

```
event: ready
data: {"request_message_id":1,"response_message_id":2,"model_type":"expert"}

event: update_session
data: {"updated_at":1788746279.247738}

data: {"v":{"response":{"message_id":2,"parent_id":1,"model":"","role":"ASSISTANT","thinking_enabled":true,"ban_edit":false,"ban_regenerate":false,"status":"WIP","incomplete_message":null,"accumulated_token_usage":0,"feedback":null,"inserted_at":1788746279.238456,"search_enabled":false,"fragments":[{"id":2,"type":"THINK","content":"We","elapsed_secs":null,"references":[],"stage_id":1}],"conversation_mode":"DEFAULT","has_pending_fragment":false,"auto_continue":false,"search_triggered":false}}

data: {"p":"response/fragments/-1/content","o":"APPEND","v":" need"}
data: {"v":" answer"}
data: {"v":" user"}
data: {"v":" says"}
data: {"v":" \""}
data: {"v":"say"}
data: {"v":" ok"}
data: {"v":"\\\""}
data: {"v":" Need"}
data: {"v":" respond"}
data: {"v":" \""}
data: {"v":"ok"}
data: {"v":"\\\""}
data: {"v":" Simple"}
data: {"v":"."}
data: {"p":"response/fragments/-1/elapsed_secs","o":"SET","v":0.859048815}
data: {"p":"response/fragments","o":"APPEND","v":[{"id":3,"type":"RESPONSE","content":"ok","references":[],"stage_id":1}]}
data: {"p":"response","o":"BATCH","v":[{"p":"accumulated_token_usage","v":36},{"p":"quasi_status","v":"FINISHED"}]}
data: {"p":"response/status","o":"SET","v":"FINISHED"}

event: update_session
data: {"updated_at":1788746279.8374898}

event: title
data: {"content":"Say ok"}

event: close
data: {"click_behavior":"none","auto_resume":false}
```