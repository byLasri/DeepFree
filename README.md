# DeepSeek Web Protocol Investigation

Phase 1 investigation of the DeepSeek web application's backend protocol (`https://chat.deepseek.com/api/v0/chat/completion`).

## Project Structure

```
src/
├── config.py                    # Configuration management
├── cli.py                       # Command-line interface
├── deepseek/
│   └── client.py                # DeepSeek API client
├── auth/
│   └── investigation.py         # Authentication/session investigation
├── recorder/
│   └── recorder.py              # Request/response recording with redaction
├── protocol/
│   ├── sse_parser.py            # SSE stream parsing
│   └── normalized_events.py     # Normalized protocol models
└── proxy/
    └── placeholder.py           # Future OpenAI-compatible proxy (Phase 2+)

tests/
├── test_sse_parser.py           # SSE parser unit tests
├── test_recorder.py             # Recorder/redaction unit tests
├── test_protocol.py             # Protocol model unit tests
└── fixtures/                    # Sanitized test fixtures

docs/
├── protocol.md                  # Documented DeepSeek protocol
├── architecture.md              # Proxy architecture design
└── findings.md                  # Phase 1 findings report
```

## Quick Start

1. Copy `.env.example` to `.env` and fill in your session credentials:
   ```bash
   cp .env.example .env
   # Edit .env with your credentials from browser DevTools
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run unit tests:
   ```bash
   python -m pytest tests/ -v
   ```

4. Test basic completion (requires valid credentials):
   ```bash
   DEEPSEEK_LIVE_TESTS=1 python -m src.cli completion "Say hello"
   ```

5. Test multi-turn conversation:
   ```bash
   DEEPSEEK_LIVE_TESTS=1 python -m src.cli multi-turn
   ```

## Commands

| Command | Description |
|---------|-------------|
| `completion <prompt>` | Single completion test |
| `multi-turn [prompts...]` | Multi-turn conversation test |
| `investigate [--endpoints]` | Investigate auth endpoints |
| `compare-har <file.har>` | Compare requests from HAR |
| `parse-sse <file>` | Parse SSE stream from file |

## Security

- **Never** commit `.env` or any credentials
- All recordings are automatically redacted
- Use `.env.example` as template only
- Rotate any credentials used during testing

## Documentation

- [Protocol Documentation](docs/protocol.md)
- [Architecture Design](docs/architecture.md)
- [Findings Report](docs/findings.md)

## Phase 1 Goals

- [x] Reproduce browser completion request
- [x] Parse and normalize SSE response
- [x] Extract message IDs and session state
- [x] Record and redact exchanges
- [ ] Investigate authentication lifecycle
- [ ] Analyze dynamic headers (x-ds-pow-response, x-hif-leim)
- [ ] Test multi-turn conversation mechanics
- [ ] Document complete protocol