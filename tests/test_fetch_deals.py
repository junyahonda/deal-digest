from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import parse_qs, urlsplit

from scripts.fetch_deals import SORTS, build_digest, classify, refresh


NOW = datetime(2026, 11, 25, 20, tzinfo=timezone.utc)


def row(number, votes, views=100, comments=2, price="", title="Deal &amp;"):
    return f"""
      <tr id="sdpostrow_{number}0">
        <td><a data-thread-id="{number}" href="/f/{number}-deal"
          data-final-price="{price}">{title} <strong>extras {number}</strong></a>
          <img alt="Votes: 3 Score: {votes}">
        </td>
        <td title="Replies: {comments:,}, Views: {views:,}">Comment info</td>
      </tr>
    """


def fixture(url):
    parts = urlsplit(url)
    if parts.query:
        sort = parse_qs(parts.query)["sort"][0]
        if sort == "dateline":
            return row(10, 20, views=550, comments=20) + row(14, 20, comments=17)
        return (row(99, 200) + row(98, 199) + row(10, 20) + row(11, 40)
                + row(12, 38, views=9_500) + row(13, 36, price="$9.95") + row(15, 1))
    number = int(parts.path.split("/")[-1].split("-")[0])
    posted = {
        99: NOW - timedelta(hours=24, seconds=1),
        98: NOW + timedelta(seconds=1),
        13: NOW - timedelta(hours=24),
    }.get(number, NOW - timedelta(hours=5))
    return f"""
      <meta name="schema-date-published" content="{posted.isoformat()}">
      <meta property="og:image" content="https://slickdeals.net/attachment/deal.thumb">
      <meta name="price" content="11">
      <a data-storename="Example Store">Store</a>
      <img alt>
    """


