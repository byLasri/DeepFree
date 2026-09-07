from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime
import json

from .protocol.normalized_events import ProtocolRequest, ProtocolResponse


@dataclass
class AuthState:
    """Long-lived authentication state (survives across chat sessions)."""
    authorization: str = ""           # Bearer token
    ds_session_id: str = ""           # DeepSeek session cookie
    smidV2: str = ""                  # Device/session cookie
    cookies: Dict[str, str] = field(default_factory=dict)
    user_agent: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    last_used: datetime = field(default_factory=datetime.now)

    def get_cookie_header(self) -> str:
        parts = []
        for k, v in self.cookies.items():
            if v:
                parts.append(f"{k}={v}")
        return "; ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authorization": self.authorization,
            "ds_session_id": self.ds_session_id,
            "smidV2": self.smidV2,
            "cookies": self.cookies,
            "user_agent": self.user_agent,
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuthState":
        state = cls(
            authorization=data.get("authorization", ""),
            ds_session_id=data.get("ds_session_id", ""),
            smidV2=data.get("smidV2", ""),
            cookies=data.get("cookies", {}),
            user_agent=data.get("user_agent", ""),
        )
        if "created_at" in data:
            state.created_at = datetime.fromisoformat(data["created_at"])
        if "last_used" in data:
            state.last_used = datetime.fromisoformat(data["last_used"])
        return state

    def is_valid(self) -> bool:
        return bool(self.authorization and self.ds_session_id)


@dataclass
class ChatSession:
    """Chat-scoped session state."""
    chat_session_id: str = ""
    current_parent_message_id: Optional[int] = None
    message_counter: int = 0
    model_type: str = "expert"
    title: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    ttl_seconds: int = 259200  # 3 days from HAR

    def add_turn(self, request: ProtocolRequest, response: ProtocolResponse):
        self.message_counter += 1
        if response.response_message_id:
            self.current_parent_message_id = response.response_message_id
        self.updated_at = datetime.now()

    def get_next_request(self, prompt: str, model_type: str = "expert") -> ProtocolRequest:
        return ProtocolRequest(
            chat_session_id=self.chat_session_id,
            parent_message_id=self.current_parent_message_id,
            model_type=model_type,
            prompt=prompt,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chat_session_id": self.chat_session_id,
            "current_parent_message_id": self.current_parent_message_id,
            "message_counter": self.message_counter,
            "model_type": self.model_type,
            "title": self.title,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "ttl_seconds": self.ttl_seconds,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatSession":
        session = cls(
            chat_session_id=data.get("chat_session_id", ""),
            current_parent_message_id=data.get("current_parent_message_id"),
            message_counter=data.get("message_counter", 0),
            model_type=data.get("model_type", "expert"),
            title=data.get("title"),
            ttl_seconds=data.get("ttl_seconds", 259200),
        )
        if "created_at" in data:
            session.created_at = datetime.fromisoformat(data["created_at"])
        if "updated_at" in data:
            session.updated_at = datetime.fromisoformat(data["updated_at"])
        return session


@dataclass
class DynamicHeaders:
    """Per-request dynamic headers that must be generated fresh."""
    x_ds_pow_response: str = ""
    x_hif_leim: str = ""
    generated_at: datetime = field(default_factory=datetime.now)
    request_payload_hash: str = ""  # For debugging/tracing

    def to_dict(self) -> Dict[str, str]:
        return {
            "x-ds-pow-response": self.x_ds_pow_response,
            "x-hif-leim": self.x_hif_leim,
        }

    def is_empty(self) -> bool:
        return not self.x_ds_pow_response and not self.x_hif_leim


@dataclass
class DeepSeekSession:
    """Complete session combining auth, chat, and dynamic header generation."""
    auth: AuthState = field(default_factory=AuthState)
    chat: ChatSession = field(default_factory=ChatSession)
    dynamic_header_provider: Optional["DynamicHeaderProvider"] = None

    def get_request_headers(self, dynamic: DynamicHeaders) -> Dict[str, str]:
        headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Host": "chat.deepseek.com",
            "Origin": "https://chat.deepseek.com",
            "Referer": f"https://chat.deepseek.com/a/chat/s/{self.chat.chat_session_id}",
            "User-Agent": self.auth.user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) Gecko/20100101 Firefox/155.0",
            "x-client-bundle-id": "com.deepseek.chat",
            "x-client-locale": "en_US",
            "x-client-platform": "web",
            "x-client-version": "2.4.0",
            "x-client-timezone-offset": "-25200",
        }
        if self.auth.authorization:
            headers["Authorization"] = f"Bearer {self.auth.authorization}"
        cookie_header = self.auth.get_cookie_header()
        if cookie_header:
            headers["Cookie"] = cookie_header
        if dynamic.x_ds_pow_response:
            headers["x-ds-pow-response"] = dynamic.x_ds_pow_response
        if dynamic.x_hif_leim:
            headers["x-hif-leim"] = dynamic.x_hif_leim
        return headers

    def get_redacted_headers(self, dynamic: DynamicHeaders) -> Dict[str, str]:
        headers = self.get_request_headers(dynamic)
        redacted = {}
        for k, v in headers.items():
            if k.lower() in ("authorization", "cookie", "x-ds-pow-response", "x-hif-leim"):
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = v
        return redacted


