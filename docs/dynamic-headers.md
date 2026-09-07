# Dynamic Headers Analysis (Updated with did.txt findings)

## Complete Dynamic Header Generation Flow

The browser performs this sequence before each completion request:

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. GET https://hif-leim.deepseek.com/query                      │
│    → Returns: {"value": "token1.token2"}                        │
│    → Header: x-hif-ttl: 600 (10 min TTL)                        │
│    → Used as: x-hif-leim header                                 │
├─────────────────────────────────────────────────────────────────┤
│ 2. POST https://chat.deepseek.com/api/v0/chat/create_pow_challenge│
│    Body: {"target_path": "/api/v0/chat/completion"}             │
│    → Returns: challenge object (see below)                      │
│    → TTL: expire_after: 300000ms (5 min)                        │
├─────────────────────────────────────────────────────────────────┤
│ 3. Browser WASM (sha3_wasm_bg.7b9ca65ddd.wasm) computes PoW    │
│    Input: challenge + salt + difficulty                         │
│    Output: x-ds-pow-response (Base64 JSON)                      │
├─────────────────────────────────────────────────────────────────┤
│ 4. POST /api/v0/chat/completion with:                           │
│    - Authorization: Bearer <token>                              │
│    - Cookie: ds_session_id, smidV2                              │
│    - x-ds-pow-response: <from step 3>                          │
│    - x-hif-leim: <from step 1>                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## PoW Challenge Endpoint

**Endpoint:** `POST https://chat.deepseek.com/api/v0/chat/create_pow_challenge`

**Request:**
```json
{
  "target_path": "/api/v0/chat/completion"
}
```

**Response (from did.txt):**
```json
{
  "code": 0,
  "msg": "",
  "data": {
    "biz_code": 0,
    "biz_msg": "",
    "biz_data": {
      "challenge": {
        "algorithm": "DeepSeekHashV1",
        "challenge": "780f82ae19064aaff9881fa8b4251816b702b4ecc80bc2af73ec965199a969ee",
        "salt": "d171f1aec3da3ac48f57",
        "signature": "3b5d8f80f3592e5a6b4b682eb13186798afa7790524c1133c17e4b18aae5378b",
        "difficulty": 144000,
        "expire_at": 1788753000769,
        "expire_after": 300000,
        "target_path": "/api/v0/chat/completion"
      }
    }
  }
}
```

| Field | Description |
|-------|-------------|
| `algorithm` | `"DeepSeekHashV1"` - Custom SHA3-based PoW |
| `challenge` | 32-byte hex challenge string |
| `salt` | 10-byte hex salt |
| `signature` | 32-byte hex - HMAC of challenge+salt |
| `difficulty` | 144000 - Target difficulty (iterations) |
| `expire_after` | 300000ms (5 minutes) - Challenge TTL |
| `target_path` | API endpoint this challenge authorizes |

**Key Insight:** Challenge is **per-request**, expires in **5 minutes**. Must fetch fresh challenge for each completion.

---

## hif-leim Endpoint

**Endpoint:** `GET https://hif-leim.deepseek.com/query`

**Response (from did.txt):**
```json
{
  "code": 0,
  "msg": "",
  "data": {
    "biz_code": 0,
    "biz_msg": "",
    "biz_data": {
      "value": "s20JYwHYC1atRunfDKIj5HAxiNtg9a9orEJmixRMIXlA3s4cNnGjWEQ=.3JK3cGbp6egbd713"
    }
  }
}
```

**Response Header:** `x-hif-ttl: 600` (10 minutes = 600 seconds)

**Token Format:** `part1.part2` (two base64url parts separated by `.`)

**Usage:** This exact `value` string becomes the `x-hif-leim` header.

**TTL:** 10 minutes (600 seconds) - longer than PoW challenge.

---

## hif-dliq Endpoint

**Endpoint:** `GET https://hif-dliq.deepseek.com/query`

**Response:** Empty (status 0, no content, base64 encoded empty)

**Purpose:** Unknown - possibly configuration/fingerprinting setup. Called with CORS preflight (OPTIONS + GET).

---

## WASM Module

**URL:** `https://fe-static.deepseek.com/chat/static/sha3_wasm_bg.7b9ca65ddd.wasm`

**Purpose:** Implements `DeepSeekHashV1` PoW algorithm in WebAssembly.

**Likely exports:**
- Hash function (SHA3-256 or custom)
- PoW solver (finds nonce where hash < target)
- Signature verification

---

## Client Settings / Device ID

**Endpoint:** `GET /api/v0/client/settings?did=af639245-51a0-4091-b31a-ea36fe57bc25&scope=...`

**Scopes:** `main`, `model`, `provider`, `web_upgrade`

**Parameter:** `did` = Device ID (UUID) - likely from `smidV2` cookie or localStorage

---

## Complete Automation Flow (for BrowserDynamicHeaderProvider)

```python
async def generate_dynamic_headers(session, payload):
    # 1. Get hif-leim token (cache for 10 min)
    if not session.hif_token or session.hif_expired:
        resp = await browser.get("https://hif-leim.deepseek.com/query")
        session.hif_token = resp.json()["data"]["biz_data"]["value"]
        session.hif_expires = now() + 600
    
    # 2. Get PoW challenge (cache for 5 min)
    if not session.pow_challenge or session.pow_expired:
        resp = await browser.post(
            "https://chat.deepseek.com/api/v0/chat/create_pow_challenge",
            json={"target_path": "/api/v0/chat/completion"}
        )
        session.pow_challenge = resp.json()["data"]["biz_data"]["challenge"]
        session.pow_expires = now() + 300
    
    # 3. Compute PoW using WASM (in browser context)
    pow_response = await browser.eval_wasm(
        "sha3_wasm_bg",
        "solve_pow",
        session.pow_challenge
    )
    
    # 4. Build headers
    return {
        "x-ds-pow-response": pow_response,
        "x-hif-leim": session.hif_token,
    }
```

---

## Key Timing Constraints

| Component | TTL | Refresh Strategy |
|-----------|-----|------------------|
| `x-hif-leim` | 600s (10 min) | Fetch before expiry |
| PoW challenge | 300s (5 min) | Fetch per completion |
| PoW response | Single-use | Generate fresh each request |
| Challenge signature | Bound to challenge | Recompute per challenge |

---

## Security Notes

- Challenge `signature` binds challenge+salt - prevents replay
- Difficulty `144000` = ~144k iterations target
- WASM execution in browser = legitimate automation path
- **No API to bypass WASM** - must execute in browser context
- `did` (device ID) likely ties to `smidV2` cookie