import os
import hashlib
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = "https://www.cinemacity.cz/films/odyssea/7268s2r"
STATE_FILE = "state.txt"

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def get_page_text() -> str:
    """Render the page with a real browser (content is JS-driven), click
    the buy-tickets button the same way a visitor would, follow it if it
    opens a new tab (common for multiplex booking systems, which often
    run on a separate ticketing domain), then grab all visible text,
    including anything sitting in iframes."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        page = context.new_page()
        page.goto(URL, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(2000)

        # Dismiss a cookie-consent banner if it's covering the button
        for label in ["Souhlasím", "Přijmout vše", "Accept All", "Accept all cookies"]:
            try:
                page.get_by_text(label, exact=False).first.click(timeout=3000)
                page.wait_for_timeout(1000)
                break
            except Exception:
                continue

        # A "choose your cinema" modal often pops up on first visit and
        # blocks every click underneath it. Try to select Flora (the only
        # cinema we care about) directly; if that's not offered, just
        # close the modal so we can proceed.
        modal_handled = False
        try:
            page.get_by_text("Flora", exact=False).first.click(timeout=4000)
            print("Selected Flora from the cinema picker.")
            modal_handled = True
        except Exception:
            pass

        if not modal_handled:
            for attempt_name, attempt in [
                ("Escape key", lambda: page.keyboard.press("Escape")),
                ("modal close button", lambda: page.locator(".modal .close").first.click(timeout=3000)),
                ("backdrop click", lambda: page.locator(".modal-backdrop").first.click(timeout=3000, force=True)),
            ]:
                try:
                    attempt()
                    page.wait_for_timeout(1000)
                    print(f"Dismissed the cinema-picker modal via: {attempt_name}")
                    modal_handled = True
                    break
                except Exception:
                    continue

        if not modal_handled:
            print("Could not dismiss the cinema-picker modal — the click below will likely fail.")

        page.wait_for_timeout(1000)

        # Trigger the booking flow the same way a visitor would, and
        # watch for a new tab — multiplex booking widgets frequently open
        # on a separate ticketing domain in a new tab/window.
        booking_page = page
        try:
            with context.expect_page(timeout=8000) as new_page_info:
                page.get_by_text("NÁKUP VSTUPENEK", exact=False).first.click(timeout=8000)
            booking_page = new_page_info.value
            try:
                booking_page.wait_for_load_state("networkidle", timeout=15000)
            except PWTimeout:
                pass
            print(f"Buy-tickets click opened a new tab: {booking_page.url}")
        except PWTimeout:
            print("No new tab opened within 8s — assuming in-page navigation.")
        except Exception as e:
            print(f"Could not click the buy-tickets button: {e}")

        booking_page.wait_for_timeout(5000)  # let the booking widget load/render

        chunks = [booking_page.inner_text("body")]
        for frame in booking_page.frames:
            if frame != booking_page.main_frame:
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
