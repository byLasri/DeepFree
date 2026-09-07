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

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from ..session import AuthState


def get_playwright_launch_config() -> dict:
    """
    Detect system default browser and return appropriate Playwright launch configuration.
    Prioritizes system-installed Chromium-based browsers (Edge, Chrome, Brave) over Playwright's bundled Chromium.
    """
    system = platform.system()
    launch_config = {
        "headless": False,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
        ]
    }
    
    system = platform.system()
    
    if platform.system() == "Windows":
        # Windows default is usually Edge. Check for Edge, then Chrome, then Brave.
        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        if any(os.path.exists(p) for p in edge_paths):
            return {"headless": False, "channel": "msedge", "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-setuid-sandbox"]}
        elif shutil.which("chrome"):
            return {"headless": False, "channel": "chrome", "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-setuid-sandbox"]}
        else:
            print("⚠️ No system Chromium browser found. Falling back to Playwright bundled Chromium.")
            return {"headless": False, "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-setuid-sandbox"]}
            
    elif platform.system() == "Darwin":  # macOS
        # macOS default is Safari, but Playwright CANNOT automate Safari for network interception.
        # We must fallback to Chrome or Edge if installed.
        chrome_path = "/Applications/Google Chrome.app"
        edge_path = "/Applications/Microsoft Edge.app"
        if os.path.exists(chrome_path):
            return {"headless": False, "channel": "chrome", "args": ["--disable-blink-features=AutomationControlled"]}
        elif os.path.exists(edge_path):
            return {"headless": False, "channel": "msedge", "args": ["--disable-blink-features=AutomationControlled"]}
        else:
            print("⚠️ No system Chromium browser found. Falling back to Playwright bundled Chromium.")
            return {"headless": False, "args": ["--disable-blink-features=AutomationControlled"]}
    else:  # Linux
        # Check for google-chrome, chromium, or brave
        if shutil.which("google-chrome"):
            return {"headless": False, "channel": "chrome", "args": ["--disable-blink-features=AutomationControlled"]}
        elif shutil.which("chromium"):
            # On Linux, 'chromium' channel might not exist, use bundled
            print("Detected system browser: Chromium")
            return {"headless": False, "channel": "chromium", "args": ["--disable-blink-features=AutomationControlled"]}
        elif shutil.which("brave-browser") or shutil.which("brave"):
            brave_path = shutil.which("brave-browser") or shutil.which("brave")
            return {"headless": False, "executable_path": shutil.which("brave-browser") or shutil.which("brave"), "args": ["--disable-blink-features=AutomationControlled"]}
        else:
            print("⚠️ No system Chromium browser found. Falling back to Playwright bundled Chromium.")
            return {"headless": False, "args": ["--disable-blink-features=AutomationControlled"]}

    return {"headless": False, "args": ["--disable-blink-features=AutomationControlled"]}


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
    captures the authenticated DeepSeek API request, and persists
    the authentication state.
    """

    def __init__(
        self,
        headless: bool = False,
        browser_type: str = "chromium",
        use_persistent_profile: bool = False,
        timeout: int = 300,  # 5 minutes default
        auth_state_dir: Path = AUTH_STATE_DIR,
        auth_state_file: Path = AUTH_STATE_FILE,
    ):
        self.headless = headless
        self.browser_type = browser_type
        self.use_persistent_profile = use_persistent_profile
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

        # Capture request metadata
        self.captured_metadata = {
            "method": request.method,
            "url": request.url,
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

        # Signal that we captured the auth
        self.auth_captured.set()

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
                # Launch browser with anti-detection measures using dynamic browser detection
                print("[*] Launching browser with anti-detection measures...")
                
                # Get dynamic browser launch configuration
                launch_config = get_browser_launch_config()
                
                # Determine if we should use persistent profile
                if self.use_persistent_profile:
                    # Use persistent profile with detected system browser
                    user_data_dir = self._get_chrome_user_data_dir()
                    print(f"[*] Using real Chrome profile: {self._get_chrome_user_data_dir()}")
                    print("⚠️  WARNING: Ensure ALL Chrome/Edge/Brave windows are completely closed before proceeding!")
                    
                    context = await p.chromium.launch_persistent_context(
                        user_data_dir=self._get_chrome_user_data_dir(),
                        headless=self.headless,
                        channel="chrome",  # Use system Chrome for persistent profile
                        args=["--disable-blink-features=AutomationControlled"],
                        ignore_https_errors=True,
                        viewport={"width": 1920, "height": 1080},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        locale="en-US",
                        timezone_id="America/New_York",
                    )
                    self.context = context
                    self.browser = None
                    page = context.pages[0] if context.pages else await context.new_page()
                    self.page = page
                    self.browser = None
                else:
                    # Get dynamic browser launch configuration
                    launch_config = get_browser_launch_config()
                    
                    # Launch browser with dynamic configuration
                    print(f"[*] Launching {launch_config.get('channel', 'bundled')} browser...")
                    browser = await p.chromium.launch(
                        headless=launch_config["headless"],
                        channel=launch_config.get("channel"),
                        args=launch_config.get("args", []),
                        executable_path=launch_config.get("executable_path"),
                    )
                    self.browser = browser

                    # Create context with anti-detection settings
                    context = await browser.new_context(
                        ignore_https_errors=True,
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        viewport={"width": 1920, "height": 1080},
                        locale="en-US",
                        timezone_id="America/New_York",
                    )
                    self.context = context

                    # CRITICAL: Inject script to overwrite navigator.webdriver BEFORE any page loads
                    await context.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', {
                            get: () => undefined
                        });
                    """)

                    page = await context.new_page()
                    self.page = page
                    self.browser = browser
                    self.context = context

                # Set up request interception
                self.context.on("request", self._request_handler)

                # Handle browser closure
                if self.use_persistent_profile:
                    self.context.on("close", self._close_handler)
                else:
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

                # Wait for auth capture or timeout/browser close
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

                # Auth captured - now collect full cookies and storage state
                print("\n[+] Authenticated request captured!")
                print("[*] Collecting cookies and storage state...")

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

                # Capture storage state for potential future use
                storage_state = await self.context.storage_state()

                # Extract ds_session_id and smidV2 explicitly
                ds_session_id = self.captured_auth_state.cookies.get("ds_session_id", "")
                smidV2 = self.captured_auth_state.cookies.get("smidV2", "")

                # Update auth state with captured values
                self.captured_auth_state.ds_session_id = ds_session_id
                self.captured_auth_state.smidV2 = smidV2
                self.captured_auth_state.last_used = datetime.now()

                # Build complete auth state with storage state
                auth_state_data = {
                    "version": 1,
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
                    "storage_state": storage_state,
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

    def _get_chrome_user_data_dir(self) -> str:
        """Get the default Chrome User Data directory based on OS."""
        os_name = platform.system()
        if os_name == "Windows":
            return os.path.join(os.environ["LOCALAPPDATA"], "Google", "Chrome", "User Data")
        elif os_name == "Darwin":  # macOS
            return os.path.expanduser("~/Library/Application Support/Google/Chrome")
        else:  # Linux
            return os.path.expanduser("~/.config/google-chrome")

    async def _persist_auth_state(self, data: Dict[str, Any]):
        """Persist authentication state atomically."""
        self.auth_state_dir.mkdir(mode=0o700, exist_ok=True)

        # Write to temp file
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


def _get_chrome_user_data_dir_static() -> str:
    """Static method to get Chrome user data directory."""
    os_name = platform.system()
    if os_name == "Windows":
        return os.path.join(os.environ["LOCALAPPDATA"], "Google", "Chrome", "User Data")
    elif os_name == "Darwin":  # macOS
        return os.path.expanduser("~/Library/Application Support/Google/Chrome")
    else:  # Linux
        return os.path.expanduser("~/.config/google-chrome")


async def run_login_extractor(
    headless: bool = False,
    use_persistent_profile: bool = False,
    timeout: int = 300,
) -> LoginResult:
    """Entry point for running the login extractor."""
    extractor = LoginExtractor(
        headless=headless,
        use_persistent_profile=use_persistent_profile,
        timeout=timeout,
    )
    return await extractor.run()


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="DeepSeek Authentication Extractor")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (not recommended for initial login)")
    parser.add_argument("--persistent-profile", action="store_true", help="Use real Chrome profile (requires all Chrome windows closed)")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout in seconds")
    args = parser.parse_args()

    result = asyncio.run(run_login_extractor(
        headless=args.headless,
        use_persistent_profile=args.persistent_profile,
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