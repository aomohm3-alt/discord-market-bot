import os
import requests
from datetime import datetime, timezone, timedelta, time
from zoneinfo import ZoneInfo

WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]

# ---- Assets ----
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
    "VOO.US": "VOO",
    "QQQ.US": "QQQ",
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

# ---------- Market schedule ----------
def us_market_mode_now():
    """
    Mon–Fri: MARKET_OPEN only during 09:30–16:00 America/New_York
    Sat–Sun: WEEKEND_CRYPTO
    Else: MARKET_CLOSED
    """
    now_et = datetime.now(tz=ZoneInfo("America/New_York"))
    wd = now_et.weekday()  # Mon=0 ... Sun=6

    if wd >= 5:
        return "WEEKEND_CRYPTO", now_et

    open_t = time(9, 30)
    close_t = time(16, 0)
    if open_t <= now_et.time() <= close_t:
        return "MARKET_OPEN", now_et

    return "MARKET_CLOSED", now_et


# ---------- Data ----------
def stooq_last_bar(symbol: str):
    url = f"https://stooq.com/q/d/l/?s={symbol.lower()}&i=d"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    lines = [x.strip() for x in r.text.splitlines() if x.strip()]
    if len(lines) < 2:
        raise RuntimeError(f"No data for {symbol}")
    last = lines[-1].split(",")  # Date,Open,High,Low,Close,Volume
    return {"date": last[0], "open": float(last[1]), "close": float(last[4])}

def cg_prices_with_change(ids, vs="usd"):
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": ",".join(ids), "vs_currencies": vs, "include_24hr_change": "true"}
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def pct_change(open_px: float, close_px: float) -> float:
    return 0.0 if open_px == 0 else (close_px - open_px) / open_px * 100.0

def fetch_bucket(mapping: dict[str, str]):
    out = []
    for sym, label in mapping.items():
        d = stooq_last_bar(sym)
        chg = pct_change(d["open"], d["close"])
        out.append({"label": label, "close": d["close"], "chg": chg, "date": d["date"]})
    out.sort(key=lambda x: x["chg"], reverse=True)
    return out


# ---------- Terminal UI ----------
def fmt_price(x: float) -> str:
    return f"{x:,.2f}"

def fmt_pct(x: float) -> str:
    return f"{x:+.2f}%"

def tag(chg: float) -> str:
    if chg >= 7:
        return "[HOT]"
    if chg >= 4:
        return "[HEAT]"
    if chg <= -7:
        return "[RISK]"
    if chg <= -4:
        return "[DRAW]"
    return ""

def diff_table_rows(rows, price_fmt=fmt_price, with_tag=False):
    """
    rows: list of dicts with keys label, close, chg
    """
    if not rows:
        return "```diff\n- no data\n```"

    sym_w = max(3, max(len(r["label"]) for r in rows))
    price_w = max(8, max(len(price_fmt(r["close"])) for r in rows))
    pct_w = 8

    lines = ["```diff"]
    for r in rows:
        chg = r["chg"]
        sign = "+" if chg >= 0 else "-"
        extra = f"  {tag(chg)}" if with_tag and tag(chg) else ""
        lines.append(
            f"{sign} {r['label']:<{sym_w}}  {price_fmt(r['close']):>{price_w}}  {fmt_pct(chg):>{pct_w}}{extra}"
        )
    lines.append("```")
    return "\n".join(lines)

def diff_table_tuple(rows, price_fmt=fmt_price):
    """
    rows: list of tuples (label, close, chg)
    """
    if not rows:
        return "```diff\n- no data\n```"

    sym_w = max(3, max(len(r[0]) for r in rows))
    price_w = max(8, max(len(price_fmt(r[1])) for r in rows))
    pct_w = 8

    lines = ["```diff"]
    for label, close, chg in rows:
        sign = "+" if chg >= 0 else "-"
        lines.append(f"{sign} {label:<{sym_w}}  {price_fmt(close):>{price_w}}  {fmt_pct(chg):>{pct_w}}")
    lines.append("```")
    return "\n".join(lines)

def embed_field(name: str, value: str, inline: bool = False) -> dict:
    if len(value) > 1020:
        value = value[:1017] + "..."
    return {"name": name, "value": value, "inline": inline}

def post_embeds(embeds: list[dict]):
    payload = {"embeds": embeds}
    r = requests.post(WEBHOOK, json=payload, timeout=20)
    r.raise_for_status()

def pulse(changes):
    if not changes:
        return ("NEUTRAL", 0, 0, 0.0)
    pos = sum(1 for x in changes if x >= 0)
    neg = len(changes) - pos
    heat = sum(changes) / len(changes)
    state = "ON" if heat > 0.05 else ("OFF" if heat < -0.05 else "NEUTRAL")
    return (state, pos, neg, heat)