class DynamicHeaderProvider:
    """Abstract interface for generating dynamic headers."""

    def generate_headers(self, session: DeepSeekSession, payload: Dict[str, Any]) -> DynamicHeaders:
        raise NotImplementedError

    def is_available(self) -> bool:
        return False


class StaticDynamicHeaderProvider(DynamicHeaderProvider):
    """Provider that uses pre-captured static values (for testing/replay only)."""

    def __init__(self, pow_response: str = "", hif_leim: str = ""):
        self.pow_response = pow_response
        self.hif_leim = hif_leim

    def generate_headers(self, session: DeepSeekSession, payload: Dict[str, Any]) -> DynamicHeaders:
        return DynamicHeaders(
            x_ds_pow_response=self.pow_response,
            x_hif_leim=self.hif_leim,
        )

    def is_available(self) -> bool:
        return bool(self.pow_response or self.hif_leim)


class BrowserDynamicHeaderProvider(DynamicHeaderProvider):
    """Provider that uses a browser (Playwright) to generate headers."""

    def __init__(self, browser_context=None):
        self.browser_context = browser_context

    def generate_headers(self, session: DeepSeekSession, payload: Dict[str, Any]) -> DynamicHeaders:
        # TODO: Implement browser-based generation
        raise NotImplementedError("Browser provider not yet implemented")

    def is_available(self) -> bool:
        return self.browser_context is not None


def create_session_from_env() -> DeepSeekSession:
    """Create a session from environment variables (legacy .env support)."""
    import os
    from dotenv import load_dotenv
    load_dotenv()

    auth = AuthState(
        authorization=os.getenv("DEEPSEEK_AUTHORIZATION", "").replace("Bearer ", ""),
        ds_session_id=os.getenv("DEEPSEEK_SESSION_ID", ""),
        smidV2="",  # Extracted from cookie if present
        cookies={},
        user_agent=os.getenv("DEEPSEEK_USER_AGENT", ""),
    )

    # Parse cookie string if provided
    cookie_str = os.getenv("DEEPSEEK_COOKIE", "")
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            auth.cookies[k.strip()] = v.strip()
            if k.strip() == "ds_session_id":
                auth.ds_session_id = v.strip()
            elif k.strip() == "smidV2":
                auth.smidV2 = v.strip()

    chat = ChatSession(
        chat_session_id=os.getenv("DEEPSEEK_CHAT_SESSION_ID", ""),
        model_type="expert",
    )

    provider = StaticDynamicHeaderProvider(
        pow_response=os.getenv("DEEPSEEK_POW_RESPONSE", ""),
        hif_leim=os.getenv("DEEPSEEK_HIF_LEIM", ""),
    )

    return DeepSeekSession(auth=auth, chat=chat, dynamic_header_provider=provider)