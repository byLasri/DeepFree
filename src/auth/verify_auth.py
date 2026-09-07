"""
DeepSeek Authentication Verifier

Loads persisted authentication state and makes HTTP-only requests
to verify whether the extracted authentication works independently
of the browser.
"""
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

import httpx

from ..session import AuthState


AUTH_STATE_DIR = Path(__file__).parent.parent.parent / ".auth_state"
AUTH_STATE_FILE = Path(__file__).parent.parent.parent / ".auth_state" / "auth.json"


class VerificationResult:
    """Verification result categories."""
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    BLOCKED_BY_DYNAMIC_PROTECTION = "BLOCKED_BY_DYNAMIC_PROTECTION"
    INCONCLUSIVE = "INCONCLUSIVE"

    def __init__(
        self,
        status: str,
        http_status: int,
        response_body: str = "",
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.status = status
        self.http_status = http_status
        self.response_body = response_body
        self.error = error
        self.metadata = metadata or {}


@dataclass
class VerificationMetadata:
    """Metadata captured during verification."""
    http_status: int = 0
    response_body_preview: str = ""
    headers_present: Dict[str, str] = None
    response_json: Dict[str, Any] = None
    blocked_by_pow: bool = False
    blocked_by_hif: bool = False
    explicit_auth_failure: bool = False

    def __post_init__(self):
        if self.headers_present is None:
            self.headers_present = {}


class AuthVerifier:
    """
    HTTP-only authentication verifier.

    Loads persisted authentication state and makes HTTP requests
    to verify whether the extracted authentication works without
    a browser.
    """

    def __init__(
        self,
        auth_state_file: Optional[Path] = None,
        base_url: str = "https://chat.deepseek.com",
        timeout: int = 30,
    ):
        self.auth_state_file = auth_state_file or AUTH_STATE_FILE
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _load_auth_state(self) -> Dict[str, Any]:
        """Load authentication state from file."""
        if not self.auth_state_file.exists():
            raise FileNotFoundError(
                f"Authentication state file not found: {self.auth_state_file}"
            )

        with open(self.auth_state_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Validate required fields
        if "authorization" not in data:
            raise ValueError("Authentication state missing 'authorization' field")
        if "token" not in data["authorization"]:
            raise ValueError("Authorization missing 'token' field")

        return data

    def _build_headers(self, auth_data: Dict[str, Any]) -> Dict[str, str]:
        """Build HTTP headers from auth state."""
        token = auth_data["authorization"]["token"]
        cookies = auth_data.get("cookies", [])

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": "https://chat.deepseek.com",
            "Referer": "https://chat.deepseek.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) Gecko/20100101 Firefox/155.0",
            "x-client-bundle-id": "com.deepseek.chat",
            "x-client-locale": "en_US",
            "x-client-platform": "web",
            "x-client-version": "2.4.0",
            "x-client-timezone-offset": "-25200",
        }

        # Build Cookie header
        cookie_parts = []
        for cookie in auth_data.get("cookies", []):
            if cookie.get("value"):
                cookie_parts.append(f"{cookie['name']}={cookie['value']}")

        if cookie_parts:
            headers["Cookie"] = "; ".join(cookie_parts)

        return headers

    def _classify_response(self, response: httpx.Response) -> tuple:
        """Classify the HTTP response."""
        status = response.status_code
        text = response.text[:2000] if response.text else ""

        # Check for explicit authentication failure
        if status == 401:
            return (VerificationResult.FAILED, True, "Explicit authentication failure (401)")

        # Check for dynamic protection errors
        if status == 403:
            text_lower = text.lower()
            if any(keyword in text_lower for keyword in [
                "invalid_pow", "missing_pow", "pow", "40301",
                "missing header", "40300",
                "hif", "challenge"
            ]):
                return (VerificationResult.BLOCKED_BY_DYNAMIC_PROTECTION, False, "Blocked by dynamic request protection")

        # Success
        if status == 200:
            return (VerificationResult.VERIFIED, False, "Success")

        # Other 4xx/5xx
        if 400 <= status < 500:
            return (VerificationResult.INCONCLUSIVE, False, f"Client error ({status})")
        if 500 <= status < 600:
            return (VerificationResult.INCONCLUSIVE, False, f"Server error ({status})")

        # Other status
        return (VerificationResult.INCONCLUSIVE, False, f"Unexpected status ({status})")

    async def verify(self) -> tuple:
        """
        Run the verification.

        Returns:
            tuple: (VerificationResult, metadata_dict)
        """
        # Load auth state
        auth_data = self._load_auth_state()
        headers = self._build_headers(auth_data)

        # Prepare metadata
        metadata = {
            "bearer_token": "PRESENT",
            "cookies_present": len(auth_data.get("cookies", [])) > 0,
            "cookie_names": [c["name"] for c in auth_data.get("cookies", [])],
            "browser_required": False,
        }

        # Make the request
        url = f"{self.base_url}/api/v0/chat_session/create"
        body = {}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    url,
                    headers=headers,
                    json=body,
                )

                status, explicit_auth_failure, reason = self._classify_response(response)

                metadata = {
                    "http_status": response.status_code,
                    "response_preview": response.text[:500] if response.text else "",
                    "headers_present": {
                        "authorization": "PRESENT",
                        "cookie": "PRESENT" if "Cookie" in headers else "ABSENT",
                        "user_agent": "PRESENT" if "User-Agent" in headers else "ABSENT",
                        "origin": "PRESENT" if "Origin" in headers else "ABSENT",
                        "referer": "PRESENT" if "Referer" in headers else "ABSENT",
                        "x_client_platform": "PRESENT" if "x-client-platform" in headers else "ABSENT",
                        "x_client_version": "PRESENT" if "x-client-version" in headers else "ABSENT",
                    },
                    "blocked_by_pow": response.status_code == 403 and "pow" in response.text.lower(),
                    "blocked_by_hif": response.status_code == 403 and "hif" in response.text.lower(),
                    "explicit_auth_failure": response.status_code == 401,
                    "reason": reason,
                }

                return VerificationResult(
                    status=VerificationResult.VERIFIED if response.status_code == 200 else
                           VerificationResult.FAILED if response.status_code == 401 else
                           VerificationResult.BLOCKED_BY_DYNAMIC_PROTECTION if response.status_code == 403 and ("pow" in response.text.lower() or "hif" in response.text.lower()) else
                           VerificationResult.INCONCLUSIVE,
                    http_status=response.status_code,
                    response_body=response.text,
                    metadata=metadata,
                ), metadata

            except httpx.TimeoutException as e:
                return VerificationResult(
                    status=VerificationResult.INCONCLUSIVE,
                    http_status=0,
                    error=f"Timeout: {e}",
                ), metadata
            except httpx.RequestError as e:
                return VerificationResult(
                    status=VerificationResult.INCONCLUSIVE,
                    http_status=0,
                    error=f"Request error: {e}",
                ), metadata
            except Exception as e:
                return VerificationResult(
                    status=VerificationResult.INCONCLUSIVE,
                    http_status=0,
                    error=f"Unexpected error: {e}",
                ), metadata