# ---------- Main ----------
def main():
    mode, now_et = us_market_mode_now()

    # Market closed on weekdays => do nothing
    if mode == "MARKET_CLOSED":
        return

    bkk = timezone(timedelta(hours=7))
    now_bkk = datetime.now(tz=bkk).strftime("%Y-%m-%d %H:%M (BKK)")
    now_et_str = now_et.strftime("%Y-%m-%d %H:%M (ET)")

    # Weekend => Crypto only
    if mode == "WEEKEND_CRYPTO":
        cg = cg_prices_with_change(CRYPTO_IDS)
        crypto = []
        for cid in CRYPTO_IDS:
            px = float(cg[cid]["usd"])
            chg = float(cg[cid].get("usd_24h_change", 0.0))
            crypto.append({"label": CRYPTO_MAP.get(cid, cid).upper(), "close": px, "chg": chg})
        crypto.sort(key=lambda x: x["chg"], reverse=True)

        crypto_block = diff_table_rows(
            crypto,
            price_fmt=lambda v: f"{v:,.0f}",
            with_tag=True
        )

        embed = {
            "title": "Market Bot — CRYPTO WEEKEND FEED",
            "description": f"`{now_bkk}`  •  `{now_et_str}`  •  `Weekend Mode`",
            "color": 0x0B1220,
            "fields": [
                embed_field("CRYPTO (24h)", crypto_block, inline=False),
            ],
            "footer": {"text": "Weekend: Crypto only • Stocks/ETF paused"},
            "timestamp": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        }
        post_embeds([embed])
        return

    # MARKET_OPEN => Full set
    mag7 = fetch_bucket(MAG7)
    etfs = fetch_bucket(ETFS)
    small = fetch_bucket(SMALL_CAPS)

    # XAU
    xau = stooq_last_bar("xauusd")
    xau_chg = pct_change(xau["open"], xau["close"])
    xau_row = [("XAUUSD", xau["close"], xau_chg)]

    # Crypto (still show as macro)
    cg = cg_prices_with_change(CRYPTO_IDS)
    crypto = []
    for cid in CRYPTO_IDS:
        px = float(cg[cid]["usd"])
        chg = float(cg[cid].get("usd_24h_change", 0.0))
        crypto.append({"label": CRYPTO_MAP.get(cid, cid).upper(), "close": px, "chg": chg})
    crypto.sort(key=lambda x: x["chg"], reverse=True)

    # Pulse from ETF + MAG7
    core_changes = [x["chg"] for x in etfs] + [x["chg"] for x in mag7]
    risk, pos, neg, heat = pulse(core_changes)

    # Small cap movers
    top5 = small[:5]
    bot5 = sorted(small[-5:], key=lambda x: x["chg"])  # most negative first

    # Tables
    core_table = diff_table_rows(etfs + mag7, with_tag=True)
    gain_table = diff_table_rows(top5, with_tag=True)
    lose_table = diff_table_rows(bot5, with_tag=True)

    macro_table = diff_table_tuple(
        xau_row + [(c["label"], c["close"], c["chg"]) for c in crypto],
        price_fmt=lambda v: f"{v:,.0f}" if v >= 1000 else f"{v:,.2f}"
    )

    full_small_table = diff_table_rows(small, with_tag=False)

    embed1 = {
        "title": "Market Bot — HF TERMINAL (US OPEN)",
        "description": f"`{now_bkk}`  •  `{now_et_str}`  •  `Cycle: 30m`\n"
                       f"**RISK** `{risk}`  |  **BREADTH** `+{pos}/-{neg}`  |  **HEAT** `{heat:+.2f}%`",
        "color": 0x0B1220,
        "fields": [
            embed_field("CORE (QQQ/VOO + MAG7)", core_table, inline=False),
            embed_field("SMALL CAP — GAINERS (Top 5)", gain_table, inline=True),
            embed_field("SMALL CAP — LOSERS (Bottom 5)", lose_table, inline=True),
            embed_field("MACRO (XAU / CRYPTO)", macro_table, inline=False),
        ],
        "footer": {"text": "Diff colors: + green / - red • Tags: HOT/HEAT/DRAW/RISK"},
        "timestamp": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
    }

    embed2 = {
        "title": "Market Bot — SMALL CAPS (FULL TAPE)",
        "description": f"`{now_bkk}`  •  `{now_et_str}`  •  `Sorted by % (Daily)`",
        "color": 0x111827,
        "fields": [
            embed_field("TAPE", full_small_table, inline=False),
        ],
        "footer": {"text": "Full list • Sorted by % change"},
        "timestamp": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
    }

    post_embeds([embed1, embed2])


if __name__ == "__main__":
    main()
