import os
import hashlib
import requests
from playwright.sync_api import sync_playwright

URL = "https://www.cinemacity.cz/films/odyssea/7268s2r"
STATE_FILE = "state.txt"

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def get_page_text() -> str:
    """Render the page with a real browser (content is JS-driven) and
    grab all visible text, including anything sitting in iframes
    (the booking widget sometimes lives in a separate embedded frame)."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(URL, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(4000)  # extra buffer for late JS rendering

        chunks = [page.inner_text("body")]
        for frame in page.frames:
            if frame != page.main_frame:
                try:
                    chunks.append(frame.inner_text("body"))
                except Exception:
                    pass

        browser.close()
        return "\n".join(chunks)


def notify(message: str) -> None:
    api = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(api, data={"chat_id": CHAT_ID, "text": message}, timeout=15)
    resp.raise_for_status()


def main() -> None:
    text = get_page_text()
    print(f"Captured {len(text)} characters of page text.")
    print("--- first 500 chars (for debugging in the Actions log) ---")
    print(text[:500])

    new_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    old_hash = None
    if os.path.exists(STATE_FILE):
        old_hash = open(STATE_FILE, encoding="utf-8").read().strip()

    if old_hash is None:
        print("No previous state found — saving baseline, no notification sent.")
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write(new_hash)
        return

    if new_hash != old_hash:
        print("Change detected — sending Telegram notification.")
        notify(f"Stránka s Odysseou se změnila, mrkni na to:\n{URL}")
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write(new_hash)
    else:
        print("No change since last check.")


if __name__ == "__main__":
    main()
