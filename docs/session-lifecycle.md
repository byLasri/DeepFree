# Session Lifecycle

## Session Types

### 1. Account Session (AuthState)
Long-lived, survives across chat sessions.

**Components:**
- `Authorization` Bearer token
- `ds_session_id` cookie
- `smidV2` cookie
- Other cookies
- User-Agent string

**Lifetime:** Unknown (likely tied to cookie expiry, potentially weeks/months)

**Scope:** All chat sessions for a user

### 2. Chat Session (ChatSession)
Created per conversation, 3-day TTL.

**Creation:**
```
POST /api/v0/chat_session/create
Headers: Authorization, Cookie
Body: {}
Response: { chat_session: { id: "uuid", ttl_seconds: 259200, ... } }
```

**Components:**
- `chat_session_id` (UUID)
- `current_parent_message_id` (chains turns)
- `message_counter`
- `model_type` (expert/default/vision)
- `title` (auto-generated)
- `created_at`, `updated_at`
- `ttl_seconds`: 259200 (3 days)

**Lifetime:** 3 days from creation

**Scope:** Single conversation thread

## Message ID Chaining

```
Turn 1:
  Request:  parent_message_id = null
  Response: request_message_id = 1, response_message_id = 2

Turn 2:
  Request:  parent_message_id = 2
  Response: request_message_id = 2, response_message_id = 3

Turn N:
  Request:  parent_message_id = response_message_id(Turn N-1)
  Response: request_message_id = parent_message_id, response_message_id = N+1
```

**Rule:** `parent_message_id` in request MUST equal `response_message_id` from previous turn.

## Session State Transitions

```
[No Session]
    ↓ POST /chat_session/create
[ChatSession created: chat_session_id=X, parent=null]
    ↓ POST /completion (parent_message_id=null)
[Turn 1: request_message_id=1, response_message_id=2]
    ↓ POST /completion (parent_message_id=2)
[Turn 2: request_message_id=2, response_message_id=3]
    ...
    ↓ (after 3 days or explicit delete)
[Session expired]
    ↓ POST /chat_session/create
[New ChatSession]
```

## Multi-Session Support

- User can have multiple concurrent chat sessions
- Each has independent `chat_session_id` and message ID chain
- Switching sessions = changing `chat_session_id` in request
- No cross-session context sharing observed

## Session Expiration Handling

**When chat session expires (3 days):**
- Completion requests with expired `chat_session_id` → Likely 422/404
- Must create new session via `/chat_session/create`
- Previous conversation context lost (unless exported)

**When account session expires:**
- `Authorization` token becomes invalid → 40003 INVALID_TOKEN
- Cookies may still work for session creation
- Requires re-login (Google OAuth or email/password)

## Implementation (src/session.py)

```python
AuthState          # Account-scoped, long-lived
ChatSession        # Chat-scoped, 3-day TTL
DynamicHeaders     # Request-scoped, per-request
DeepSeekSession    # Combined state
DynamicHeaderProvider  # Abstraction for PoW/hif generation
```