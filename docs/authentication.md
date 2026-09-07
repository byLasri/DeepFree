# Authentication Lifecycle

## Observed Flow (from HAR + Live Testing)

```
1. User visits https://chat.deepseek.com
2. Login via Google OAuth or email/password
   → Sets cookies: ds_session_id, smidV2, .thumbcache_*
   → Sets Authorization Bearer token (returned in response headers or localStorage)
3. User creates/opens chat
   → POST /api/v0/chat_session/create → returns chat_session_id + TTL (259200s)
4. Completion requests with:
   - Authorization: Bearer <token>
   - Cookie: ds_session_id=<...>; smidV2=<...>
   - x-ds-pow-response: <fresh per-request>
   - x-hif-leim: <fresh per-request>
```

## Endpoints Discovered

| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/api/v0/chat_session/create` | POST | ✅ Working | Creates chat session, returns UUID + TTL |
| `/api/v0/chat/completion` | POST | ✅ Working | Main endpoint, requires dynamic headers |
| `/api/v0/chat/create_pow_challenge` | POST | ✅ Working | Returns fresh PoW challenge (5 min TTL) |
| `/api/v0/auth/login` | POST | ❌ Not observed | Likely used during initial login |
| `/api/v0/auth/refresh` | POST | ❌ Not observed | Token refresh mechanism unknown |
| `/api/v0/chat/sessions` | GET | ❌ Not tested | May list user's sessions |
| `GET https://hif-leim.deepseek.com/query` | GET | ✅ Working | Returns x-hif-leim token (10 min TTL) |
| `GET https://hif-dliq.deepseek.com/query` | GET | ⚠️ Unknown | Empty response, possibly config |
| `GET https://fe-static.deepseek.com/chat/static/sha3_wasm_bg.7b9ca65ddd.wasm` | GET | ✅ Working | DeepSeekHashV1 WASM module |

## Cookie Analysis

| Cookie | Scope | Lifetime | Purpose |
|--------|-------|----------|---------|
| `ds_session_id` | Account | Session | DeepSeek session identifier |
| `smidV2` | Device | Long-lived (months) | Device/session fingerprint |
| `.thumbcache_*` | Ephemeral | Session | Thumbnail cache (empty) |

## Token Lifetime

**UNKNOWN** — Not observed in HAR. The `Authorization` Bearer token appears to persist across the captured session but:
- No refresh endpoint confirmed
- No expiry information in responses
- May be tied to `ds_session_id` cookie lifetime

## Google OAuth

**Critical for automation** — The web UI supports Google login. A legitimate browser automation flow would be:

```
Playwright → chat.deepseek.com → "Sign in with Google"
    → Google OAuth consent → redirect back to DeepSeek
    → DeepSeek sets cookies + Authorization token
    → Browser now has authenticated session
    → Extract cookies + token for Python client
    → Browser generates PoW + x-hif-leim per request
```

This is the **only viable path** for automated authentication since PoW requires browser WASM execution.

## Session Persistence

- `chat_session_id` persists for 3 days (TTL: 259200s)
- Multiple chat sessions can exist per account
- `parent_message_id` chains messages within a session
- Session survives browser reload (cookies + token)

## Security Considerations

- Never commit cookies, tokens, or PoW values
- Rotate credentials after experimentation
- Browser automation should use isolated profile
- Respect rate limits and ToS