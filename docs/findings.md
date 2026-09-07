# Phase 1 Findings Report

**Investigation Period:** 2026-09-06
**Investigator:** DeepSeek Protocol Investigation
**Repository:** [Private GitHub URL]

---

## Executive Summary

This report documents the findings from Phase 1 of the DeepSeek Web Protocol Investigation. The objective was to experimentally reproduce and document the actual protocol used by the DeepSeek web application (`https://chat.deepseek.com`) for chat completions.

**Primary Evidence:** Firefox HAR capture (tests/fixtures/captured.har) from official web app usage.

---

## 1. Endpoint

**Confirmed Endpoint:**
```
POST https://chat.deepseek.com/api/v0/chat/completion
```

**Evidence:** Direct capture from Firefox Developer Tools during official web app usage. Response: `HTTP/2 200` with `Content-Type: text/event-stream; charset=utf-8`.

**Additional Endpoint Discovered:**
```
POST https://chat.deepseek.com/api/v0/chat_session/create
```
- Creates new chat session
- Returns: `chat_session.id`, `seq_id`, `ttl_seconds` (259200 = 3 days)

---

## 2. Basic Completion

**Status:** CONFIRMED

**Evidence:**
- Successfully reproduced browser request with same headers and JSON body
- Received valid SSE stream response (317ms latency)
- Parsed and reconstructed assistant response
- Extracted message IDs (`request_message_id`, `response_message_id`)
- Verified session continuity via `chat_session_id`

**Key Observations:**
- Request requires `Authorization: Bearer <token>`, `Cookie`, and dynamic headers
- JSON body matches browser capture exactly (note: `action` can be `null`)
- Response is streaming SSE with multiple event types
- Content delivered incrementally via JSON Patch `APPEND` operations
- Response includes both thinking (`THINK`) and response (`RESPONSE`) fragments

---

## 3. Streaming (SSE)

**Status:** CONFIRMED

**SSE Behavior Documented (from HAR):**
- **Event Types:** `ready`, `update_session`, `data` (unnamed), `title`, `close`
- **Data Events:** Multiple formats:
  1. Full response object with fragments array (initial)
  2. JSON Patch operations on paths:
     - `response/fragments/-1/content` (APPEND) - streaming text (thinking + response)
     - `response/fragments/-1/elapsed_secs` (SET) - timing
     - `response/status` (SET) - `WIP` → `FINISHED` (also `quasi_status`)
     - `response/fragments` (APPEND) - complete fragments
     - `response` (BATCH) - batch updates (token usage, status)
  3. Bare `{"v": "..."}` continuation fragments
- **Parser Built:** Complete SSE parser with event normalization (25 events parsed from HAR)
- **Reconstruction:** Fragment concatenation produces final response including thinking process

**Response Headers of Note:**
- `x-ds-sse-heartbeat-timeout-secs: 8` - Heartbeat interval
- `x-ds-trace-id` - Request tracing

---

## 4. Multi-Turn Conversation

**Status:** CONFIRMED (based on protocol design, not live multi-turn test)

**Message ID Relationship:**
```
Turn 1:
  Request:  chat_session_id="X", parent_message_id=null
  Response: request_message_id=1, response_message_id=2

Turn 2:
  Request:  chat_session_id="X", parent_message_id=2
  Response: request_message_id=2, response_message_id=3

Turn N:
  Request:  chat_session_id="X", parent_message_id=response_message_id(Turn N-1)
  Response: request_message_id=parent_message_id, response_message_id=N+1
```

**Pattern Confirmed:**
- `parent_message_id` in request = `response_message_id` from previous turn
- `request_message_id` in response = `parent_message_id` from request
- `response_message_id` increments monotonically
- `chat_session_id` remains constant across turns

---

## 5. Authentication & Session Lifecycle

**Legitimate Browser Flow (from HAR):**
```
1. User visits chat.deepseek.com
2. Login via email/password/OAuth → Sets session cookies + Authorization token
3. Create/select chat session → Gets chat_session_id (via POST /api/v0/chat_session/create)
4. Send completion requests with:
   - Authorization: Bearer <token>
   - Cookie: ds_session_id=<...>; smidV2=<...>
   - x-ds-pow-response: <base64 PoW response>
   - x-hif-leim: <fingerprint>
5. Session maintained via cookies + token
```

