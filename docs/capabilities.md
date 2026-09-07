# Model Capabilities & Parameters

## model_type Values

| Value | Accepted | Description |
|-------|----------|-------------|
| `expert` | ✅ Yes | Default/recommended mode |
| `default` | ✅ Yes | Alternative mode |
| `vision` | ✅ Yes | From error message (not tested) |
| `chat` | ❌ No (422) | Rejected |
| `reasoning` | ❌ No (422) | Rejected |

**Error message for invalid values:**
```
Failed to deserialize the JSON body into the target type: 
model_type: unknown variant `chat`, expected one of `DEFAULT`, `default`, `expert`, `vision`
```

**Note:** Case-insensitive for `DEFAULT`/`default`.

### Behavioral Differences (Hypothesis)

| model_type | Likely Behavior |
|------------|-----------------|
| `expert` | Full reasoning + thinking enabled by default |
| `default` | Standard chat, thinking optional |
| `vision` | Multimodal (image input via `ref_file_ids`) |

**Not tested live** — requires fresh PoW.

---

## thinking_enabled

| Value | Type | Default | Effect |
|-------|------|---------|--------|
| `true` | Boolean | `true` | Streams `THINK` fragments (reasoning) |
| `false` | Boolean | — | Suppresses thinking fragments |

**Observed in HAR:** `thinking_enabled: true` produces `THINK` type fragments in SSE.

---

## search_enabled

| Value | Type | Default | Effect |
|-------|------|---------|--------|
| `true` | Boolean | `false` | Enables web search |
| `false` | Boolean | — | Standard completion |

**Accepted:** Both values return 200 (with valid PoW).

**Behavior unknown** — No separate search tool protocol observed in SSE. Likely:
- Internal model capability
- Or web application orchestration (additional requests not captured)

**Tested:** Both accepted, no protocol difference in request/response structure.

---

## action Parameter

| Value | Accepted | Description |
|-------|----------|-------------|
| `default` | ✅ Yes | Normal message |
| `retry` | ✅ Yes | Retry last generation |
| `continue` | ❌ No (422) | Rejected |
| `regenerate` | ❌ No (422) | Rejected |
| `edit` | ❌ No (422) | Rejected |
| `stop` | ❌ No (422) | Rejected |

**HAR value:** `action: null` (maps to `default`)

---

## ref_file_ids

**Field exists in request:** `"ref_file_ids": []`

**Purpose:** Reference uploaded files in chat.

**Upload protocol:** NOT OBSERVED in HAR.

**Hypothesized flow:**
1. `POST /api/v0/file/upload` (or similar) → returns file_id
2. Include `file_id` in `ref_file_ids` array
3. Completion processes file content

**Not implemented or tested.**

---

## preempt

| Value | Type | Default | Effect |
|-------|------|---------|--------|
| `true` | Boolean | `false` | Preemptive generation? |
| `false` | Boolean | — | Standard |

**Not tested.** May control speculative decoding or early response.

---

## Fragment Types (SSE Response)

| Type | Description | thinking_enabled |
|------|-------------|------------------|
| `THINK` | Model's internal reasoning process | `true` only |
| `RESPONSE` | Final user-visible answer | Always |

**From HAR:** First fragment is `THINK` with content `"We"`, then `RESPONSE` with content `"ok"`.

---

## Token Usage

**Observed in SSE BATCH events:**
```json
{
  "p": "response",
  "o": "BATCH",
  "v": [
    {"p": "accumulated_token_usage", "v": 36},
    {"p": "quasi_status", "v": "FINISHED"}
  ]
}
```

**Fields:**
- `accumulated_token_usage`: Total tokens so far
- `quasi_status`: `"FINISHED"` when complete

---

## Conversation Modes

**From initial response object:**
```json
"conversation_mode": "DEFAULT"
```

**Other possible values:** Unknown. May relate to `model_type`.

---

## Status Values

| Status | Meaning |
|--------|---------|
| `WIP` | Work in progress (streaming) |
| `FINISHED` | Generation complete |
| `quasi_status: FINISHED` | Pre-final signal |

**Transitions:** `WIP` → `FINISHED` (via `response/status` SET operation)