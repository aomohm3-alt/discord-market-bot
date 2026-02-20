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

# ---------- UI helpers ----------
def fmt_price(x: float) -> str:
    # ทำให้ดูเป็นมืออาชีพ: ตัวใหญ่แยก comma, ทศนิยม 2 ตำแหน่ง
    return f"{x:,.2f}"

def fmt_pct(x: float) -> str:
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.2f}%"

def diff_table(rows: list[tuple[str, float, float]], *, price_fmt=fmt_price) -> str:
    """
    Discord codeblock 'diff' => + (green) - (red)
    Format: [+/-] TICKER  PRICE  PCT
    """
    if not rows:
        return "```diff\n- no data\n```"

    # column widths
    sym_w = max(4, max(len(r[0]) for r in rows))
    price_w = max(8, max(len(price_fmt(r[1])) for r in rows))
    pct_w = 8

    lines = ["```diff"]
    for sym, price, chg in rows:
        sign = "+" if chg >= 0 else "-"
        lines.append(
            f"{sign} {sym:<{sym_w}}  {price_fmt(price):>{price_w}}  {fmt_pct(chg):>{pct_w}}"
        )
    lines.append("```")
    return "\n".join(lines)

def embed_field(name: str, value: str, inline: bool = False) -> dict:
    # Discord field value limit ~1024 chars; keep safe by truncating
    if len(value) > 1020:
        value = value[:1017] + "..."
    return {"name": name, "value": value, "inline": inline}

def pick_color(market_proxy: list[float]) -> int:
    # สี premium: เขียวถ้าภาพรวมบวก แดงถ้าลบ เทาถ้าใกล้ศูนย์
    avg = sum(market_proxy) / max(1, len(market_proxy))
    if avg > 0.05:
        return 0x2ECC71  # green
    if avg < -0.05:
        return 0xE74C3C  # red
    return 0x95A5A6      # gray

def post_embeds(embeds: list[dict]):
    payload = {"embeds": embeds}
    r = requests.post(WEBHOOK, json=payload, timeout=20)
    r.raise_for_status()

# ---------- Main ----------
def main():
    bkk = timezone(timedelta(hours=7))
    now_bkk = datetime.now(tz=bkk).strftime("%Y-%m-%d • %H:%M (BKK)")

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

    # Market proxy for color (ใช้ ETF + Mag7 เฉลี่ยเป็น mood ตลาด)
    proxy = [x["chg"] for x in etfs] + [x["chg"] for x in mag7]
    color = pick_color(proxy)

    # --- Build premium blocks ---
    mag7_block = diff_table([(x["label"], x["close"], x["chg"]) for x in mag7])
    etf_block = diff_table([(x["label"], x["close"], x["chg"]) for x in etfs])

    # Small cap: top 5 gainers & top 5 losers
    top5 = small[:5]
    bot5 = sorted(small[-5:], key=lambda x: x["chg"])  # most negative first
    gain_block = diff_table([(x["label"], x["close"], x["chg"]) for x in top5])
    lose_block = diff_table([(x["label"], x["close"], x["chg"]) for x in bot5])

    # Full small cap board
    full_small = diff_table([(x["label"], x["close"], x["chg"]) for x in small])

    crypto_block = diff_table(
        [(x["label"], x["close"], x["chg"]) for x in crypto],
        price_fmt=lambda v: f"{v:,.0f}"  # crypto ไม่ต้องทศนิยมเยอะ
    )

    gold_block = diff_table([("XAUUSD", xau["close"], xau_chg)])

    # ---------- Embed #1 (Dashboard) ----------
    embed1 = {
        "title": "📊 US MARKETS — PREMIUM DASHBOARD",
        "description": f"🕒 {now_bkk}\nStocks/ETF/XAU = Daily (Open→Close) • Crypto = 24h",
        "color": color,
        "fields": [
            embed_field("⭐ MAG 7 (sorted)", mag7_block, inline=False),
            embed_field("📈 ETF / Indices", etf_block, inline=False),
            embed_field("📌 Small Cap — Gainers (Top 5)", gain_block, inline=True),
            embed_field("📌 Small Cap — Losers (Bottom 5)", lose_block, inline=True),
            embed_field("🪙 Crypto (24h)", crypto_block, inline=False),
            embed_field("🥇 Gold", gold_block, inline=False),
        ],
        "footer": {"text": "Tip: + green / - red • Clean layout • Sorted by %"},
        "timestamp": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
    }

    # ---------- Embed #2 (Full small caps) ----------
    embed2 = {
        "title": "🧪 SMALL CAP — FULL BOARD (sorted by %)",
        "description": f"🕒 {now_bkk}",
        "color": 0x1F2A44,  # น้ำเงินเข้มดูหรู
        "fields": [
            embed_field("All Small Caps", full_small, inline=False),
        ],
        "footer": {"text": "Full list • Sorted by % change"},
        "timestamp": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
    }

    post_embeds([embed1, embed2])

if __name__ == "__main__":
    main()
