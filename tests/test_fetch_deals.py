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
        self.assertEqual(classify("Dinnerware set", store="Amazon"), "kitchen")

    def test_platform_markers_quantities_and_hardware_bonuses(self):
        cases = {
            "games": (
                "Nintendo Switch 2 Console", "Switch 2 Carrying Case",
                "Mario Kart World (Nintendo Switch 2)", "DOOM (Steam)", "Hades II (PC)",
                "Myst (PC Digital Download)", "Humble PC game bundle", "Terraria PC code",
                "Free game at Epic Games", "The Witcher (GOG)", "Hades + Hades II (Steam)",
                "Game + DLC (Epic)", "Game + DLC (GOG)", "Game + DLC [PC]",
                "Game with DLC (PC Digital Download)", "Hades (Steam) + Free Hades II (Steam)",
                "Hades II PC + Free DLC (Steam)", "Game (Steam / Epic)", "Game (PC Digital)",
                "Game [Steam]", "Game [GOG]", "Game PC Digital Game Download", "Game via Battle.net",
                "Game PC Digital key", "Game (Mac / Steam)", "Game (Mac) from GOG", "Steam key for Hades II",
                "Switch 2 Console + Free Game Code", "Switch 2 Pro Controller",
                "2-Pack Screen Protectors for Nintendo Switch 2",
                "Nintendo Switch 2 - Pack of 2 Screen Protectors",
            ),
            "tech": (
                "Nintendo Switch OLED", "PS5 console", "Xbox Series X", "Steam Deck OLED",
                "Mario Kart 8 Deluxe (Switch)", "Forza Horizon Xbox game code",
                "Nintendo Switch 2-Pack Screen Protectors (Switch OLED)",
                "Nintendo Switch 2‑pack Screen Protectors (Switch OLED)",
                "Nintendo Switch 2pk Screen Protectors (Switch OLED)",
                "Nintendo Switch 2 pk Screen Protectors (Switch OLED)",
                "Nintendo Switch 2 count Screen Protectors (Switch OLED)",
                "Switch 2 Pack", "Switch 2-Count", "Switch 2-Pack", "Switch 2pk",
                "Switch 2 pcs", "Switch 2-Piece Accessory Set",
                "RTX 5070 GPU + Free Game Code (Steam)", "Ryzen 7 CPU with bonus game (GOG)",
                "HP laptop w/game code (Epic)", "Gaming PC includes a free game (Steam)",
                "27-inch monitor + game (PC Digital)", "Beelink [Mini PC]",
                "Lenovo ThinkCentre (Desktop PC)", "SSD + bonus game (Steam / Epic)",
                "Mini PC Digital Signage Player", "Microsoft Office 2021 (Mac)",
                "Windows 11 Pro", "Antivirus subscription (Mac)", "VPN annual plan (Mac)",
            ),
            "giftcards": ("$50 Steam gift card",),
            "other": ("Steam mop",),
        }
        for expected, titles in cases.items():
            for title in titles:
                with self.subTest(title=title):
                    self.assertEqual(classify(title), expected)
        self.assertEqual(classify("Hades II", "PC Games"), "games")
        self.assertEqual(classify("Surprise game", store="GOG.com"), "games")
        self.assertEqual(classify("Myst (Mac)", "Video Games"), "games")
        self.assertEqual(classify("Myst (Mac)"), "other")

    def test_mixed_games_follow_the_leading_platform(self):
        cases = (
            ("Video Games: Final Fantasy VII Rebirth (PS5) $12.88, Rise of the Ronin (PS5) $17.50, "
             "Yakuza 0 (Switch 2) $21.16 + More w/ Free S/H @ eBay", "tech"),
            ("Yakuza 0 (Switch 2) and Final Fantasy VII Rebirth (PS5)", "games"),
            ("Forza (Xbox), Hades (Steam)", "tech"),
            ("Hades (Steam), Forza (Xbox)", "games"),
            ("Game [PC / PS5]", "games"),
            ("Game [PC / PS5 / Switch 2]", "games"),
            ("Game [PS5 / PC / Switch 2]", "tech"),
            ("Game [PS5 / PC]", "tech"),
            ("Mario Kart 8 (Nintendo Switch), Mario Kart World (Switch 2)", "tech"),
        )
        for title, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(classify(title, "Video Games", "eBay"), expected)

    def test_rewards_offers_and_power_accessories(self):
        cases = (
            ("18% cashback WALMART today only from CapitalOneOffers", "Tech & Electronics",
             "Capital One Offers", "other"),
            ("Baseus Qi2 Certified 15W Wireless Magnetic Power Bank 10000mAh with USB-C Cable "
             "22.5W PD Charging $19.79 + Free Shipping w/ Prime or orders $35+", "Chargers & Power Banks",
             "Amazon", "tech"),
            ("15% credit card rewards at Lenovo", "Electronics", "Lenovo", "other"),
            ("USB-C charger", "", None, "tech"),
            ("Portable batteries", "", None, "tech"),
            ("25% cash back on an OLED laptop", "", None, "tech"),
        )
        for title, category, store, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(classify(title, category, store), expected)

    def test_classifies_beauty_wellness_and_kitchen_by_product_or_metadata(self):
        cases = (
            ("Vitamin C Face Serum", "Health & Wellness", None, "beauty"),
            ("Waterproof Mascara", "", None, "beauty"),
            ("Moisturizing Shampoo with Coconut Oil", "", None, "beauty"),
            ("Eau de Parfum Spray", "Fragrances", None, "beauty"),
            ("Daily Essentials Set", "Beauty & Personal Care", None, "beauty"),
            ("Rechargeable Beard Trimmer", "Electronics", None, "beauty"),
            ("Biotin Multivitamins for Hair, Skin, and Nails", "Beauty", None, "wellness"),
            ("Premier Protein 30g Protein Shakes", "", None, "wellness"),
            ("Adjustable Dumbbells", "", None, "wellness"),
            ("Electric Toothbrush", "Personal Care", None, "wellness"),
            ("Blood Pressure Monitor", "Electronics", None, "wellness"),
            ("Weighted Blanket", "", None, "wellness"),
            ("Trail Shelter", "Sports & Outdoors", None, "wellness"),
            ("Camping Tent", "", None, "wellness"),
            ("20,000mAh USB-C Power Bank for Camping", "Sports & Outdoors", None, "tech"),
            ("Digital Air Fryer", "Electronics", "Newegg", "kitchen"),
            ("Ninja Countertop Blender", "Electronics", None, "kitchen"),
            ("Programmable Coffee Maker", "", None, "kitchen"),
            ("Stainless Steel Cookware Set", "", None, "kitchen"),
            ("8-inch Chef's Knife", "", None, "kitchen"),
            ("8-inch Chef Knife", "", None, "kitchen"),
            ("Countertop Microwave Oven", "Electronics", None, "kitchen"),
            ("Glass Food Storage Containers", "", None, "kitchen"),
            ("12-piece Stainless Steel Set", "Kitchen Utensils", None, "kitchen"),
            ("Gift Card for a Blender", "Kitchen", None, "giftcards"),
            ("Laptop with free blender", "Computers", None, "tech"),
            ("Dish Spray Bundle", "Kitchen & Bathroom Cleaning Supplies", None, "other"),
            ("Countertop Water Bottle", "", None, "other"),
        )
        for title, category, store, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(classify(title, category, store), expected)

    def test_keeps_ranked_category_alternates_below_the_overall_top_fifteen(self):
        def listings(url):
            if urlsplit(url).query:
                return ("".join(row(n, 200 - n) for n in range(20, 40))
                        + "".join(row(n, 200 - n, title="Nintendo e-gift card") for n in range(40, 46))
                        + "".join(row(n, 200 - n, title="OLED laptop") for n in range(46, 52))
                        + "".join(row(n, 200 - n, title="Switch 2 console") for n in range(52, 58))
                        + "".join(row(n, 200 - n, title="Shampoo") for n in range(58, 64))
                        + "".join(row(n, 200 - n, title="Yoga mat") for n in range(64, 70))
                        + "".join(row(n, 200 - n, title="Air fryer") for n in range(70, 76)))
            return fixture(url)

        deals = build_digest(NOW, listings)["deals"]
        self.assertEqual([deal["id"] for deal in deals], [str(n) for n in (
            *range(20, 35), *range(40, 76))])
        self.assertEqual([deal["category"] for deal in deals],
                         ["other"] * 15 + [
                             group for group in ("giftcards", "tech", "games", "beauty", "wellness", "kitchen")
                             for _ in range(6)
                         ])

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
