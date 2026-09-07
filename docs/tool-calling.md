# Tool Calling Investigation

## Executive Summary

**Classification: `TEXT_ONLY` / `NOT_FOUND`**

No native tool calling protocol exists in the DeepSeek web application backend. The system is **text-only streaming** with reasoning (`THINK` fragments) but no structured tool calls, function calls, or action protocols.

---

## Evidence Search

### Searched In
- Request payloads (HAR + live)
- SSE response events (25 events parsed)
- All network traffic in HAR (7 entries)
- Client-side JS bundles (DevTools search)

### Search Terms
```
tool, tool_call, tool_calls, function, function_call, function_calls
actions, action, plugin, plugins, mcp, command, commands
search, browse, file, code, agent, orchestration
```

### Results
| Pattern | Found In Requests | Found In SSE | Found In JS |
|---------|-------------------|--------------|-------------|
| `tool_call` | ❌ | ❌ | ❌ |
| `function_call` | ❌ | ❌ | ❌ |
| `actions` | ❌ | ❌ | ❌ |
| `plugin` | ❌ | ❌ | ❌ |
| `mcp` | ❌ | ❌ | ❌ |
| `command` | ❌ | ❌ | ❌ |
| `search` | ✅ (param) | ❌ | — |

---

## What EXISTS (Not Tool Calling)

### 1. Reasoning (THINK fragments)
```json
{
  "type": "THINK",
  "content": "We need to answer user says \"say ok\"...",
  "stage_id": 1
}
```
- Internal model reasoning
- Streamed incrementally via `APPEND`
- Not actionable — purely internal

### 2. Search Flag
```json
"search_enabled": true
```
- Boolean parameter
- No structured search results in SSE
- No citations/references observed

### 3. File References
```json
"ref_file_ids": []
```
- Placeholder for file uploads
- Upload protocol unobserved

### 4. Action Parameter
```json
"action": "retry" | "default"
```
- Only controls retry behavior
- Not a tool/action protocol

---

## Comparison: Native vs Text-Based

| Aspect | Native (OpenAI) | DeepSeek Web |
|--------|-----------------|--------------|
| Tool definition | `tools` array in request | ❌ None |
| Tool call | `tool_calls` in response | ❌ None |
| Tool result | `tool` role message | ❌ None |
| Structured args | JSON Schema | ❌ None |
| Streaming tool calls | ✅ Supported | ❌ None |

---

## External Agent Loop (Viable Alternative)

Since native tools don't exist, an external agent loop can be implemented via **prompt engineering**:

```
┌─────────────────────────────────────────────────────────┐
│                    External Agent                        │
├─────────────────────────────────────────────────────────┤
│  1. Inject tool definitions in system prompt            │
│  2. Instruct model: "Call tools via JSON format:"       │
│     ```json                                             │
│     { "tool_call": { "name": "fn", "arguments": {} } }  │
│     ```                                                 │
│  3. Parse model's text response for tool_call           │
│  4. Execute tool externally                             │
│  5. Inject result as next prompt: "Tool result: {...}"  │
│  6. Continue until final answer                         │
└─────────────────────────────────────────────────────────┘
```

### Tested Architecture (tests/live/test_agent_loop.py)

```python
tools = [{"name": "get_test_value", "description": "...", "parameters": {}}]

system_prompt = f"""You have access to tools: {json.dumps(tools)}

When you need to use a tool, respond with:
```json
{{"tool_call": {{"name": "tool_name", "arguments": {{}}}}}
```"""

# Turn 1: Model emits tool_call JSON in text
# Turn 2: Inject result, model produces final answer
```

**Status:** Architecture works conceptually. Blocked by PoW for live testing.

---

## Implications for OpenAI-Compatible Proxy

### Cannot Support
- `tools` parameter in `/v1/chat/completions`
- `tool_choice` parameter
- Native `tool_calls` in streaming response
- Function calling semantics

### Must Implement (Shim)
1. **Tool definition injection** — Convert OpenAI `tools` → system prompt
2. **Tool call parsing** — Extract JSON from model's text response
3. **Executor** — Run tool, capture result
4. **Result injection** — Feed back as next conversation turn
5. **Streaming coordination** — Handle multi-turn within single OpenAI request

### Latency Cost
| Approach | Round Trips | Latency |
|----------|-------------|---------|
| Native | 1 | ~300ms |
| Text shim | 2-4 | ~600-1200ms |

---

## Conclusion

DeepSeek web **does not support native tool calling**. Any OpenAI-compatible proxy must implement a **text-based tool calling shim** with significant latency overhead and parsing complexity. This is a fundamental limitation of the web protocol.

**Recommendation:** If native tool calling is required, use the official DeepSeek API (if available) rather than the web protocol.