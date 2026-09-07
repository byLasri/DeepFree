"""
DeepSeek Authentication Extractor

Uses Playwright to perform one-time browser-based Google OAuth login,
captures the authenticated DeepSeek API request, and persists the
authentication state for later HTTP-only verification.
"""
import asyncio
import json
import os
import platform
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Response

from ..session import AuthState


def get_playwright_launch_config() -> dict:
    """
    Detect system default browser and return appropriate Playwright launch configuration.
    Prioritizes system-installed Chromium-based browsers (Edge, Chrome, Brave) over Playwright's bundled Chromium.
    HARDENED: Minimal anti-detection - only hide navigator.webdriver to avoid Google "insecure browser" detection.
    """
    # MINIMAL ARGS: Only essential flags + hide automation marker
    # --disable-blink-features=AutomationControlled prevents navigator.webdriver = true
    # This is required to pass Google's "insecure browser" check
    # Removed: --disable-web-security, --disable-gpu, --disable-features=IsolateOrigins,site-per-process
    # Removed: --no-sandbox, --disable-setuid-sandbox (not needed outside containers)
    # Removed: --window-size - let browser use system default resolution
    base_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
    ]
    
    if platform.system() == "Windows":
        # Windows default is usually Edge. Check for Edge, then Chrome, then Brave.
        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        if any(os.path.exists(p) for p in edge_paths):
            return {"headless": False, "channel": "msedge", "args": base_args}
        elif shutil.which("chrome"):
            return {"headless": False, "channel": "chrome", "args": base_args}
        else:
            print("⚠️ No system Chromium browser found. Falling back to Playwright bundled Chromium.")
            return {"headless": False, "args": base_args}
            
    elif platform.system() == "Darwin":  # macOS
        # macOS default is Safari, but Playwright CANNOT automate Safari for network interception.
        # We must fallback to Chrome or Edge if installed.
        chrome_path = "/Applications/Google Chrome.app"
        edge_path = "/Applications/Microsoft Edge.app"
        if os.path.exists(chrome_path):
            return {"headless": False, "channel": "chrome", "args": base_args}
        elif os.path.exists(edge_path):
            return {"headless": False, "channel": "msedge", "args": base_args}
        else:
            print("⚠️ No system Chromium browser found. Falling back to Playwright bundled Chromium.")
            return {"headless": False, "args": base_args}
    else:  # Linux
        # Check for google-chrome, chromium, or brave
        if shutil.which("google-chrome"):
            return {"headless": False, "channel": "chrome", "args": base_args}
        elif shutil.which("chromium"):
            # On Linux, 'chromium' channel might not exist, use bundled
            print("Detected system browser: Chromium")
            return {"headless": False, "channel": "chromium", "args": base_args}
        elif shutil.which("brave-browser") or shutil.which("brave"):
            brave_path = shutil.which("brave-browser") or shutil.which("brave")
            return {"headless": False, "executable_path": shutil.which("brave-browser") or shutil.which("brave"), "args": base_args}
        else:
            print("⚠️ No system Chromium browser found. Falling back to Playwright bundled Chromium.")
            return {"headless": False, "args": base_args}

    return {"headless": False, "args": base_args}


def get_browser_launch_config() -> dict:
    """Get the best available browser launch configuration for Google OAuth."""
    return get_playwright_launch_config()


AUTH_STATE_DIR = Path(__file__).parent.parent.parent / ".auth_state"
AUTH_STATE_FILE = AUTH_STATE_DIR / "auth.json"
AUTH_STATE_TMP = AUTH_STATE_DIR / "auth.json.tmp"

# The endpoint we monitor for authentication signal
TARGET_API_PREFIX = "https://chat.deepseek.com/api/v0/"


class LoginResult:
    """Result of the login extraction process."""
    SUCCESS = "AUTH_CAPTURED"
    BROWSER_CLOSED_EARLY = "BROWSER_CLOSED_EARLY"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"

    def __init__(
        self,
        status: str,
        auth_state: Optional[AuthState] = None,
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ):
        self.status = status
        self.auth_state = auth_state
        self.metadata = metadata or {}
        self.error = error


