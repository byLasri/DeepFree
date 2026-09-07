import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class DeepSeekConfig:
    authorization: str = ""
    session_id: str = ""
    chat_session_id: str = ""
    cookie: str = ""
    pow_response: str = ""
    hif_leim: str = ""
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    base_url: str = "https://chat.deepseek.com"
    live_tests: bool = False

    @classmethod
    def from_env(cls) -> "DeepSeekConfig":
        return cls(
            authorization=os.getenv("DEEPSEEK_AUTHORIZATION", ""),
            session_id=os.getenv("DEEPSEEK_SESSION_ID", ""),
            chat_session_id=os.getenv("DEEPSEEK_CHAT_SESSION_ID", ""),
            cookie=os.getenv("DEEPSEEK_COOKIE", ""),
            pow_response=os.getenv("DEEPSEEK_POW_RESPONSE", ""),
            hif_leim=os.getenv("DEEPSEEK_HIF_LEIM", ""),
            user_agent=os.getenv("DEEPSEEK_USER_AGENT", ""),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://chat.deepseek.com"),
            live_tests=os.getenv("DEEPSEEK_LIVE_TESTS", "0") == "1",
        )

    def is_configured(self) -> bool:
        return bool(self.authorization and self.chat_session_id)

    def get_headers(self, include_dynamic: bool = True) -> dict:
        headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Host": "chat.deepseek.com",
            "Origin": "https://chat.deepseek.com",
            "Referer": f"https://chat.deepseek.com/a/chat/s/{self.chat_session_id}" if self.chat_session_id else "https://chat.deepseek.com/",
            "User-Agent": self.user_agent,
            "x-client-bundle-id": "com.deepseek.chat",
            "x-client-locale": "en_US",
            "x-client-platform": "web",
            "x-client-timezone-offset": "-25200",
            "x-client-version": "2.4.0",
        }
        if self.authorization:
            headers["authorization"] = f"Bearer {self.authorization}"
        if self.cookie:
            headers["Cookie"] = self.cookie
        if include_dynamic and self.pow_response:
            headers["x-ds-pow-response"] = self.pow_response
        if include_dynamic and self.hif_leim:
            headers["x-hif-leim"] = self.hif_leim
        return headers

    def get_redacted_headers(self, include_dynamic: bool = True) -> dict:
        headers = self.get_headers(include_dynamic)
        redacted = {}
        for k, v in headers.items():
            if k.lower() in ("authorization", "cookie", "x-ds-pow-response", "x-hif-leim"):
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = v
        return redacted