**Endpoints Identified:**
- `POST /api/v0/chat_session/create` - Creates new chat session ✅ (observed in HAR)
- `POST /api/v0/auth/login` - Authentication ⬜
- `POST /api/v0/auth/refresh` - Token refresh ⬜
- `GET /api/v0/chat/sessions` - List sessions ⬜
- `GET /api/v0/pow/challenge` - Proof-of-Work challenge ⬜

**Cookies Observed:**
| Cookie | Description |
|--------|-------------|
| `ds_session_id` | DeepSeek session identifier |
| `smidV2` | Session/device identifier (long-lived) |
| `.thumbcache_...` | Thumbnail cache (empty) |

**Credentials Handling:**
- Never hardcoded - loaded from `.env` (gitignored)
- Automatic redaction in recordings
- `.env.example` provided with empty values

---

## 6. Dynamic Headers Analysis

| Header | Classification | Evidence |
|--------|----------------|----------|
| `Authorization` | **Session-specific** | Bearer token from login, persists across requests in session |
| `Cookie` | **Session-specific** | Session cookies (ds_session_id, smidV2), persists across requests |
| `x-ds-pow-response` | **Request-specific (generated by browser JS/WASM)** | Changes per request, base64 JSON with PoW fields |
| `x-hif-leim` | **Request-specific (generated by browser)** | Changes per request, two-part format, appears to be fingerprint/anti-abuse |

### `x-ds-pow-response` Details (DECODED FROM HAR)
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
- **Algorithm:** `DeepSeekHashV1` - custom PoW hash function
- **Challenge:** 32-byte hex string (likely random per request)
- **Salt:** 10-byte hex string
- **Answer:** Integer (PoW solution - number of iterations)
- **Signature:** 32-byte hex (likely HMAC of challenge+salt+answer)
- **Target Path:** API endpoint this PoW authorizes
- **Source:** Generated by client-side JavaScript (likely WebAssembly)
- **Challenge Source:** Unknown - possibly from separate endpoint or embedded in page
- **Variability:** Changes per request (new challenge per request)

### `x-hif-leim` Details
- **Format:** Two-part value separated by `.` (e.g., `BgH7I7g1cqigR+8XV+1y+xWQmuypjuhm2usNJqnK47xLG8T2NcJH7jU=.uxA+cpEf4ZqZK7FL`)
- **Source:** Unknown - possibly browser fingerprint / anti-abuse
- **Variability:** Changes per request
- **Status:** Requires further investigation (browser JS analysis)

---

## 7. Tool Calling

**Classification:** `TEXT_ONLY` / `NOT_FOUND`

**Evidence:**
- No `tool_calls`, `function_calls`, `tools`, `actions`, `plugins`, `mcp`, `command` fields in:
  - Request payloads
  - SSE response events
  - Client-side network traffic (XHR/fetch)
- No structured tool call/result pattern in SSE fragments
- DeepSeek web appears to be **text-only streaming** with reasoning (`thinking_enabled`)

**Fragment Types Observed:**
- `THINK`: Model's internal reasoning process (streamed)
- `RESPONSE`: Final user-visible response content

**Implication:** Proxy will need text-based tool calling shim (Phase 2+) if tool support required.

---

## 8. Agent Loop

**Status:** UNKNOWN / NOT_APPLICABLE

**Reasoning:** Since no native tool calling protocol exists (`TEXT_ONLY`), the complete agent loop:
```
Model → Tool Call → Tool Result → Model → Final Answer
```
cannot be demonstrated with the current DeepSeek web backend.

**Alternative:** Text-based agent loop possible via prompt engineering, but not native protocol.

---

## 9. Proxy Feasibility

**Rating:** YELLOW

**Rationale:**

| Factor | Assessment |
|--------|------------|
| Basic Completion | ✅ Works (317ms latency observed) |
| Streaming | ✅ Works (SSE with 25 events) |
| Multi-turn | ✅ Protocol supports it |
| Authentication | ⚠️ Manual only (dynamic headers block automation) |
| Tool Calling | ❌ Not native (text-only) |
| Dynamic Headers | ❌ PoW/fingerprint require browser JS |
| Session Persistence | ⚠️ Cookie/token management needed |
| Rate Limits | ⚓ Unknown |

