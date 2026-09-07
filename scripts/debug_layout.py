#!/usr/bin/env python3
"""
Layout Debugging Script

Compares a normal browser context vs a Playwright context to verify
CSS rendering is identical.
"""
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright


async def dump_page_info(page, label: str, output_dir: Path):
    """Dump HTML and computed CSS for a page."""
    print(f"\n[{label}] Dumping page info...")
    
    # Wait for network idle
    await page.wait_for_load_state("networkidle", timeout=30000)
    await asyncio.sleep(2)  # Extra time for CSS/JS
    
    # Get outer HTML
    html = await page.evaluate("document.documentElement.outerHTML")
    html_file = output_dir / f"{label}_layout.html"
    html_file.write_text(html, encoding="utf-8")
    print(f"  HTML saved to: {html_file} ({len(html)} chars)")
    
    # Get computed CSS of body
    css = await page.evaluate("window.getComputedStyle(document.body).cssText")
    css_file = output_dir / f"{label}_body_css.txt"
    css_file.write_text(css, encoding="utf-8")
    print(f"  Body CSS saved to: {css_file}")
    
    # Get viewport size
    viewport = await page.evaluate("() => ({ innerWidth: window.innerWidth, innerHeight: window.innerHeight })")
    print(f"  Viewport: {viewport}")
    
    # Get User-Agent
    ua = await page.evaluate("navigator.userAgent")
    print(f"  User-Agent: {ua[:80]}...")
    
    # Check for key DeepSeek elements
    has_chat = await page.evaluate("() => !!document.querySelector('[data-testid=chat-input]')")
    has_sider = await page.evaluate("() => !!document.querySelector('.sider') || !!document.querySelector('[class*=sider]')")
    print(f"  Chat input found: {has_chat}")
    print(f"  Sider found: {has_sider}")
    
    return {
        "html_file": html_file,
        "css_file": css_file,
        "viewport": viewport,
        "user_agent": ua,
    }


async def run_normal_browser(output_dir: Path):
    """Launch a normal browser (no Playwright modifications)."""
    print("\n" + "="*60)
    print("LAUNCHING NORMAL BROWSER (baseline)")
    print("="*60)
    
    async with async_playwright() as p:
        # Use system Edge with NO custom args
        browser = await p.chromium.launch(
            headless=False,
            channel="msedge",
            args=[],
        )
        context = await browser.new_context()  # NO custom viewport, NO custom UA
        page = await context.new_page()
        
        print("[*] Navigating to DeepSeek...")
        await page.goto("https://chat.deepseek.com", wait_until="domcontentloaded", timeout=30000)
        
        result = await dump_page_info(page, "normal", output_dir)
        
        print("\n[*] Normal browser will stay open for 10 seconds for visual inspection...")
        await asyncio.sleep(10)
        
        await context.close()
        await browser.close()
        
    return result


async def run_playwright_browser(output_dir: Path):
    """Launch a Playwright browser with the hardened config."""
    print("\n" + "="*60)
    print("LAUNCHING PLAYWRIGHT BROWSER (hardened config)")
    print("="*60)
    
    async with async_playwright() as p:
        # Use the SAME hardened config as login_extractor.py
        base_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ]
        
        browser = await p.chromium.launch(
            headless=False,
            channel="msedge",
            args=base_args,
        )
        # CLEAN context - no ignore_https_errors, no hardcoded UA, no hardcoded viewport
        context = await browser.new_context()
        page = await context.new_page()
        
        print("[*] Navigating to DeepSeek...")
        await page.goto("https://chat.deepseek.com", wait_until="domcontentloaded", timeout=30000)
        
        result = await dump_page_info(page, "playwright", output_dir)
        
        print("\n[*] Playwright browser will stay open for 10 seconds for visual inspection...")
        await asyncio.sleep(10)
        
        await context.close()
        await browser.close()
        
    return result


def compare_results(normal: dict, playwright: dict, output_dir: Path):
    """Compare the two results."""
    print("\n" + "="*60)
    print("COMPARISON RESULTS")
    print("="*60)
    
    # Compare viewports
    nv = normal["viewport"]
    pv = playwright["viewport"]
    viewport_match = nv == pv
    print(f"\nViewport match: {viewport_match}")
    print(f"  Normal:      {nv}")
    print(f"  Playwright:  {pv}")
    
    # Compare User-Agents
    nua = normal["user_agent"]
    pua = playwright["user_agent"]
    ua_match = nua == pua
    print(f"\nUser-Agent match: {ua_match}")
    print(f"  Normal:      {nua[:100]}...")
    print(f"  Playwright:  {pua[:100]}...")
    
    # Compare body CSS
    ncss = Path(normal["css_file"]).read_text(encoding="utf-8")
    pcss = Path(playwright["css_file"]).read_text(encoding="utf-8")
    css_match = ncss == pcss
    print(f"\nBody CSS match: {css_match}")
    if not css_match:
        print("  CSS DIFFERENCES:")
        for i, (nc, pc) in enumerate(zip(ncss.split(";"), pcss.split(";"))):
            if nc != pc:
                print(f"    Normal:      {nc.strip()}")
                print(f"    Playwright:  {pc.strip()}")
                if i > 20:
                    print("    ... (truncated)")
                    break
    
    # Summary
    print("\n" + "="*60)
    if viewport_match and ua_match and css_match:
        print("[PASS] LAYOUT MATCHES PERFECTLY")
    else:
        print("[FAIL] LAYOUT DIFFERENCES DETECTED")
        if not viewport_match:
            print("  - Viewport mismatch")
        if not ua_match:
            print("  - User-Agent mismatch")
        if not css_match:
            print("  - Body CSS mismatch")
    print("="*60)


async def main():
    output_dir = Path("debug_output")
    output_dir.mkdir(exist_ok=True)
    
    print("DeepSeek Layout Debugging Script")
    print("This will open two browser windows side by side.")
    print("Output will be saved to:", output_dir.absolute())
    
    normal = await run_normal_browser(output_dir)
    playwright = await run_playwright_browser(output_dir)
    
    compare_results(normal, playwright, output_dir)


if __name__ == "__main__":
    asyncio.run(main())