# DeepSeek Web Protocol Documentation

This document describes the actual protocol observed from the DeepSeek web application (`https://chat.deepseek.com`) via browser network captures.

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
| `Cookie` | `<session cookies>` | Yes | Session cookies |
| `Host` | `chat.deepseek.com` | Yes | |
| `Origin` | `https://chat.deepseek.com` | Yes | |
| `Referer` | `https://chat.deepseek.com/a/chat/s/<chat_session_id>` | Yes | Must match chat session |
| `User-Agent` | Browser UA string | Yes | |
| `x-client-bundle-id` | `com.deepseek.chat` | Yes | Static |
| `x-client-locale` | `en_US` | Yes | Static |
| `x-client-platform` | `web` | Yes | Static |
| `x-client-timezone-offset` | `-25200` | Yes | Timezone offset in seconds |
| `x-client-version` | `2.4.0` | Yes | Client version |
| `x-ds-pow-response` | `<dynamic>` | **Unknown** | Proof-of-Work response |
| `x-hif-leim` | `<dynamic>` | **Unknown** | Anti-abuse/fingerprint |

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
  "action": "retry",
  "preempt": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `chat_session_id` | string | Yes | Chat session identifier from URL |
| `parent_message_id` | integer/null | Yes | Previous message ID for conversation continuity |
| `model_type` | string | Yes | Model variant (`expert`, `chat`, etc.) |
| `prompt` | string | Yes | User input |
| `ref_file_ids` | array | No | Referenced file IDs |
| `thinking_enabled` | boolean | No | Enable reasoning (default: true) |
| `search_enabled` | boolean | No | Enable web search (default: false) |
| `action` | string | No | `retry`, `continue`, etc. |
| `preempt` | boolean | No | Preemptive generation flag |

---

## Response: Server-Sent Events (SSE)

The response is a streaming `text/event-stream` with multiple event types.

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
data: {"updated_at":"2024-01-15T10:30:00Z"}
```
- Session timestamp updates
- Occurs multiple times during stream

#### 3. Data Events (no event name)
Path-based JSON Patch operations:
```json
data: {"p":"response/fragments/-1/content","o":"APPEND","v":"Hello"}
data: {"p":"response/fragments/-1/content","o":"APPEND","v":" world"}
data: {"p":"response/fragments/-1/elapsed_secs","o":"SET","v":1.5}
data: {"p":"response/status","o":"SET","v":"FINISHED"}
data: {"p":"response/fragments","o":"APPEND","v":[...]}
data: {"p":"response","o":"BATCH","v":[...]}
```

| Path | Operation | Description |
|------|-----------|-------------|
| `response/fragments/-1/content` | APPEND | Streaming text content |
| `response/fragments/-1/elapsed_secs` | SET | Generation time in seconds |
| `response/status` | SET | `IN_PROGRESS`, `FINISHED`, `ERROR` |
| `response/fragments` | APPEND | Complete fragment array |
| `response` | BATCH | Batch update |

#### 4. `title` Event
```json
event: title
data: {"content":"Say hello"}
```
- Auto-generated conversation title

#### 5. `close` Event
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
- Created via separate session creation endpoint (TBD)

### Message IDs
- `request_message_id`: Sequential identifier for user message
- `response_message_id`: Sequential identifier for assistant response
- Both increment monotonically within a chat session

---

## Authentication & Session Lifecycle

### Observed Flow
```
1. User logs in → Receives session cookies + Authorization token
2. Creates/opens chat session → Gets chat_session_id
3. Sends completion requests with:
   - Authorization: Bearer <token>
   - Cookie: <session cookies>
   - x-ds-pow-response: <dynamic>
   - x-hif-leim: <dynamic>
4. Session maintained via cookies + token
```

### Dynamic Headers Investigation

#### `x-ds-pow-response`
- **Source:** Likely generated by client-side JavaScript (Proof-of-Work)
- **Format:** Appears to contain `algorithm`, `challenge`, `salt`, `answer`, `signature`, `target_path`
- **Variability:** Changes per request
- **Status:** Requires further investigation (browser JS analysis needed)

#### `x-hif-leim`
- **Source:** Unknown - possibly browser fingerprint / anti-abuse
- **Variability:** Changes per request/session
- **Status:** Requires further investigation

---

## Tool/Action Protocol

**Current Finding:** `NOT_FOUND` / `UNKNOWN`

No structured tool calling (`tool_calls`, `function_calls`, `actions`) observed in:
- Request payloads
- SSE response events
- Client-side network traffic

DeepSeek web appears to use **text-only** streaming with no native tool protocol.

---

## Streaming Behavior

- **Confirmed:** SSE streaming with incremental content delivery
- **Fragment Reconstruction:** Content arrives via `APPEND` operations on `response/fragments/-1/content`
- **Completion Signal:** `response/status` set to `FINISHED`
- **Timing:** `elapsed_secs` tracks generation time

---

## Known Endpoints (To Investigate)

| Endpoint | Method | Purpose | Status |
|----------|--------|---------|--------|
| `/api/v0/chat/completion` | POST | Main completion | ✅ Documented |
| `/api/v0/chat/sessions` | GET | List sessions | ⬜ Pending |
| `/api/v0/chat/session` | POST | Create session | ⬜ Pending |
| `/api/v0/auth/login` | POST | Login | ⬜ Pending |
| `/api/v0/auth/refresh` | POST | Refresh token | ⬜ Pending |
| `/api/v0/pow/challenge` | GET | Get PoW challenge | ⬜ Pending |

---

## Example: Sanitized Request

```http
POST /api/v0/chat/completion HTTP/2
Host: chat.deepseek.com
Authorization: Bearer [REDACTED]
Cookie: [REDACTED]
Content-Type: application/json
x-ds-pow-response: [REDACTED]
x-hif-leim: [REDACTED]
Origin: https://chat.deepseek.com
Referer: https://chat.deepseek.com/a/chat/s/[CHAT_SESSION_ID]

{
  "chat_session_id": "[CHAT_SESSION_ID]",
  "parent_message_id": null,
  "model_type": "expert",
  "prompt": "Say hello",
  "ref_file_ids": [],
  "thinking_enabled": true,
  "search_enabled": false,
  "action": "retry",
  "preempt": false
}
```

---

## Example: Sanitized SSE Response

```
event: ready
data: {"request_message_id":1,"response_message_id":2,"model_type":"expert"}

event: update_session
data: {"updated_at":"[TIMESTAMP]"}

data: {"p":"response/fragments/-1/content","o":"APPEND","v":"Hello"}

data: {"p":"response/fragments/-1/content","o":"APPEND","v":" world"}

data: {"p":"response/status","o":"SET","v":"FINISHED"}

event: title
data: {"content":"Say hello"}

event: close
data: {"click_behavior":"none","auto_resume":false}
```