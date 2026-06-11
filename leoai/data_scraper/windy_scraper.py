#!/usr/bin/env python3
"""
Windy Forecast Scraper — Firefox / accuracy-first
Usage:
    python windy_scraper_firefox.py [lat] [lon]

Requirements:
    pip install playwright
    playwright install firefox
"""

import sys
import asyncio
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError
import re

# Defaults
DEFAULT_ZOOM = 9

DATA_SELECTOR = "table.forecast-table__table"
LOCATION_SELECTOR = "div.services__content"
CANVAS_SELECTOR = "canvas.forecast-table__canvas"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/117 Safari/537.36"
)

NAV_TIMEOUT = 90000
WAIT_TIMEOUT = 45000
RETRIES = 2


def build_url(lat, lon, zoom):
    return f"https://www.windy.com/{lat}/{lon}?satellite,{lat},{lon},{zoom}"


async def run_once(page, url, screenshot_path):
    """
    Navigate, ensure canvas is fully rendered, wait 5s, extract table HTML,
    and take a final screenshot.
    """
    await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)

    print("Waiting for forecast canvas to render...")
    try:
        await page.wait_for_function(
            f"""
            () => {{
                const c = document.querySelector('{CANVAS_SELECTOR}');
                if (!c) return false;
                return c.width > 0 && c.height > 0;
            }}
            """,
            timeout=WAIT_TIMEOUT
        )
    except TimeoutError:
        raise TimeoutError(f"Canvas '{CANVAS_SELECTOR}' failed to load.")

    table_node = await page.query_selector(DATA_SELECTOR)
    if not table_node:
        raise RuntimeError(
            f"Canvas rendered, but table selector '{DATA_SELECTOR}' not found."
        )

    # every <img> inside each row to get its src (or srcset) rewritten into a full Windy URL:
    await page.evaluate(
        """(selector) => {
            const table = document.querySelector(selector);
            if (!table) return;

            const rows = table.querySelectorAll("tr");

            const BASE = "https://www.windy.com";
            const imgs = table.querySelectorAll("img");

            imgs.forEach(img => {
                // Fix src
                const src = img.getAttribute("src");
                if (src && src.startsWith("/")) {
                    img.setAttribute("src", BASE + src);
                }

                // Fix srcset
                const srcset = img.getAttribute("srcset");
                if (srcset) {
                    const rewritten = srcset.split(",")
                        .map(item => {
                            const parts = item.trim().split(" ");
                            const url = parts[0];
                            const density = parts[1];
                            const fullUrl = url.startsWith("/") ? BASE + url : url;
                            return density ? `${fullUrl} ${density}` : fullUrl;
                        })
                        .join(", ");
                    img.setAttribute("srcset", rewritten);
                }
            });
        }""",
        DATA_SELECTOR
    )

    print("Canvas loaded. Waiting 5 seconds for final render stabilization...")
    await asyncio.sleep(5)

    # Guaranteed final screenshot
    try:
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"Screenshot saved → {screenshot_path}")
    except Exception as err:
        print(f"Screenshot failed: {err}")

    weather_raw_data = await table_node.inner_html()
    location_raw_data = ""
    location_node = await page.query_selector(LOCATION_SELECTOR)
    if location_node:
        text = await location_node.inner_text()
        location_raw_data = re.sub(r"\n+", " ", text)

    return location_raw_data, weather_raw_data


async def get_windy_forecast_raw_data(lat: float, lon: float):

    # Generate meaningful filenames
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"windy_{lat}_{lon}_{timestamp_str}"

    screenshot_filename = f"./data_windy/{base_name}.png"
    text_filename = f"./data_windy/{base_name}.txt"
    debug_filename = f"./data_windy/{base_name}_debug.png"

    url = build_url(lat, lon, DEFAULT_ZOOM)
    print(f"Scraping Windy Forecast @ {lat}, {lon}")
    print(f"→ {url}")

    async with async_playwright() as p:
        browser = await p.firefox.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )

        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1800, "height": 1200},
            java_script_enabled=True,
            device_scale_factor=1,
        )

        page = await context.new_page()

        location_raw_data = ""
        weather_raw_data = None
        last_error = None

        for attempt in range(1, RETRIES + 2):
            try:
                print(f"Attempt {attempt}…")
                location_raw_data, weather_raw_data = await run_once(page, url, screenshot_filename)
                break
            except Exception as exc:
                last_error = exc
                print(f"Attempt {attempt} failed: {exc}")

                await asyncio.sleep(2 * attempt)

                try:
                    await page.reload(
                        wait_until="domcontentloaded",
                        timeout=30000
                    )
                except Exception:
                    pass

        if weather_raw_data is None:
            print(
                f"❌ Final failure — saving debug screenshot to {debug_filename}")
            try:
                await page.screenshot(path=debug_filename, full_page=True)
            except Exception:
                pass
            await browser.close()
            sys.exit(1)

        await browser.close()

    # Write file
    timestamp = datetime.now().isoformat()
    content = f"""
# Windy Raw Data
location_raw_data: {location_raw_data}
timestamp: {timestamp}
latitude: {lat}
longitude: {lon}
source_url: {url}
screenshot: {screenshot_filename}

## Table Meta-data

Table has total 7 rows:

- Row 1: Date in python format %A %d
- Row 2: The icon image of weather
- Row 3: Hour in 24h format
- Row 4: Temperature in Celsius
- Row 5: Rain in mm
- Row 6: Wind in kt (knots)
- Row 7: Wind gusts in kt (knots)
- Row 8: Wind direction

## Table of Raw Weather Data
<table class="forecast-table__table">
{weather_raw_data}
</table>

# end_of_record
    """.strip()

    Path(text_filename).write_text(content, encoding="utf-8")
    print(f"✔ Forecast extracted and written to {text_filename}")
    return text_filename, screenshot_filename
