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
LIMIT = 5
WINDOW = timedelta(hours=24)


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


def complete_deal(deal, html, now):
    page = DealMarkup(html)
    published = datetime.fromisoformat(page.meta["schema-date-published"])
    if not now - WINDOW <= published <= now:
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
    top = []
    for deal in ranking:
        if result := complete_deal(deal, fetch(deal["link"]), now):
            top.append(result)
            if len(top) == LIMIT:
                return {"generated_at": now.isoformat(), "deals": top}
    raise ValueError(f"Only {len(top)} eligible deals found; expected {LIMIT}")


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
