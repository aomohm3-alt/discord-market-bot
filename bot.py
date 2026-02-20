import os
import requests
from datetime import datetime, timezone, timedelta

WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]

MAG7 = {
    "AAPL.US": "AAPL",
    "MSFT.US": "MSFT",
    "AMZN.US": "AMZN",
    "GOOGL.US": "GOOGL",
    "META.US": "META",
    "NVDA.US": "NVDA",
    "TSLA.US": "TSLA",
}

ETFS = {
    "VOO.US": "VOO (S&P500)",
    "QQQ.US": "QQQ (Nasdaq-100)",
}

SMALL_CAPS = {
    "IREN.US": "IREN",
    "BTDR.US": "BTDR",
    "RKLB.US": "RKLB",
    "INTC.US": "INTC",
    "EOSE.US": "EOSE",
    "ACHR.US": "ACHR",
    "BBAI.US": "BBAI",
    "TMC.US": "TMC",
    "INDI.US": "INDI",
    "AEHR.US": "AEHR",
    "NVTS.US": "NVTS",
    "RR.US": "RR",
    "SLDP.US": "SLDP",
    "ASTS.US": "ASTS",
}

CRYPTO_IDS = ["bitcoin", "ethereum"]
CRYPTO_MAP = {"bitcoin": "BTC", "ethereum": "ETH"}


def stooq_last_bar(symbol: str):
    url = f"https://stooq.com/q/d/l/?s={symbol.lower()}&i=d"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    lines = [x.strip() for x in r.text.splitlines() if x.strip()]
    last = lines[-1].split(",")
    return {
        "date": last[0],
        "open": float(last[1]),
        "close": float(last[4]),
    }


def cg_prices_with_change(ids, vs="usd"):
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": ",".join(ids),
        "vs_currencies": vs,
        "include_24hr_change": "true",
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def pct_change(open_px, close_px):
    return 0 if open_px == 0 else (close_px - open_px) / open_px * 100


def fmt_pct(x):
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.2f}%"


def badge(x):
    if x >= 5:
        return "🔥"
    if x <= -5:
        return "🚨"
    return "🟢" if x >= 0 else "🔴"


def fetch_bucket(mapping):
    data = []
    for sym, label in mapping.items():
        d = stooq_last_bar(sym)
        chg = pct_change(d["open"], d["close"])
        data.append({"label": label, "close": d["close"], "chg": chg, "date": d["date"]})
    data.sort(key=lambda x: x["chg"], reverse=True)
    return data


def post_embeds(embeds):
    payload = {"embeds": embeds}
    r = requests.post(WEBHOOK, json=payload, timeout=20)
    r.raise_for_status()


def main():
    bkk = timezone(timedelta(hours=7))
    now = datetime.now(tz=bkk).strftime("%Y-%m-%d • %H:%M (BKK)")

    mag7 = fetch_bucket(MAG7)
    etfs = fetch_bucket(ETFS)
    small = fetch_bucket(SMALL_CAPS)

    xau = stooq_last_bar("xauusd")
    xau_chg = pct_change(xau["open"], xau["close"])

    cg = cg_prices_with_change(CRYPTO_IDS)
    crypto = []
    for cid in CRYPTO_IDS:
        px = cg[cid]["usd"]
        chg = cg[cid]["usd_24h_change"]
        crypto.append({"label": CRYPTO_MAP[cid], "close": px, "chg": chg})
    crypto.sort(key=lambda x: x["chg"], reverse=True)

    # -------- DASHBOARD EMBED --------
    dash_lines = []

    dash_lines.append("⭐ **MAG 7**")
    for x in mag7:
        dash_lines.append(f"{badge(x['chg'])} {x['label']} {x['close']:.2f} ({fmt_pct(x['chg'])})")

    dash_lines.append("\n📊 **ETF / INDICES**")
    for x in etfs:
        dash_lines.append(f"{badge(x['chg'])} {x['label']} {x['close']:.2f} ({fmt_pct(x['chg'])})")

    dash_lines.append("\n🧪 **SMALL CAP – TOP 5 / BOTTOM 5**")
    top5 = small[:5]
    bot5 = list(reversed(small[-5:]))

    for x in top5:
        dash_lines.append(f"{badge(x['chg'])} {x['label']} {x['close']:.2f} ({fmt_pct(x['chg'])})")

    dash_lines.append("—")

    for x in bot5:
        dash_lines.append(f"{badge(x['chg'])} {x['label']} {x['close']:.2f} ({fmt_pct(x['chg'])})")

    dash_lines.append("\n🪙 **CRYPTO (24h)**")
    for x in crypto:
        dash_lines.append(f"{badge(x['chg'])} {x['label']} {x['close']:,.0f} ({fmt_pct(x['chg'])})")

    dash_lines.append("\n🥇 **GOLD**")
    dash_lines.append(f"{badge(xau_chg)} XAUUSD {xau['close']:.2f} ({fmt_pct(xau_chg)})")

    embed1 = {
        "title": "📊 US MARKETS DASHBOARD",
        "description": f"🕒 {now}",
        "color": 3447003,
        "fields": [{
            "name": "Market Overview",
            "value": "\n".join(dash_lines)[:4000],
            "inline": False
        }],
    }

    # -------- FULL SMALL CAP EMBED --------
    full_lines = []
    for x in small:
        full_lines.append(f"{badge(x['chg'])} {x['label']} {x['close']:.2f} ({fmt_pct(x['chg'])})")

    embed2 = {
        "title": "🧪 SMALL CAP — FULL BOARD",
        "description": f"🕒 {now}",
        "color": 15844367,
        "fields": [{
            "name": "All Small Caps (Sorted by %)",
            "value": "\n".join(full_lines)[:4000],
            "inline": False
        }],
    }

    post_embeds([embed1, embed2])


if __name__ == "__main__":
    main()
