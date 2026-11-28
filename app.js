const list = document.querySelector("#deals");
const status = document.querySelector("#status");
const updated = document.querySelector("#updated");
const template = document.querySelector("#deal-template");
const categoryButtons = document.querySelectorAll(".category-filters button");
const categories = new Map([
  ["giftcards", "Gift cards"], ["tech", "Tech"], ["games", "Switch 2 & PC games"], ["other", "Others"],
]);
const fullDate = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium", timeStyle: "short",
});
const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "always", style: "short" });
const numbers = new Intl.NumberFormat();
const signed = new Intl.NumberFormat(undefined, { signDisplay: "exceptZero" });
const hour = 60 * 60 * 1000;

function renderDeal(deal, position, now) {
  const card = template.content.cloneNode(true);
  const set = (selector, value) => {
    card.querySelector(selector).textContent = value;
  };
  const posted = card.querySelector(".posted");
  const hours = Math.floor((now - new Date(deal.posted_at)) / hour);
  posted.dateTime = deal.posted_at;
  posted.title = fullDate.format(new Date(deal.posted_at));
  posted.textContent = hours < 1 ? "Under 1 hr ago" : relative.format(-hours, "hour");
  set(".place", `#${position}`);
  set(".store", deal.store || "Slickdeals");
  set(".deal-title", deal.title);
  if (deal.price) set(".price", deal.price);
  else card.querySelector(".price").hidden = true;
  const category = card.querySelector(".deal-category");
  if (category && categories.has(deal.category)) {
    category.textContent = categories.get(deal.category);
    category.hidden = false;
  }
  set(".votes", signed.format(deal.votes));
  set(".views", numbers.format(deal.views));
  set(".comments", numbers.format(deal.comments));
  set(".score", numbers.format(deal.score));
  const link = card.querySelector(".deal-link");
  link.href = deal.link;
  const title = card.querySelector(".deal-title");
  title.id = `deal-title-${position}`;
  link.id = `deal-link-${position}`;
  link.setAttribute("aria-labelledby", `${link.id} ${title.id}`);
  if (deal.image) {
    const image = card.querySelector("img");
    image.addEventListener("load", () => {
      image.hidden = false;
      image.previousElementSibling.setAttribute("hidden", "");
    }, { once: true });
    image.src = deal.image;
  }
  return card;
}

function renderRanking(digest, category) {
  const now = Date.now();
  const recent = digest.deals.filter((deal) => {
    const age = now - new Date(deal.posted_at);
    return age >= 0 && age <= 24 * hour && (category === "all" || deal.category === category);
  }).slice(0, 5);
  list.replaceChildren(...recent.map((deal, i) => renderDeal(deal, i + 1, now)));
  const notices = [];
  if (!recent.length) {
    notices.push(category === "all"
      ? "No deals from the last 24 hours in the latest snapshot. Check back after the next refresh."
      : "No deals in this category from the last 24 hours.");
  } else if (category !== "all" && recent.length < 5) {
    notices.push(`Only ${recent.length} ${recent.length === 1 ? "deal" : "deals"} in this category from the last 24 hours.`);
  }
  if (recent.length && now - new Date(digest.generated_at) > 2 * hour) {
    notices.push("The hourly refresh is delayed. This is the last available ranking.");
  }
  status.textContent = notices.join(" ");
  status.hidden = !notices.length;
}

async function loadDeals() {
  try {
    const response = await fetch("./data/deals.json", { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const digest = await response.json();
    const generated = new Date(digest.generated_at);
    const time = document.createElement("time");
    time.dateTime = generated.toISOString();
    time.textContent = fullDate.format(generated);
    updated.replaceChildren("Updated ", time);
    renderRanking(digest, "all");
    for (const button of categoryButtons) {
      button.disabled = false;
      button.addEventListener("click", () => {
        for (const option of categoryButtons) {
          option.setAttribute("aria-pressed", String(option === button));
        }
        renderRanking(digest, button.dataset.category);
      });
    }
  } catch {
    status.textContent = "The deal ranking couldn’t load. Try refreshing this page.";
  }
}

loadDeals();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("./sw.js").catch((error) => {
    console.warn("Deal Digest offline mode is unavailable:", error);
  });
}
