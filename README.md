# Deal Digest

The five most popular deals in a rolling 24-hour window, drawn from the public Slickdeals Hot Deals forum. The mobile-first site shows the deal's price and store when available, its original posting time, net votes, views, comments, and ranking score.

## Run locally

Requires Python 3.8+ and curl. From the repository root:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/fetch_deals.py
python3 -m http.server 8000
```

Open http://localhost:8000.

Run the browser logic tests with Node.js 22+: `node --test tests/site.test.cjs`.

## Ranking and refresh

- Combine and deduplicate the first page of four public Hot Deals listings: highest rating, most views, most comments, and newest. This is a candidate sample, not a complete crawl of every Slickdeals forum.
- Score = net votes + 2 × comments + 3 × log₁₀(1 + views). Confirm the original posting time using the deal page, not its promotion time or the latest reply.
- The Pages workflow runs on main pushes, hourly at minute 17 UTC, and on demand. It publishes the generated snapshot as a Pages artifact without adding data commits. If the upstream refresh fails, the workflow does not replace the last successful deployment. The site stops showing deals older than 24 hours and notes when a refresh is delayed.
- Deal Digest can be installed from Android Chrome. After an online visit, it can reload offline and show still-current deals from the last saved snapshot. Product images and external links may need a connection.
- GitHub Pages uses Actions as its source. The published CNAME is `deals.junyahonda.com`; the DNS record is `deals` CNAME `junyahonda.github.io`.
