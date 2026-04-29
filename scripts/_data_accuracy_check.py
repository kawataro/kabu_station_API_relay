"""Deep data-accuracy check (one-off, runs against live relay + DB).
Run via:  .venv/Scripts/python.exe scripts/_data_accuracy_check.py
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime
from statistics import median

import requests

SYMS = ["7203@1", "9984@1", "6758@1"]
RELAY = "http://127.0.0.1:18091"
BEARER = open("data/.bearer").read().strip()
HDR = {"Authorization": f"Bearer {BEARER}"}

con = sqlite3.connect("data/kabu_orderbook.db")
con.row_factory = sqlite3.Row

def head(s: str) -> None:
    print()
    print("====", s, "====")


# 1. kabu raw (DB stored) vs relay output
head("1. raw_json (saved) vs relay output, per symbol")
for s in SYMS:
    relay = requests.get(f"{RELAY}/v1/boards/{s}", headers=HDR).json()
    row = con.execute(
        "SELECT raw_json FROM orderbook_snapshots WHERE api_symbol=? AND collected_at=?",
        (s, relay["collected_at_utc"]),
    ).fetchone()
    raw = json.loads(row["raw_json"])
    bid_ok = raw["Buy1"]["Price"] == relay["best_bid_price"] and raw["Buy1"]["Qty"] == relay["best_bid_qty"]
    ask_ok = raw["Sell1"]["Price"] == relay["best_ask_price"] and raw["Sell1"]["Qty"] == relay["best_ask_qty"]
    cur_ok = raw["CurrentPrice"] == relay["current_price"]
    vol_ok = raw["TradingVolume"] == relay["trading_volume"]
    vwap_ok = raw["VWAP"] == relay["vwap"]
    ladder = (
        all(raw[f"Buy{i}"]["Price"] == relay["bids"][i - 1]["price"] for i in range(1, 11))
        and all(raw[f"Sell{i}"]["Price"] == relay["asks"][i - 1]["price"] for i in range(1, 11))
    )
    print(f"  {s:8s}  bid:{bid_ok}  ask:{ask_ok}  cur:{cur_ok}  vol:{vol_ok}  vwap:{vwap_ok}  20-level-ladder:{ladder}")


# 2. Computational identity: every row in DB
head("2. Computational identity: every snapshot in DB (mid/spread/depth recomputed from raw)")
total = bad = 0
sample_bad = []
for s in SYMS:
    rows = con.execute(
        """SELECT raw_json, mid_price, spread, spread_pct, bid_depth_5_jpy, ask_depth_5_jpy
           FROM orderbook_snapshots WHERE api_symbol=?""",
        (s,),
    ).fetchall()
    for r in rows:
        total += 1
        raw = json.loads(r["raw_json"])
        bp, ap = raw["Buy1"]["Price"], raw["Sell1"]["Price"]
        if bp is None or ap is None:
            continue
        emid = (bp + ap) / 2
        espr = ap - bp
        epct = (espr / emid) * 100
        ebid = sum(raw[f"Buy{i}"]["Price"] * raw[f"Buy{i}"]["Qty"] for i in range(1, 6))
        eask = sum(raw[f"Sell{i}"]["Price"] * raw[f"Sell{i}"]["Qty"] for i in range(1, 6))
        for name, expected, actual, tol in [
            ("mid",   emid, r["mid_price"],        1e-9),
            ("spr",   espr, r["spread"],           1e-9),
            ("pct",   epct, r["spread_pct"],       1e-6),
            ("biddp", ebid, r["bid_depth_5_jpy"],  1e-3),
            ("askdp", eask, r["ask_depth_5_jpy"],  1e-3),
        ]:
            if abs(expected - actual) > tol:
                bad += 1
                if len(sample_bad) < 3:
                    sample_bad.append((s, name, expected, actual))
                break
print(f"  rows checked: {total}, mismatches: {bad}")
if sample_bad:
    print(f"  sample mismatches: {sample_bad}")


# 3. Sanity: ladder monotonicity, no negative prices, no negative spread
head("3. Ladder monotonicity + spread sanity (every snapshot)")
checks = {"bid_mono": 0, "ask_mono": 0, "spread_neg": 0, "price_neg": 0}
total = 0
for s in SYMS:
    for r in con.execute("SELECT raw_json FROM orderbook_snapshots WHERE api_symbol=?", (s,)):
        total += 1
        raw = json.loads(r["raw_json"])
        bids = [raw[f"Buy{i}"]["Price"] for i in range(1, 11)]
        asks = [raw[f"Sell{i}"]["Price"] for i in range(1, 11)]
        bs = [b for b in bids if b is not None]
        if any(bs[i] <= bs[i + 1] for i in range(len(bs) - 1)):
            checks["bid_mono"] += 1
        as_ = [a for a in asks if a is not None]
        if any(as_[i] >= as_[i + 1] for i in range(len(as_) - 1)):
            checks["ask_mono"] += 1
        if bids[0] is not None and asks[0] is not None and asks[0] - bids[0] < 0:
            checks["spread_neg"] += 1
        for v in bids + asks:
            if v is not None and v <= 0:
                checks["price_neg"] += 1
print(f"  rows checked: {total}")
print(f"  bid ladder NOT strictly descending : {checks['bid_mono']}")
print(f"  ask ladder NOT strictly ascending  : {checks['ask_mono']}")
print(f"  best_ask < best_bid (negative spread): {checks['spread_neg']}")
print(f"  non-positive prices                : {checks['price_neg']}")


# 4. VWAP within [Low,High], current_price near ladder
head("4. Day's price band vs VWAP / current_price")
for s in SYMS:
    r = con.execute(
        "SELECT raw_json FROM orderbook_snapshots WHERE api_symbol=? ORDER BY id DESC LIMIT 1", (s,)
    ).fetchone()
    raw = json.loads(r["raw_json"])
    lp, hp, op, pc, vwap, cur = (
        raw.get("LowPrice"), raw.get("HighPrice"),
        raw.get("OpeningPrice"), raw.get("PreviousClose"),
        raw["VWAP"], raw["CurrentPrice"],
    )
    bp, ap = raw["Buy1"]["Price"], raw["Sell1"]["Price"]
    in_lh = lp is not None and hp is not None and lp <= vwap <= hp
    cur_band_ok = (
        bp is not None and ap is not None and (bp <= cur <= ap or abs(cur - bp) <= 5 or abs(cur - ap) <= 5)
    )
    print(f"  {s:8s} prev_close={pc} open={op} low={lp} high={hp}")
    print(f"           vwap={vwap} (in [low,high]: {in_lh})  cur={cur} (within band: {cur_band_ok})")
    print(f"           best_bid={bp} best_ask={ap} spread={ap-bp if (bp and ap) else None}")


# 5. Time monotonicity + gap distribution
head("5. Time-ordering + sampling-cadence sanity")
for s in SYMS:
    times = [
        datetime.fromisoformat(r["collected_at"])
        for r in con.execute(
            "SELECT collected_at FROM orderbook_snapshots WHERE api_symbol=? ORDER BY id ASC", (s,)
        )
    ]
    gaps = [(times[i + 1] - times[i]).total_seconds() for i in range(len(times) - 1)]
    monotone = all(g > 0 for g in gaps)
    print(
        f"  {s:8s} rows={len(times)} time_monotone={monotone} "
        f"min_gap={min(gaps):.2f}s med_gap={median(gaps):.2f}s max_gap={max(gaps):.2f}s"
    )


# 6. price_changes are real changes, and align with adjacent snapshots
head("6. price_changes: every row is a real change")
mis = ok = 0
for r in con.execute(
    """SELECT prev_best_bid, new_best_bid, prev_best_ask, new_best_ask FROM price_changes"""
):
    if r["prev_best_bid"] != r["new_best_bid"] or r["prev_best_ask"] != r["new_best_ask"]:
        ok += 1
    else:
        mis += 1
print(f"  price_changes rows total={ok+mis}, with-real-change={ok}, no-op={mis}")

head("6b. price_changes align with adjacent snapshots (last 5)")
for pc in con.execute(
    """SELECT id, api_symbol, detected_at,
              prev_best_bid, new_best_bid, prev_best_ask, new_best_ask
       FROM price_changes ORDER BY id DESC LIMIT 5"""
):
    s = pc["api_symbol"]
    new = con.execute(
        "SELECT best_bid_price, best_ask_price FROM orderbook_snapshots "
        "WHERE api_symbol=? AND collected_at=?",
        (s, pc["detected_at"]),
    ).fetchone()
    prev = con.execute(
        "SELECT best_bid_price, best_ask_price FROM orderbook_snapshots "
        "WHERE api_symbol=? AND collected_at<? ORDER BY collected_at DESC LIMIT 1",
        (s, pc["detected_at"]),
    ).fetchone()
    nb_ok = new and new["best_bid_price"] == pc["new_best_bid"]
    na_ok = new and new["best_ask_price"] == pc["new_best_ask"]
    pb_ok = (prev is None) or prev["best_bid_price"] == pc["prev_best_bid"]
    pa_ok = (prev is None) or prev["best_ask_price"] == pc["prev_best_ask"]
    print(f"  pc.id={pc['id']:>4} {s:8s} new_bid:{nb_ok} new_ask:{na_ok} prev_bid:{pb_ok} prev_ask:{pa_ok}")


# 7. Closing snapshot vs kabu now (post-close, kabu still serves last quote)
head("7. Last snapshot vs kabu live (post-close: kabu serves last-quote)")
import os as _os
pw = _os.environ["KABU_API_PASSWORD"]
tok = requests.post("http://localhost:18080/kabusapi/token", json={"APIPassword": pw}).json()["Token"]
for s in SYMS:
    kraw = requests.get(f"http://localhost:18080/kabusapi/board/{s}", headers={"X-API-KEY": tok}).json()
    last = con.execute(
        "SELECT collected_at, best_bid_price, best_ask_price, current_price, trading_volume, vwap "
        "FROM orderbook_snapshots WHERE api_symbol=? ORDER BY id DESC LIMIT 1",
        (s,),
    ).fetchone()
    same_state = (
        kraw["Buy1"]["Price"] == last["best_bid_price"]
        and kraw["Sell1"]["Price"] == last["best_ask_price"]
        and kraw["CurrentPrice"] == last["current_price"]
        and kraw["TradingVolume"] == last["trading_volume"]
        and kraw["VWAP"] == last["vwap"]
    )
    print(
        f"  {s:8s} last_db_at={last['collected_at']} "
        f"matches_kabu_now={same_state}"
    )
    print(
        f"           db:    bid={last['best_bid_price']} ask={last['best_ask_price']} "
        f"cur={last['current_price']} vol={last['trading_volume']} vwap={last['vwap']}"
    )
    print(
        f"           kabu:  bid={kraw['Buy1']['Price']} ask={kraw['Sell1']['Price']} "
        f"cur={kraw['CurrentPrice']} vol={kraw['TradingVolume']} vwap={kraw['VWAP']}"
    )
