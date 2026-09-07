# Proxy Architecture Design

## Overview

This document describes the planned architecture for an OpenAI/Codex-compatible proxy that translates between OpenAI API semantics and the DeepSeek web protocol.

## Target Architecture

```
┌─────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐     ┌─────────────────────┐
│  Codex/OpenCode │────▶│  OpenAI-Compatible   │────▶│  DeepSeek Protocol   │────▶│  DeepSeek Web       │
│  (Client)       │     │  API Layer           │     │  Adapter             │     │  Backend            │
└─────────────────┘     └──────────────────────┘     └──────────────────────┘     └─────────────────────┘
                              │                              │                            │
                              ▼                              ▼                            ▼
                       POST /v1/chat/completions       Internal Event Model       POST /api/v0/chat/
                       POST /v1/responses              Normalized Events          completion (SSE)
                       GET /v1/models                  Session Management
```

---

## Component Breakdown

### 1. OpenAI-Compatible API Layer

**Responsibilities:**
- Accept OpenAI-format requests (`/v1/chat/completions`, `/v1/responses`)
- Validate request structure
- Handle authentication (API keys)
- Route to internal representation
- Stream responses back in OpenAI SSE format

**Endpoints:**
- `POST /v1/chat/completions` - Chat completions (streaming + non-streaming)
- `POST /v1/responses` - Responses API (future)
- `GET /v1/models` - Model listing

**Request Translation:**
```python
# OpenAI → Internal
{
  "model": "deepseek-chat",
  "messages": [...],
  "stream": true,
  "tools": [...],           # → Not supported in Phase 1
  "tool_choice": "auto",    # → Not supported in Phase 1
}
```

### 2. Internal Representation

**Normalized Event Model:**
```python
@dataclass
class InternalEvent:
    event_type: EventType          # CONTENT, TOOL_CALL, TOOL_RESULT, STATUS, ERROR
    content: str                   # Text content
    tool_calls: list[ToolCall]     # Structured tool calls (future)
    tool_results: list[ToolResult] # Tool results (future)
    metadata: dict                 # Message IDs, timing, etc.
    is_final: bool                 # Stream completion
```

**Session Management:**
- Map OpenAI conversation → DeepSeek chat_session_id
- Track message_id chains
- Handle context window / history

### 3. DeepSeek Protocol Adapter

**Responsibilities:**
- Translate Internal → DeepSeek request format
- Manage DeepSeek session lifecycle (create session via `/api/v0/chat_session/create`)
- Handle authentication (cookies, tokens, PoW)
- Parse DeepSeek SSE → Internal events
- Handle errors / retries

**Key Challenges:**
- Dynamic headers (`x-ds-pow-response`, `x-hif-leim`)
- Session initialization (requires `chat_session_id` from session creation endpoint)
- Message ID chaining
- No native tool calling support
- PoW generation (`DeepSeekHashV1` algorithm, likely WASM)
- Fingerprint header (`x-hif-leim`) generation

**Discovered Endpoints:**
- `POST /api/v0/chat/completion` - Main completion (SSE)
- `POST /api/v0/chat_session/create` - Create new chat session

**Request Translation:**
```python
# Internal → DeepSeek
{
  "chat_session_id": "abc123",
  "parent_message_id": 5,
  "model_type": "expert",
  "prompt": "User message",
  "thinking_enabled": true,
  "search_enabled": false,
}
```

**Response Translation:**
```
DeepSeek SSE → Internal Events
- ready → SESSION_READY (with message IDs)
- content fragments → CONTENT_DELTA events
- status: FINISHED → STREAM_END
- title → CONVERSATION_TITLE
- close → SESSION_CLOSE
```

### 4. DeepSeek Web Backend

**Endpoint:** `POST https://chat.deepseek.com/api/v0/chat/completion`

**Protocol:** SSE over HTTP/2

**Authentication:** Bearer token + Cookies + Dynamic headers

---

## Data Flow

