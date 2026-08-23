import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

WOSM_URLS = [
    "https://www.scout.org/get-involved/act-now/volunteer",
    "https://www.scout.org/get-involved/act-now/careers",
]
STATE_FILE = Path("state.json")
USER_AGENT = "WOSM-Volunteer-Monitor/1.0 (+GitHub Actions)"

def fetch(url):
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    return r.text

def clean_page(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)

def extract_opportunities(url, html):
    soup = BeautifulSoup(html, "html.parser")
    items = []

    # Collect headings and nearby links. This is deliberately conservative:
    # a human/AI can review the changed page text rather than guessing every card.
    for a in soup.find_all("a", href=True):
        label = " ".join(a.stripped_strings)
        href = a["href"]
        if not label or len(label) < 4:
            continue
        if href.startswith("/"):
            href = "https://www.scout.org" + href
        if "scout.org" not in href:
            continue
        low = label.lower()
        if any(k in low for k in ["volunteer", "open call", "consultant", "apply", "opportunit"]):
            items.append({"title": label, "url": href})

    # Deduplicate.
    seen = set()
    out = []
    for item in items:
        key = (item["title"].strip().lower(), item["url"])
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out

def load_state():
    if not STATE_FILE.exists():
        return {"pages": {}, "items": {}}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

def telegram(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": message, "disable_web_page_preview": False},
        timeout=30,
    )
    r.raise_for_status()

def ai_review(changes):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    # Optional AI layer. It does not decide whether something exists;
    # the deterministic monitor detects the change first.
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    prompt = """You are reviewing new WOSM (World Organization of the Scout Movement)
volunteer/open-call information. Summarize only genuinely new volunteer/open-call
opportunities. Ignore ordinary articles, staff jobs, and unrelated links.
Return concise plain text with:
- Opportunity
- Deadline if stated
- Eligibility if stated
- Application link
- One-sentence summary
If none are genuine opportunities, say NO_RELEVANT_OPPORTUNITY.

New/changed information:
""" + json.dumps(changes, ensure_ascii=False, indent=2)

    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        input=prompt,
    )
    return response.output_text.strip()

def main():
    state = load_state()
    changes = []

    for url in WOSM_URLS:
        html = fetch(url)
        text = clean_page(html)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

        previous = state["pages"].get(url)
        if previous and previous != digest:
            # Include the current page text for AI review and a deterministic alert.
            changes.append({"page": url, "content": text[:30000]})

        state["pages"][url] = digest

        for item in extract_opportunities(url, html):
            key = hashlib.sha256(
                f'{item["title"]}|{item["url"]}'.encode("utf-8")
            ).hexdigest()
            if key not in state["items"]:
                state["items"][key] = {
                    **item,
                    "first_seen": datetime.now(timezone.utc).isoformat(),
                }

    # First run establishes a baseline and does not spam.
    if not state.get("initialized"):
        state["initialized"] = True
        save_state(state)
        print("Baseline created. No notification sent.")
        return

    save_state(state)

    if not changes:
        print("No page changes detected.")
        return

    reviewed = ai_review(changes)

    if reviewed == "NO_RELEVANT_OPPORTUNITY":
        print("WOSM changed, but AI found no relevant volunteer/open call.")
        return

    if reviewed:
        message = "🔔 New/changed WOSM volunteer information\n\n" + reviewed
    else:
        message = (
            "🔔 WOSM volunteer pages changed.\n\n"
            "Review the current opportunities:\n" +
            "\n".join(f"• {u}" for u in WOSM_URLS)
        )

    telegram(message)
    print("Notification sent.")

if __name__ == "__main__":
    main()
