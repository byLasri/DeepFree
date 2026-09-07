import requests
import json
from typing import Optional
from dataclasses import dataclass
from ..session import AuthState
from ..recorder.recorder import Recorder


@dataclass
class EndpointInfo:
    method: str
    url: str
    purpose: str
    required_inputs: list[str]
    important_headers: list[str]
    response_type: str
    session_state_changes: bool
    discovered: bool = False


KNOWN_ENDPOINTS = {
    "completion": EndpointInfo(
        method="POST",
        url="/api/v0/chat/completion",
        purpose="Main chat completion endpoint",
        required_inputs=["chat_session_id", "prompt", "parent_message_id"],
        important_headers=["authorization", "Cookie", "x-ds-pow-response", "x-hif-leim"],
        response_type="text/event-stream (SSE)",
        session_state_changes=True,
    ),
    "chat_sessions": EndpointInfo(
        method="GET",
        url="/api/v0/chat/sessions",
        purpose="List chat sessions",
        required_inputs=[],
        important_headers=["authorization", "Cookie"],
        response_type="application/json",
        session_state_changes=False,
    ),
    "create_session": EndpointInfo(
        method="POST",
        url="/api/v0/chat_session/create",
        purpose="Create new chat session",
        required_inputs=[],
        important_headers=["authorization", "Cookie"],
        response_type="application/json",
        session_state_changes=True,
    ),
    "login": EndpointInfo(
        method="POST",
        url="/api/v0/auth/login",
        purpose="User login",
        required_inputs=["email", "password"],
        important_headers=["Content-Type"],
        response_type="application/json",
        session_state_changes=True,
    ),
    "refresh": EndpointInfo(
        method="POST",
        url="/api/v0/auth/refresh",
        purpose="Refresh session token",
        required_inputs=[],
        important_headers=["authorization", "Cookie"],
        response_type="application/json",
        session_state_changes=True,
    ),
    "pow_challenge": EndpointInfo(
        method="GET",
        url="/api/v0/pow/challenge",
        purpose="Get Proof-of-Work challenge",
        required_inputs=[],
        important_headers=[],
        response_type="application/json",
        session_state_changes=False,
    ),
}


class AuthInvestigator:
    def __init__(self, auth: AuthState, recorder: Optional[Recorder] = None):
        self.auth = auth
        self.recorder = recorder
        self.session = requests.Session()
        self._set_cookies_from_auth()

    def _set_cookies_from_auth(self):
        for k, v in self.auth.cookies.items():
            if v:
                self.session.cookies.set(k.strip(), v.strip(), domain="chat.deepseek.com")

    def _get_base_headers(self) -> dict:
        return {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": "https://chat.deepseek.com",
            "Referer": "https://chat.deepseek.com/",
            "User-Agent": self.auth.user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) Gecko/20100101 Firefox/155.0",
            "x-client-bundle-id": "com.deepseek.chat",
            "x-client-locale": "en_US",
            "x-client-platform": "web",
            "x-client-version": "2.4.0",
        }

    def investigate_endpoint(self, endpoint_key: str, **kwargs) -> dict:
        endpoint = KNOWN_ENDPOINTS.get(endpoint_key)
        if not endpoint:
            return {"error": f"Unknown endpoint: {endpoint_key}"}

        url = f"https://chat.deepseek.com{endpoint.url}"
        headers = self._get_base_headers()
        if self.auth.authorization:
            headers["Authorization"] = f"Bearer {self.auth.authorization}"

        try:
            if endpoint.method == "GET":
                resp = self.session.get(url, headers=headers, timeout=30, params=kwargs)
            else:
                resp = self.session.post(url, headers=headers, json=kwargs, timeout=30)

            result = {
                "endpoint": endpoint_key,
                "url": url,
                "method": endpoint.method,
                "status": resp.status_code,
                "headers": dict(resp.headers),
                "body": resp.text[:2000] if resp.text else "",
                "cookies_after": dict(self.session.cookies),
            }

            if self.recorder:
                self.recorder.record(
                    url=url,
                    method=endpoint.method,
                    request_headers=headers,
                    request_body=kwargs if kwargs else None,
                    response_status=resp.status_code,
                    response_headers=dict(resp.headers),
                    response_body=resp.text,
                    metadata={"investigation": endpoint_key},
                )

            return result
        except Exception as e:
            return {"endpoint": endpoint_key, "error": str(e)}

    def compare_requests(self, har_file: str) -> dict:
        with open(har_file, "r") as f:
            har = json.load(f)

        entries = har.get("log", {}).get("entries", [])
        completion_entries = [
            e for e in entries
            if "/api/v0/chat/completion" in e.get("request", {}).get("url", "")
        ]

        if len(completion_entries) < 2:
            return {"error": "Need at least 2 completion requests to compare"}

        comparison = {
            "total_completion_requests": len(completion_entries),
            "static_headers": {},
            "session_headers": {},
            "dynamic_headers": {},
            "body_differences": [],
        }

        headers_list = [e["request"]["headers"] for e in completion_entries]

        all_header_names = set()
        for h in headers_list:
            for header in h:
                all_header_names.add(header["name"].lower())

        for name in all_header_names:
            values = []
            for h in headers_list:
                for header in h:
                    if header["name"].lower() == name:
                        values.append(header["value"])
                        break

            unique_values = set(values)
            if len(unique_values) == 1:
                if name in ("x-client-platform", "x-client-bundle-id", "x-client-version", "x-client-locale"):
                    comparison["static_headers"][name] = values[0]
                else:
                    comparison["session_headers"][name] = values[0]
            else:
                comparison["dynamic_headers"][name] = values

        return comparison