### Non-Streaming Request
```
Client → OpenAI API Layer → Internal Request → Adapter → DeepSeek SSE
                                                      ↓
                                              Collect all events
                                                      ↓
                                              Build complete response
                                                      ↓
                                              Return OpenAI response
```

### Streaming Request
```
Client → OpenAI API Layer → Internal Request → Adapter → DeepSeek SSE
                                                      ↓
                                              Parse each SSE event
                                                      ↓
                                              Translate to OpenAI chunk
                                                      ↓
                                              Yield chunk to client
```

---

## Session Management Strategy

### DeepSeek Session
- `chat_session_id`: Persistent across conversation
- `parent_message_id`: Chains messages (previous response_message_id)
- Cookies + Authorization: Maintained per user session

### Proxy Session Mapping
```
OpenAI Conversation (messages[]) 
    │
    ├─→ DeepSeek chat_session_id (created on first request)
    ├─→ Message ID chain tracking
    └─→ Cookie/token storage per user
```

### Authentication Handling
- **Phase 1:** Manual credential injection via environment
- **Phase 2:** Automated login flow (if feasible)
- **Phase 3:** Token refresh / session persistence

---

## Tool Calling Translation

**Current Status:** DeepSeek web does **not** support native tool calling.

**Planned Approach (if needed):**
1. **Text-based tool calling:** Inject tool definitions in system prompt, parse model's text output for tool calls
2. **Function calling shim:** Local executor that parses structured text output
3. **Fallback:** Document as unsupported, text-only

**OpenAI → DeepSeek Tool Translation:**
```
OpenAI tools array → System prompt injection → Text parsing → Local execution → Result injection
```

---

## Error Handling

| DeepSeek Error | OpenAI Error |
|----------------|--------------|
| 401 Unauthorized | 401 Invalid API key |
| 403 Forbidden | 403 Access denied |
| 429 Rate limited | 429 Rate limit |
| 5xx Server error | 500 Internal error |
| SSE parse error | 500 Internal error |
| Session expired | 401 Session expired |

---

## Configuration

```python
@dataclass
class ProxyConfig:
    # DeepSeek credentials (per user)
    deepseek_authorization: str
    deepseek_cookie: str
    deepseek_chat_session_id: str
    
    # Proxy settings
    host: str = "0.0.0.0"
    port: int = 8080
    
    # DeepSeek overrides
    model_type: str = "expert"
    thinking_enabled: bool = True
    search_enabled: bool = False
```

---

## Implementation Phases

### Phase 1 (Current) - Protocol Investigation
- [x] Reproduce browser completion
- [x] Parse SSE stream
- [x] Extract message IDs
- [x] Record/redact exchanges
- [ ] Investigate auth lifecycle
- [ ] Analyze dynamic headers
- [ ] Document protocol

### Phase 2 - Basic Proxy
- [ ] Implement OpenAI `/v1/chat/completions` endpoint
- [ ] Build DeepSeek adapter
- [ ] Session management
- [ ] Streaming support
- [ ] Error handling

### Phase 3 - Advanced Features
- [ ] Tool calling shim
- [ ] Multi-user support
- [ ] Automated auth (if feasible)
- [ ] Model listing
- [ ] Responses API

### Phase 4 - Production Hardening
- [ ] Rate limiting
- [ ] Logging/monitoring
- [ ] Health checks
- [ ] Deployment configs

---

## Security Considerations

1. **Credential Storage:** Never log or persist raw credentials
2. **Request Redaction:** All recordings auto-redact sensitive headers
3. **Session Isolation:** Per-user session state
4. **Transport:** HTTPS only in production
5. **Audit Trail:** Sanitized request/response logging

---

## Testing Strategy

### Unit Tests
- SSE parser
- Request/response translation
- Session state management
- Credential redaction

### Integration Tests
- Live DeepSeek completion (opt-in)
- Multi-turn conversations
- Streaming vs non-streaming
- Error scenarios

### Fixtures
- Sanitized HAR captures
- SSE stream samples
- Expected translations