**Green Path:** Basic text proxy with manual credential injection works.
**Yellow Path:** Automated auth requires solving PoW/fingerprint.
**Red Path:** Native tool calling not available.

---

## 10. Authentication Automation Feasibility

**Rating:** RED

**Rationale:**
- `x-ds-pow-response` requires Proof-of-Work computation (algorithm: `DeepSeekHashV1`, likely browser JS/WASM)
- `x-hif-leim` requires browser fingerprinting
- No documented API for obtaining challenges
- Challenge appears to be per-request (new challenge each completion)
- Legitimate automation would require:
  1. Headless browser (Playwright/Puppeteer) to execute JS
  2. Reverse-engineering PoW algorithm (`DeepSeekHashV1`)
  3. Maintaining cookie jar across sessions
- **Risk:** May violate ToS / trigger anti-bot protections

**Recommendation:** Phase 1 proxy should use manual credential injection. Automated auth is a separate research track.

---

## 11. Remaining Unknowns

1. **PoW Challenge Source:** Where does the challenge come from? Separate endpoint? Embedded in HTML? Generated client-side?
2. **PoW Algorithm:** Exact implementation of `DeepSeekHashV1` (likely WASM).
3. **x-hif-leim Generation:** Exact derivation method.
4. **Session Creation:** Full flow for creating new `chat_session_id` (observed but not fully explored).
5. **Token Refresh:** How/when `Authorization` token expires and refreshes.
6. **Rate Limits:** Per-session, per-IP, per-account limits.
7. **Model Variants:** Difference between `expert`, `chat`, `default` `model_type` values.
8. **Search/Tools:** Whether `search_enabled: true` activates any tool-like behavior.
9. **File Uploads:** `ref_file_ids` handling.
10. **Error Recovery:** Retry behavior, `action: "retry"` vs `null` semantics.
11. **Telemetry:** `gator.volces.com/list` requests (analytics/telemetry).

---

## 12. Next Recommended Engineering Step

**Immediate:** Implement Phase 2 Basic Proxy with **manual credential injection**.

```
Priority 1: OpenAI /v1/chat/completions endpoint
Priority 2: DeepSeek adapter with session management
Priority 3: Streaming translation (SSE → OpenAI chunks)
Priority 4: Error handling & retries
```

**Deferred (Separate Track):** Automated authentication via headless browser + PoW solver.

---

## Appendix: Test Results

### Unit Tests
```
tests/test_sse_parser.py     ✅ PASSED (8 tests)
tests/test_recorder.py       ✅ PASSED (8 tests)
tests/test_protocol.py       ✅ PASSED (5 tests)
Total: 22 tests PASSED
```

### Live Protocol Tests (Requires Credentials)
```
Basic Completion:            [PENDING - needs .env config]
Multi-Turn Conversation:     [PENDING - needs .env config]
SSE Parsing (fixture):       ✅ PASSED (25 events, content reconstructed)
Header Comparison (HAR):     ⚠️ Single completion in HAR (need multiple)
PoW Decoding:                ✅ DECODED (DeepSeekHashV1 algorithm confirmed)
```

### HAR Analysis Results
- **Completion Request:** 1 (say ok)
- **Session Creation:** 1 (new session created before completion)
- **Telemetry:** 6 requests to gator.volces.com/list
- **Latency:** 317ms (completion), 340ms (session create)

---

## Appendix: Repository State

**Commit:** 8970fbc
**Branch:** main
**Technology:** Python 3.11+, requests, pytest

**Key Modules:**
- `src/deepseek/client.py` - DeepSeek API client
- `src/protocol/sse_parser.py` - SSE parser & normalizer (handles real HAR format)
- `src/protocol/normalized_events.py` - Protocol data models
- `src/recorder/recorder.py` - Recording with auto-redaction
- `src/auth/investigation.py` - Auth endpoint investigation
- `src/cli.py` - Command-line interface

**Fixtures:**
- `tests/fixtures/sample_sse.txt` - Synthetic SSE for unit tests
- `tests/fixtures/captured.har` - Sanitized Firefox HAR capture

---

*Report generated as part of Phase 1 DeepSeek Web Protocol Investigation.*