async def run_verifier(
    auth_state_file: Optional[Path] = None,
    base_url: str = "https://chat.deepseek.com",
    timeout: int = 30,
) -> tuple:
    """Entry point for running the verifier."""
    if auth_state_file is None:
        auth_state_file = AUTH_STATE_FILE
    verifier = AuthVerifier(
        auth_state_file=auth_state_file,
        base_url=base_url,
        timeout=timeout,
    )
    return await verifier.verify()


def _print_result(result: VerificationResult, metadata: Dict[str, Any]):
    """Print verification result in a formatted way."""
    print("=" * 40)

    if result.status == "VERIFIED":
        print("AUTHENTICATION VERIFIED")
        print("=" * 40)
        print()
        print(f"Bearer token: {metadata.get('bearer_token', 'UNKNOWN')}")
        print(f"DeepSeek cookies: {'PRESENT' if metadata.get('cookies_present') else 'ABSENT'}")
        print(f"Browser required: NO")
        print(f"HTTP client: httpx")
        print(f"HTTP status: {result.http_status}")
        print()
        print("Persisted authentication works independently of the browser.")

    elif result.status == "BLOCKED_BY_DYNAMIC_PROTECTION":
        print("AUTHENTICATION NOT DISPROVEN")
        print("=" * 40)
        print()
        print(f"Bearer token: PRESENT")
        print(f"DeepSeek cookies: {'PRESENT' if metadata.get('cookies_present') else 'ABSENT'}")
        print(f"Browser required: NO")
        print(f"HTTP client: httpx")
        print(f"HTTP status: {result.http_status}")
        print()
        print("Server response indicates dynamic request protection.")
        print("Authentication cannot be independently verified yet.")
        if metadata.get("blocked_by_pow"):
            print("PoW requirement detected.")
        if metadata.get("blocked_by_hif"):
            print("hif-leim requirement detected.")
        print("PoW/dynamic-header work remains a separate phase.")

    elif result.status == "FAILED":
        print("AUTHENTICATION FAILED")
        print("=" * 40)
        print()
        print(f"HTTP status: {result.http_status}")
        print(f"Reason: {result.error or 'Explicit authentication failure (401)'}")

    else:  # INCONCLUSIVE
        print("AUTHENTICATION VERIFICATION INCONCLUSIVE")
        print("=" * 40)
        print()
        if result.error:
            print(f"Error: {result.error}")
        else:
            print(f"HTTP status: {result.http_status}")
            print(f"Reason: {result.metadata.get('reason', 'Unknown')}")
        print()
        print("The HTTP request did not provide enough evidence to determine")
        print("whether the persisted authentication is accepted.")

    print("=" * 40)


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="DeepSeek Authentication Verifier")
    parser.add_argument("--auth-file", type=Path, default=AUTH_STATE_FILE, help="Path to auth.json")
    parser.add_argument("--base-url", default="https://chat.deepseek.com", help="Base URL")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds")
    args = parser.parse_args()

    result, metadata = asyncio.run(run_verifier(
        auth_state_file=args.auth_file,
        base_url=args.base_url,
        timeout=args.timeout,
    ))

    _print_result(result, metadata)

    # Exit code based on result
    if result.status == "VERIFIED":
        sys.exit(0)
    elif result.status == "FAILED":
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()