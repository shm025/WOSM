import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


WOSM_URLS = [
    "https://www.scout.org/get-involved/act-now/volunteer",
    "https://www.scout.org/get-involved/act-now/careers",
]

STATE_FILE = Path("state.json")
USER_AGENT = "WOSM-Volunteer-Monitor/2.0 (+GitHub Actions)"
WOSM_DOMAIN = "scout.org"


def fetch(url):
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def clean_page(html):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    text = soup.get_text("\n", strip=True)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def normalize_url(url):
    url = url.split("#")[0].strip()

    if url.startswith("/"):
        url = urljoin("https://www.scout.org", url)

    return url.rstrip("/")


def is_candidate_link(title, url):
    title_low = title.lower()
    url_low = url.lower()

    # Ignore generic navigation.
    ignored_titles = {
        "volunteer",
        "apply",
        "careers",
        "join scouting",
        "donate to scouting",
        "submit your project",
        "partner with us",
        "learn more",
        "read more",
        "contact us",
    }

    if title_low in ignored_titles:
        return False

    # Ignore obvious navigation / utility URLs.
    ignored_url_parts = [
        "/get-involved/act-now/volunteer",
        "/get-involved/act-now/careers",
        "/about",
        "/contact",
        "/privacy",
        "/terms",
        "/search",
    ]

    if any(part in url_low for part in ignored_url_parts):
        return False

    # Careers links are handled separately, but we still want
    # actual position pages rather than the careers landing page.
    if "careers.scout.org" in url_low:
        return True

    keywords = [
        "volunteer",
        "open call",
        "consultant",
        "consultancy",
        "opportunity",
        "application",
        "apply",
        "position",
        "internship",
        "intern",
        "coordinator",
        "advisor",
        "director",
        "manager",
        "specialist",
        "officer",
    ]

    return any(keyword in title_low or keyword in url_low for keyword in keywords)


def extract_opportunities(url, html):
    soup = BeautifulSoup(html, "html.parser")
    items = []

    # Look at links in headings/cards/tables as well as normal links.
    for a in soup.find_all("a", href=True):
        title = " ".join(a.stripped_strings).strip()

        if not title or len(title) < 5:
            continue

        href = normalize_url(a["href"])

        if not href.startswith("http"):
            continue

        if not (
            "scout.org" in href.lower()
            or "careers.scout.org" in href.lower()
        ):
            continue

        if not is_candidate_link(title, href):
            continue

        # Try to capture useful nearby text.
        context = ""

        parent = a.parent
        if parent:
            context = " ".join(parent.stripped_strings)

        # Look at the closest table row if applicable.
        row = a.find_parent("tr")
        if row:
            context = " ".join(row.stripped_strings)

        items.append(
            {
                "title": title,
                "url": href,
                "source_page": url,
                "context": context[:2000],
            }
        )

    # Also inspect headings followed by links.
    for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
        heading_text = " ".join(heading.stripped_strings).strip()

        if not heading_text or len(heading_text) < 5:
            continue

        link = heading.find_next("a", href=True)

        if not link:
            continue

        href = normalize_url(link["href"])

        if not href.startswith("http"):
            continue

        if not (
            "scout.org" in href.lower()
            or "careers.scout.org" in href.lower()
        ):
            continue

        if not is_candidate_link(heading_text, href):
            continue

        items.append(
            {
                "title": heading_text,
                "url": href,
                "source_page": url,
                "context": heading_text[:2000],
            }
        )

    # Deduplicate.
    seen = set()
    result = []

    for item in items:
        key = (
            item["title"].strip().lower(),
            normalize_url(item["url"]),
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(item)

    return result


def load_state():
    if not STATE_FILE.exists():
        return {
            "pages": {},
            "items": {},
            "initialized": False,
        }

    try:
        return json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError:
        print("WARNING: state.json was invalid. Starting fresh.")
        return {
            "pages": {},
            "items": {},
            "initialized": False,
        }


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(
            state,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def item_key(item):
    value = f'{item["title"].strip().lower()}|{normalize_url(item["url"])}'

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    if not chat_id:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID is missing."
        )

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": False,
        },
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(
            f"Telegram API error {response.status_code}: "
            f"{response.text}"
        )


def ai_review(new_items):
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return None

    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    prompt = """
You are reviewing new information from the World Organization
of the Scout Movement (WOSM).

Identify ONLY genuine:
- volunteer opportunities
- open calls
- volunteer roles
- internships
- consultancies that are relevant to volunteering or participation

Ignore:
- ordinary staff jobs unless they are clearly relevant to the
  user's monitoring purpose
- generic navigation links
- generic "Apply" links
- pages that are not actual opportunities
- unrelated articles

For each relevant opportunity, provide:

Opportunity:
Deadline:
Location:
Eligibility:
Application:
Summary:

If there are no relevant opportunities, return exactly:

NO_RELEVANT_OPPORTUNITY

New items:
""" + json.dumps(
        new_items,
        ensure_ascii=False,
        indent=2,
    )

    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        input=prompt,
    )

    return response.output_text.strip()


def format_basic_message(items):
    lines = [
        "🔔 New WOSM opportunity detected!",
        "",
    ]

    for item in items:
        lines.append(f"• {item['title']}")
        lines.append(f"  {item['url']}")

        if item.get("context"):
            lines.append(f"  {item['context'][:500]}")

        lines.append("")

    return "\n".join(lines)


def main():
    state = load_state()

    new_items = []
    current_items = {}

    for page_url in WOSM_URLS:
        print(f"Checking: {page_url}")

        html = fetch(page_url)
        text = clean_page(html)

        page_digest = hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()

        state["pages"][page_url] = page_digest

        opportunities = extract_opportunities(
            page_url,
            html,
        )

        print(
            f"Found {len(opportunities)} candidate opportunities "
            f"on this page."
        )

        for item in opportunities:
            key = item_key(item)

            current_items[key] = item

            if key not in state["items"]:
                new_items.append(item)

    print(f"New candidate items: {len(new_items)}")

    # First run:
    # Save everything as the baseline but do NOT notify.
    if not state.get("initialized"):
        for key, item in current_items.items():
            state["items"][key] = {
                **item,
                "first_seen": datetime.now(
                    timezone.utc
                ).isoformat(),
            }

        state["initialized"] = True
        save_state(state)

        print(
            "Baseline created. "
            "No notification sent on first run."
        )
        return

    # Save newly discovered items.
    for item in new_items:
        key = item_key(item)

        state["items"][key] = {
            **item,
            "first_seen": datetime.now(
                timezone.utc
            ).isoformat(),
        }

    save_state(state)

    if not new_items:
        print("No new opportunities detected.")
        return

    print("New opportunities detected.")

    # Ask AI to filter/summarize if available.
    reviewed = ai_review(new_items)

    if reviewed == "NO_RELEVANT_OPPORTUNITY":
        print(
            "New links were found, but AI determined "
            "there were no relevant opportunities."
        )
        return

    if reviewed:
        message = (
            "🔔 New WOSM volunteer/opportunity information\n\n"
            + reviewed
        )
    else:
        message = format_basic_message(new_items)

    telegram(message)

    print("Notification sent.")


if __name__ == "__main__":
    main()
