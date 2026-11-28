import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import subprocess
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode, urljoin, urlsplit


BASE = "https://slickdeals.net"
SORTS = ("voteavg", "views", "replycount", "dateline")
MAX_PER_CATEGORY = 15
WINDOW = timedelta(hours=24)
GIFT_CARD = re.compile(r"\b(?:e[- ]?)?gift[ -]?cards?\b", re.I)
SWITCH_2_PLATFORM = r"(?:nintendo\s+)?switch\s*2\b(?![‐‑‒–—-]?\s*(?:packs?|pks?|counts?|cts?|pcs|pieces?)\b)"
SWITCH_2 = re.compile(rf"\b{SWITCH_2_PLATFORM}", re.I)
LEGACY_CONSOLE = r"(?:ps[345]|playstation(?:\s*[345])?|xbox(?:\s+(?:one|series\s+[sx]))?|nintendo\s+switch)"
TECH_PLATFORM = re.compile(rf"\b{LEGACY_CONSOLE}\b|\bswitch\s+(?:oled|lite)\b|(?<=[(\[])switch(?=[)\]])", re.I)
PC_DIGITAL_OFFER = r"pc\s+digital\s+(?:games?|(?:game\s+)?downloads?|codes?|keys?)"
PC_PLATFORM = rf"(?:{PC_DIGITAL_OFFER}|pc(?:\s+digital)?|windows|steam|epic(?:\s+games)?|gog(?:\.com)?|battle\.net)"
PC_GAME = re.compile(
    rf"\b(?:{PC_DIGITAL_OFFER}|pc\s+(?:(?:video\s+)?games?|(?:game\s+)?codes?|download|gaming\s+bundle)|"
    r"steam\s+(?:keys?|codes?|games?|bundles?|downloads?|version)|"
    r"epic\s+(?:games(?:\s+store)?|store)|gog(?:\.com)?|battle\.net)\b"
    rf"|(?:(?P<paren>\()|\[)\s*(?:mac\s*/\s*)*{PC_PLATFORM}"
    rf"(?:\s*/\s*(?:{PC_PLATFORM}|{SWITCH_2_PLATFORM}|{LEGACY_CONSOLE}|mac))*\s*(?(paren)\)|\])"
    r"|\bsteam(?=\s*(?:$|:))|(?:\b(?:at|on|from)\s+|@\s*)steam\b", re.I,
)
MAC_TAG = re.compile(r"\(\s*mac\s*\)|\[\s*mac\s*\]", re.I)
BONUS = re.compile(
    r"(?:\s+(?:with\b|w/|includes?\b|plus\b)\s*|\s*\+\s*)"
    r"(?:an?\s+)?(?:free|bonus|(?:pc\s+)?games?|dlc)\b", re.I,
)
HARDWARE = re.compile(
    r"\b(?:computers?|laptops?|desktops?|chromebooks?|macbooks?|tablets?|ipads?|"
    r"smartphones?|cell phones?|iphones?|smart ?watches?|smart ?tv|tvs?|televisions?|"
    r"monitors?|projectors?|headphones?|earbuds?|soundbars?|power[ -]?banks?|chargers?|portable batteries|"
    r"graphics cards?|geforce|radeon|gpus?|cpus?|processors?|ssds?|nvme|motherboards?|"
    r"(?:mini|gaming|desktop|prebuilt)\s+pcs?|routers?|keyboards?|gaming mice|"
    r"steam\s+(?:deck|machine|frame|controller|hardware))\b|^pcs?\b", re.I,
)
SOFTWARE = re.compile(r"\b(?:microsoft office|office \d{4}|windows|antivirus|vpns?|software)\b", re.I)
REWARDS_OFFER = re.compile(r"\b(?:cash[ -]?back|credit[ -]cards?|rewards|statement credits?)\b", re.I)
TECH = re.compile(
    r"\b(?:tech|electronics|wi-fi|video games?|xbox|playstation|ps5|nintendo switch|"
    r"switch\s*(?:2(?:pks?|cts?|pcs)?|oled|lite))\b", re.I,
)
TECH_STORES = {"apple", "b&h", "b&h photo", "dell", "lenovo", "micro center", "newegg"}
PC_GAME_STORES = {"battle.net", "epic games", "epic games store", "gog", "gog.com", "steam"}


def get_html(url):
    return subprocess.run(
        ["curl", "--fail", "--silent", "--show-error", "--location",
         "--proto", "=https", "--max-time", "20", "--retry", "1", url],
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout


class DealMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.meta = {}
        self.store = None
        self.anchor = None
        self.stats = None
        self.votes = 0
        self.title_parts = []
        self.in_title = False
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "a" and attrs.get("data-thread-id"):
            self.anchor = attrs
            self.in_title = True
        elif tag == "td" and (match := re.fullmatch(
            r"Replies: ([\d,]+), Views: ([\d,]+)", attrs.get("title") or ""
        )):
            self.stats = tuple(int(value.replace(",", "")) for value in match.groups())
        elif tag == "img" and (match := re.fullmatch(
            r"Votes: [\d,]+ Score: ([+-]?\d+)", attrs.get("alt") or ""
        )):
            self.votes = int(match[1])
        elif tag == "meta" and (name := attrs.get("name") or attrs.get("property")):
            self.meta[name] = attrs.get("content") or ""
        if not self.store and attrs.get("data-storename"):
            self.store = attrs["data-storename"].strip() or None

    def handle_endtag(self, tag):
        if tag == "a":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)


def popularity(votes, views, comments):
    return round(votes + 3 * math.log10(1 + views) + 2 * comments, 2)


