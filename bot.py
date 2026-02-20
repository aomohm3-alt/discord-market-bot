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


# ---------- Terminal formatting ----------
def fmt_price(x: float) -> str:
    return f"{x:,.2f}"

def fmt_pct(x: float) -> str:
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.2f}%"

def diff_table(rows: list[tuple[str, float, float, str]]):
    """
    rows: [(symbol, price, pct, note)]
    Uses 'diff' to color +/-.
    """
    if not rows:
        return "```diff\n- no data\n```"

    sym_w = max(3, max(len(r[0]) for r in rows))
    price_w = max(8, max(len(fmt_price(r[1])) for r in rows))
    pct_w = 8

    lines = ["```diff"]
    for sym, price, chg, note in rows:
        sign = "+" if chg >= 0 else "-"
        note_txt = f"   {note}" if note else ""
        lines.append(f"{sign} {sym:<{sym_w}}  {fmt_price(price):>{price_w}}  {fmt_pct(chg):>{pct_w}}{note_txt}")
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


# ---------- Market pulse ----------
def market_pulse(core_changes: list[float]):
    if not core_changes:
        return ("NEUTRAL", 0, 0, 0.0)
    pos = sum(1 for x in core_changes if x >= 0)
    neg = sum(1 for x in core_changes if x < 0)
    heat = sum(core_changes) / len(core_changes)
    risk = "ON" if heat > 0.05 else ("OFF" if heat < -0.05 else "NEUTRAL")
    return (risk, pos, neg, heat)


def main():
    bkk = timezone(timedelta(hours=7))
    now_bkk = datetime.now(tz=bkk).strftime("%Y-%m-%d %H:%M (BKK)")

    mag7 = fetch_bucket(MAG7)
    etfs = fetch_bucket(ETFS)
    small = fetch_bucket(SMALL_CAPS)

    # XAU
    xau = stooq_last_bar("xauusd")
    xau_chg = pct_change(xau["open"], xau["close"])

    # Crypto
    cg = cg_prices_with_change(CRYPTO_IDS)
    crypto = []
    for cid in CRYPTO_IDS:
        px = float(cg[cid]["usd"])
        chg = float(cg[cid].get("usd_24h_change", 0.0))
        crypto.append({"label": CRYPTO_MAP.get(cid, cid).upper(), "close": px, "chg": chg})
    crypto.sort(key=lambda x: x["chg"], reverse=True)

    # Pulse from core (MAG7 + ETFs)
    core_changes = [x["chg"] for x in etfs] + [x["chg"] for x in mag7]
    risk, pos, neg, heat = market_pulse(core_changes)

    # Notes: tag heat movers
    def note_for(chg: float):
        if chg >= 5:
            return "(HF-HEAT)"
        if chg <= -5:
            return "(RISK)"
        return ""

    # Build blocks
    core_rows = []
    for x in etfs:
        core_rows.append((x["label"], x["close"], x["chg"], ""))
    for x in mag7:
        core_rows.append((x["label"], x["close"], x["chg"], ""))

    # Small movers
    top5 = small[:5]
    bot5 = sorted(small[-5:], key=lambda x: x["chg"])  # most negative first
    mover_rows = [(x["label"], x["close"], x["chg"], note_for(x["chg"])) for x in top5] + \
                 [(x["label"], x["close"], x["chg"], note_for(x["chg"])) for x in bot5]

    macro_rows = [
        ("XAUUSD", xau["close"], xau_chg, ""),
        ("BTC", crypto[0]["close"], crypto[0]["chg"], "") if crypto else ("BTC", 0.0, 0.0, ""),
        ("ETH", crypto[1]["close"], crypto[1]["chg"], "") if len(crypto) > 1 else ("ETH", 0.0, 0.0, ""),
    ]

    embed1 = {
        "title": "HF TERMINAL — MARKET PULSE",
        "description": f"`{now_bkk}`  •  `Cycle: 30m`\n**RISK**: `{risk}`  |  **BREADTH**: `+{pos} / -{neg}`  |  **HEAT**: `{heat:+.2f}%`",
        "color": 0x111827,  # dark navy
        "fields": [
            embed_field("CORE (MAG7 + INDEX)", diff_table(core_rows), inline=False),
            embed_field("SMALL CAP — MOVERS (TOP / BOTTOM)", diff_table(mover_rows), inline=False),
            embed_field("MACRO (XAU / CRYPTO)", diff_table(macro_rows), inline=False),
        ],
        "footer": {"text": "HF style • diff = green/red • sorted by % where applicable"},
        "timestamp": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
    }

    # Full small cap tape (sorted)
    full_rows = [(x["label"], x["close"], x["chg"], "") for x in small]
    embed2 = {
        "title": "HF BOOK — SMALL CAPS (FULL TAPE)",
        "description": f"`{now_bkk}`  •  `Sorted by % (Open→Close)`",
        "color": 0x0B1220,  # deeper dark
        "fields": [
            embed_field("TAPE", diff_table(full_rows), inline=False),
        ],
        "footer": {"text": "Full list • sorted by % change"},
        "timestamp": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
    }

    post_embeds([embed1, embed2])


if __name__ == "__main__":
    main()