class FetchDealsTest(unittest.TestCase):
    def test_classifies_titles_store_and_slickdeals_primary_category(self):
        self.assertEqual(classify("Apple eGift Card", "Electronics", "Apple"), "giftcards")
        self.assertEqual(classify("$50 dining credit", "Gift Cards"), "giftcards")
        self.assertEqual(classify("Laptop with $50 gift card"), "tech")
        self.assertEqual(classify("Winter boots + $50 gift card"), "other")
        self.assertEqual(classify("C27G4X", "Monitors"), "tech")
        self.assertEqual(classify("G50VT", store="Micro Center"), "tech")
        self.assertEqual(classify("Dinnerware set", store="Amazon"), "other")

    def test_classifies_switch_2_and_pc_games_but_not_other_consoles_or_steam_hardware(self):
        for title in ("Nintendo Switch 2 Console", "Switch 2 Carrying Case",
                      "Mario Kart World (Nintendo Switch 2)", "DOOM (Steam)", "Hades II (PC)",
                      "Myst (PC Digital Download)", "Humble PC game bundle", "Terraria PC code",
                      "Free game at Epic Games", "The Witcher (GOG)"):
            with self.subTest(title=title):
                self.assertEqual(classify(title, "Video Games"), "games")
        self.assertEqual(classify("Hades II", "PC Games"), "games")
        self.assertEqual(classify("Surprise game", store="GOG.com"), "games")
        self.assertEqual(classify("$50 Steam gift card"), "giftcards")
        for title in ("Nintendo Switch OLED", "PS5 console", "Xbox Series X", "Steam Deck OLED"):
            self.assertEqual(classify(title), "tech")
        self.assertEqual(classify("Steam mop"), "other")

    def test_detects_pc_storefronts_and_platform_tags_after_bundle_separators(self):
        for title in ("Hades + Hades II (Steam)", "Game + DLC (Epic)", "Game + DLC (GOG)",
                      "Game + DLC [PC]", "Game with DLC (PC Digital Download)"):
            with self.subTest(title=title):
                self.assertEqual(classify(title, "Video Games"), "games")

    def test_switch_pack_quantities_do_not_match_the_switch_2_platform(self):
        for quantity in ("2-Pack", "2‑pack", "2pk", "2 pk", "2 count"):
            with self.subTest(quantity=quantity):
                title = f"Nintendo Switch {quantity} Screen Protectors (Switch OLED)"
                self.assertEqual(classify(title), "tech")
        self.assertEqual(classify("2-Pack Screen Protectors for Nintendo Switch 2"), "games")

    def test_free_pc_games_do_not_reclassify_hardware(self):
        for title in ("RTX 5070 GPU + Free Game Code (Steam)", "Ryzen 7 CPU with bonus game (GOG)",
                      "HP laptop w/game code (Epic)", "Gaming PC includes a free game (Steam)",
                      "27-inch monitor + game (PC Digital)"):
            with self.subTest(title=title):
                self.assertEqual(classify(title), "tech")
        self.assertEqual(classify("Switch 2 Console + Free Game Code"), "games")
        self.assertEqual(classify("Hades (Steam) + Free Hades II (Steam)"), "games")

    def test_keeps_ranked_category_alternates_below_the_overall_top_fifteen(self):
        def listings(url):
            if urlsplit(url).query:
                return ("".join(row(n, 200 - n) for n in range(20, 40))
                        + "".join(row(n, 200 - n, title="Nintendo e-gift card") for n in range(40, 46))
                        + "".join(row(n, 200 - n, title="OLED laptop") for n in range(46, 52))
                        + "".join(row(n, 200 - n, title="Switch 2 console") for n in range(52, 58)))
            return fixture(url)

        deals = build_digest(NOW, listings)["deals"]
        self.assertEqual([deal["id"] for deal in deals], [str(n) for n in (
            *range(20, 35), *range(40, 58))])
        self.assertEqual([deal["category"] for deal in deals],
                         ["other"] * 15 + ["giftcards"] * 6 + ["tech"] * 6 + ["games"] * 6)

    def test_ranks_deduplicated_deals_using_all_three_metrics_and_true_post_time(self):
        result = build_digest(NOW, fixture)
        self.assertEqual(result["generated_at"], NOW.isoformat())
        self.assertEqual([deal["id"] for deal in result["deals"]], ["10", "14", "12", "11", "13", "15"])
        first = result["deals"][0]
        self.assertEqual(first["title"], "Deal & extras 10")
        self.assertEqual(first["votes"], 20)
        self.assertEqual(first["views"], 550)
        self.assertEqual(first["comments"], 20)
        self.assertEqual(first["store"], "Example Store")
        self.assertEqual(first["price"], "$11.00")
        self.assertEqual(first["image"], "https://slickdeals.net/attachment/deal.thumb")
        self.assertEqual(result["deals"][4]["price"], "$9.95")

    def test_refresh_keeps_previous_snapshot_on_incomplete_source(self):
        def broken(url):
            if f"sort={SORTS[0]}" in url:
                return "<html>Upstream error</html>"
            return fixture(url)

        with TemporaryDirectory() as temp:
            output = Path(temp) / "deals.json"
            output.write_text("last good snapshot")
            with self.assertRaisesRegex(ValueError, "No readable deal rows"):
                refresh(output, NOW, broken)
            self.assertEqual(output.read_text(), "last good snapshot")

    def test_refresh_skips_unusable_timestamps_and_publishes_a_short_ranking(self):
        def listings(url):
            parts = urlsplit(url)
            if parts.query:
                return "".join(row(n, 30 - n) for n in range(20, 24))
            if parts.path.startswith("/f/21-"):
                return "<meta name='price' content='11'>"
            if parts.path.startswith("/f/22-"):
                return "<meta name='schema-date-published' content='not a timestamp'>"
            return fixture(url)

        with TemporaryDirectory() as temp:
            output = Path(temp) / "deals.json"
            result = refresh(output, NOW, listings)
            self.assertEqual([deal["id"] for deal in result["deals"]], ["20", "23"])
            self.assertTrue(output.is_file())

    def test_refresh_keeps_previous_snapshot_if_not_enough_recent_deals(self):
        with TemporaryDirectory() as temp:
            output = Path(temp) / "deals.json"
            output.write_text("last good snapshot")
            with self.assertRaisesRegex(ValueError, "Only 0 eligible deals"):
                refresh(output, NOW + timedelta(hours=48), fixture)
            self.assertEqual(output.read_text(), "last good snapshot")