def read_list(html):
    for row in re.findall(r'<tr\b[^>]*\bid="sdpostrow_\d+"[^>]*>.*?</tr>', html, re.S):
        markup = DealMarkup(row)
        if not markup.anchor or not markup.stats:
            continue
        link = markup.anchor.get("href") or ""
        thread_id = markup.anchor["data-thread-id"]
        if not re.fullmatch(rf"/f/{re.escape(thread_id)}(?:-[^?#]+)?", link):
            continue
        title = " ".join("".join(markup.title_parts).split())
        if not title:
            continue
        comments, views = markup.stats
        yield {
            "id": thread_id, "title": title, "link": BASE + link,
            "price": markup.anchor.get("data-final-price") or None,
            "votes": markup.votes, "views": views, "comments": comments,
            "score": popularity(markup.votes, views, comments),
        }


def load_candidates(sort, fetch):
    query = urlencode({"f": 9, "daysprune": 1, "order": "desc", "sort": sort})
    deals = list(read_list(fetch(f"{BASE}/forums/forumdisplay.php?{query}")))
    if not deals:
        raise ValueError(f"No readable deal rows in Slickdeals {sort} list")
    return deals


def classify(title, category="", store=None):
    offer = re.split(r"(?i)\s+(?:with|includes?|plus|\+)\s+", title, maxsplit=1)[0]
    if GIFT_CARD.search(category) or GIFT_CARD.search(offer):
        return "giftcards"

    main_item = BONUS.split(title, maxsplit=1)[0]
    hardware = HARDWARE.search(main_item)
    platform_title = main_item if hardware else title
    markers = ((SWITCH_2.search(platform_title), "games"), (PC_GAME.search(platform_title), "games"),
               (TECH_PLATFORM.search(platform_title), "tech"))
    platforms = [(match.start(), group) for match, group in markers if match]
    if platforms:
        return min(platforms, key=lambda platform: platform[0])[1]
    if hardware or SOFTWARE.search(main_item):
        return "tech"
    if REWARDS_OFFER.search(main_item):
        return "other"

    store = (store or "").casefold()
    if (SWITCH_2.search(category) or PC_GAME.search(category) or store in PC_GAME_STORES
        or (MAC_TAG.search(platform_title) and category.strip().casefold() == "video games")):
        return "games"
    if TECH.search(category) or TECH.search(main_item) or HARDWARE.search(category) or store in TECH_STORES:
        return "tech"
    return "other"


def complete_deal(deal, html, now):
    page = DealMarkup(html)
    try:
        published = datetime.fromisoformat(page.meta.get("schema-date-published", ""))
    except ValueError:
        return None
    if published.tzinfo is None or not now - WINDOW <= published <= now:
        return None
    image = urljoin(BASE, page.meta.get("og:image", ""))
    image_url = urlsplit(image)
    if (image_url.scheme != "https" or image_url.hostname not in
        {"slickdeals.net", "static.slickdealscdn.com", "www.slickdeals.net"}
        or not image_url.path.startswith("/attachment/")):
        image = None
    price = deal["price"]
    if not price and re.fullmatch(r"\d+(?:\.\d{1,2})?", page.meta.get("price", "")):
        price = f"${Decimal(page.meta['price']):,.2f}"
    return {
        **deal, "price": price, "store": page.store, "image": image,
        "posted_at": published.astimezone(timezone.utc).isoformat(),
        "category": classify(deal["title"], page.meta.get("primaryCategory", ""), page.store),
    }


def build_digest(now, fetch=get_html):
    candidates = {}
    with ThreadPoolExecutor(max_workers=len(SORTS)) as pool:
        for listing in pool.map(lambda sort: load_candidates(sort, fetch), SORTS):
            for deal in listing:
                previous = candidates.get(deal["id"])
                if not previous or deal["views"] > previous["views"]:
                    candidates[deal["id"]] = deal
    ranking = sorted(candidates.values(), key=lambda deal: (
        deal["score"], deal["votes"], deal["comments"], deal["views"], int(deal["id"]),
    ), reverse=True)
    counts = dict.fromkeys(("giftcards", "tech", "games", "other"), 0)
    top = []
    with ThreadPoolExecutor(max_workers=len(SORTS)) as pool:
        for offset in range(0, len(ranking), len(SORTS)):
            batch = ranking[offset:offset + len(SORTS)]
            for result in pool.map(lambda deal: complete_deal(deal, fetch(deal["link"]), now), batch):
                if result and counts[result["category"]] < MAX_PER_CATEGORY:
                    top.append(result)
                    counts[result["category"]] += 1
            if all(count == MAX_PER_CATEGORY for count in counts.values()):
                break
    if not top:
        raise ValueError("Only 0 eligible deals found")
    return {"generated_at": now.isoformat(), "deals": top}


def refresh(output, now, fetch=get_html):
    digest = build_digest(now, fetch)
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as temp:
        json.dump(digest, temp, ensure_ascii=False, indent=2)
        temp.write("\n")
    os.replace(temp.name, output)
    return digest


def main():
    parser = argparse.ArgumentParser(description="Refresh the Slickdeals Deal Digest.")
    parser.add_argument("--output", type=Path, default=Path("data/deals.json"))
    args = parser.parse_args()
    try:
        digest = refresh(args.output, datetime.now(timezone.utc))
    except (KeyError, OSError, TypeError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Deal refresh failed; previous data was not replaced: {error}\n")
    print(f"Wrote {len(digest['deals'])} deals to {args.output} at {digest['generated_at']}")


if __name__ == "__main__":
    main()