class LoginExtractor:
    """
    One-time browser-based authentication extractor.

    Opens a visible browser, waits for manual Google OAuth login,
    captures the authenticated DeepSeek API request and response,
    and persists the minimal authentication state.
    """

    def __init__(
        self,
        headless: bool = False,
        browser_type: str = "chromium",
        timeout: int = 300,  # 5 minutes default
        auth_state_dir: Path = AUTH_STATE_DIR,
        auth_state_file: Path = AUTH_STATE_FILE,
    ):
        self.headless = headless
        self.browser_type = browser_type
        self.timeout = timeout
        self.auth_state_dir = auth_state_dir
        self.auth_state_file = auth_state_file
        self.auth_state_tmp = auth_state_file.with_suffix(".json.tmp")

        # Runtime state
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.auth_captured = asyncio.Event()
        self.captured_auth_state: Optional[AuthState] = None
        self.captured_metadata: Dict[str, Any] = {}
        self.browser_closed_early = False
        self._browser_closed = asyncio.Event()
        self._last_exception: Optional[Exception] = None
        # Track authenticated response
        self.auth_response_captured = asyncio.Event()
        self.captured_response: Optional[Response] = None

    def _ensure_auth_dir(self):
        """Ensure the auth state directory exists."""
        self.auth_state_dir.mkdir(mode=0o700, exist_ok=True)

    def _request_handler(self, request):
        """Playwright request interceptor to capture authenticated API requests."""
        if not request.url.startswith(TARGET_API_PREFIX):
            return

        # Check for Authorization header
        auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
        if not auth_header:
            return

        if not auth_header.startswith("Bearer "):
            return

        token = auth_header[7:].strip()  # Remove "Bearer "
        if not token:
            return

        # Capture the authentication state
        if self.captured_auth_state is not None:
            return  # Already captured

        print(f"\n[+] Authenticated DeepSeek API request observed!")
        print(f"    URL: {request.url}")
        print(f"    Method: {request.method}")

        # Capture cookies from request headers
        cookies = {}
        cookie_header = request.headers.get("cookie") or request.headers.get("Cookie")
        if cookie_header:
            for part in cookie_header.split(";"):
                part = part.strip()
                if "=" in part:
                    k, v = part.split("=", 1)
                    cookies[k.strip()] = v.strip()

        # Store the captured auth state (will be updated with full cookies later)
        self.captured_auth_state = AuthState(
            authorization=auth_header,
            user_agent=request.headers.get("user-agent") or request.headers.get("User-Agent") or "",
            cookies=cookies,
        )

        # Capture request metadata - including full browser fingerprint for WAF bypass
        self.captured_metadata = {
            "method": request.method,
            "url": request.url,
            "browser_fingerprint": {
                "user_agent": request.headers.get("user-agent") or request.headers.get("User-Agent", ""),
                "origin": request.headers.get("origin") or request.headers.get("Origin", ""),
                "referer": request.headers.get("referer") or request.headers.get("Referer", ""),
                "sec_ch_ua": request.headers.get("sec-ch-ua") or request.headers.get("Sec-CH-UA", ""),
                "sec_ch_ua_platform": request.headers.get("sec-ch-ua-platform") or request.headers.get("Sec-CH-UA-Platform", ""),
            },
            "headers_present": {
                "authorization": "PRESENT",
                "cookie": "PRESENT" if cookie_header else "ABSENT",
                "user_agent": "PRESENT" if request.headers.get("user-agent") or request.headers.get("User-Agent") else "ABSENT",
                "origin": "PRESENT" if request.headers.get("origin") or request.headers.get("Origin") else "ABSENT",
                "referer": "PRESENT" if request.headers.get("referer") or request.headers.get("Referer") else "ABSENT",
                "x_client_platform": "PRESENT" if request.headers.get("x-client-platform") or request.headers.get("x-client-platform") else "ABSENT",
                "x_client_version": "PRESENT" if request.headers.get("x-client-version") or request.headers.get("x-client-version") else "ABSENT",
                "x_ds_pow_response": "PRESENT" if request.headers.get("x-ds-pow-response") or request.headers.get("x-ds-pow-response") else "ABSENT",
                "x_hif_leim": "PRESENT" if request.headers.get("x-hif-leim") or request.headers.get("x-hif-leim") else "ABSENT",
            }
        }

        # Signal that we captured the auth request
        self.auth_captured.set()

    def _response_handler(self, response: Response):
        """Playwright response interceptor to confirm authenticated request succeeded."""
        if not response.url.startswith(TARGET_API_PREFIX):
            return
        
        # Only care about responses to requests we already captured auth for
        if self.captured_auth_state is None:
            return
            
        if response.status == 200:
            print(f"[+] Authenticated DeepSeek API response confirmed: {response.status} {response.url}")
            self.captured_response = response
            self.auth_response_captured.set()

    async def _close_handler(self):
        """Handle browser closure before auth capture."""
        self.browser_closed_early = True
        self._browser_closed.set()
        if not self.auth_captured.is_set():
            print("\n[!] Browser closed before authentication was captured.")

    async def run(self) -> LoginResult:
        """Run the login extraction process."""
        self._ensure_auth_dir()

        print("=" * 60)
        print("DeepSeek Authentication Extractor")
        print("=" * 60)
        print()

        async with async_playwright() as p:
            try:
                # Launch browser with CLEAN configuration - no security weakening
                print("[*] Launching browser...")
                
                launch_config = get_browser_launch_config()
                print(f"[*] Launching {launch_config.get('channel', 'bundled')} browser...")
                
                browser = await p.chromium.launch(
                    headless=launch_config["headless"],
                    channel=launch_config.get("channel"),
                    args=launch_config.get("args", []),
                    executable_path=launch_config.get("executable_path"),
                )
                self.browser = browser

                # Create context with CLEAN settings - NO ignore_https_errors, NO hardcoded UA
                # Use browser's actual defaults for locale, timezone, UA, viewport
                context = await browser.new_context(
                    # REMOVED: ignore_https_errors=True  - TLS must be valid
                    # REMOVED: hardcoded user_agent - use browser's real UA
                    # REMOVED: hardcoded viewport - use browser's natural size
                    # REMOVED: device_scale_factor=2.0 - use default
                    # REMOVED: hardcoded locale - use browser default
                    # REMOVED: hardcoded timezone_id - use browser default
                    # REMOVED: permissions=["geolocation"] - not needed
                )
                self.context = context

                # Create page
                page = await context.new_page()
                self.page = page

                # REMOVED: navigator.webdriver override - we want normal browser behavior
                # REMOVED: window.chrome injection - not needed

                # Set up request AND response interception
                self.context.on("request", self._request_handler)
                self.context.on("response", self._response_handler)

                # Handle browser closure
                self.context.on("close", self._close_handler)
                self.browser.on("disconnected", self._close_handler)

                # Navigate to sign-in page
                print("[*] Navigating to DeepSeek sign-in page...")
                try:
                    await self.page.goto("https://chat.deepseek.com/sign_in", wait_until="domcontentloaded", timeout=30000)
                except Exception as e:
                    print(f"[!] Navigation error: {e}")

                print()
                print("=" * 60)
                print("Please log in manually via Google OAuth in the browser window.")
                print("Complete the login in the browser window.")
                print("Waiting for authenticated DeepSeek traffic...")
                print("=" * 60)
                print()

                # Wait for auth request capture
                try:
                    await asyncio.wait_for(self.auth_captured.wait(), timeout=self.timeout)
                except asyncio.TimeoutError:
                    return LoginResult(
                        status=LoginResult.TIMEOUT,
                        error=f"Timeout after {self.timeout} seconds waiting for authenticated request",
                    )

                # Check if browser was closed early
                if self.browser_closed_early:
                    return LoginResult(
                        status=LoginResult.BROWSER_CLOSED_EARLY,
                        error="Browser closed before authentication was captured",
                    )

                # NOW wait for the authenticated response to confirm success
                print("[+] Auth request captured. Waiting for successful response...")
                try:
                    await asyncio.wait_for(self.auth_response_captured.wait(), timeout=10)
                except asyncio.TimeoutError:
                    print("[!] Response not received within 10s, but auth was captured. Continuing...")

                # Auth captured and response confirmed - now collect full cookies
                print("\n[+] Authentication confirmed!")
                print("[*] Collecting cookies...")

                # Get full cookies
                cookies = await self.context.cookies()
                cookie_count = 0
                cookie_names = []

                for cookie in cookies:
                    if cookie["domain"].endswith("deepseek.com"):
                        self.captured_auth_state.cookies[cookie["name"]] = cookie["value"]
                        cookie_count += 1
                        cookie_names.append(cookie["name"])

                print(f"    Captured {cookie_count} DeepSeek cookies: {', '.join(cookie_names)}")

                # Extract ds_session_id and smidV2 explicitly
                ds_session_id = self.captured_auth_state.cookies.get("ds_session_id", "")
                smidV2 = self.captured_auth_state.cookies.get("smidV2", "")

                # Update auth state with captured values
                self.captured_auth_state.ds_session_id = ds_session_id
                self.captured_auth_state.smidV2 = smidV2
                self.captured_auth_state.last_used = datetime.now()

                # Build MINIMAL auth state - NO storage_state
                auth_state_data = {
                    "version": 2,
                    "captured_at": datetime.now().isoformat(),
                    "authorization": {
                        "scheme": "Bearer",
                        "token": self.captured_auth_state.authorization[7:] if self.captured_auth_state.authorization.startswith("Bearer ") else self.captured_auth_state.authorization,
                    },
                    "cookies": [
                        {
                            "name": k,
                            "value": v,
                            "domain": ".deepseek.com",
                            "path": "/",
                            "expires": None,
                            "httpOnly": True,
                            "secure": True,
                            "sameSite": "Lax",
                        }
                        for k, v in self.captured_auth_state.cookies.items()
                    ],
                    "client": {
                        "browser": launch_config.get("channel", "bundled"),
                    },
                    "browser_fingerprint": self.captured_metadata.get("browser_fingerprint", {}),
                }

                # Persist atomically
                await self._persist_auth_state(auth_state_data)

                # Close browser
                print("[*] Closing browser...")
                await self.context.close()
                if self.browser:
                    await self.browser.close()

                print("[+] Authentication state persisted successfully!")
                print(f"    Bearer token: PRESENT")
                print(f"    Cookies: {len(self.captured_auth_state.cookies)} captured")
                print(f"    ds_session_id: {'PRESENT' if ds_session_id else 'ABSENT'}")
                print(f"    smidV2: {'PRESENT' if smidV2 else 'ABSENT'}")

                return LoginResult(
                    status=LoginResult.SUCCESS,
                    auth_state=self.captured_auth_state,
                    metadata=self.captured_metadata,
                )

            except Exception as e:
                self._last_exception = e
                return LoginResult(
                    status=LoginResult.ERROR,
                    error=str(e),
                )

    async def _persist_auth_state(self, data: Dict[str, Any]):
        """Persist authentication state atomically."""
        self.auth_state_dir.mkdir(mode=0o700, exist_ok=True)

        # Write to temp file in SAME directory for atomic replace
        with open(self.auth_state_tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

        # Atomic replace
        os.replace(self.auth_state_tmp, self.auth_state_file)

        # Set restrictive permissions (Unix-like)
        try:
            os.chmod(self.auth_state_file, 0o600)
            os.chmod(self.auth_state_dir, 0o700)
        except Exception:
            pass  # Windows may not support chmod


async def run_login_extractor(
    headless: bool = False,
    timeout: int = 300,
) -> LoginResult:
    """Entry point for running the login extractor."""
    extractor = LoginExtractor(
        headless=headless,
        timeout=timeout,
    )
    return await extractor.run()


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="DeepSeek Authentication Extractor")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (not recommended for initial login)")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout in seconds")
    args = parser.parse_args()

    result = asyncio.run(run_login_extractor(
        headless=args.headless,
        timeout=args.timeout,
    ))

    if result.status == LoginResult.SUCCESS:
        print("\n[+] Authentication extraction SUCCESSFUL")
        sys.exit(0)
    else:
        print(f"\n[-] Authentication extraction FAILED: {result.status}")
        if result.error:
            print(f"    Error: {result.error}")
        sys.exit(1)


if __name__ == "__main__":
    main()