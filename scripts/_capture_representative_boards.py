"""Capture one representative board JSON per new-universe symbol from kabu.
Saves to evidence/board_<sym>.json for hand-off / sanity inspection.
"""
from __future__ import annotations
import json, os, time
from pathlib import Path
import requests

SYMS = ["4586@1", "4056@1", "4978@1", "3825@1", "4583@1"]
TIMEOUT = 10.0

pw = os.environ["KABU_API_PASSWORD"]
tok = requests.post("http://localhost:18080/kabusapi/token", json={"APIPassword": pw}, timeout=TIMEOUT).json()["Token"]
H = {"X-API-KEY": tok}

# Clean slot list first
requests.put("http://localhost:18080/kabusapi/unregister/all", headers=H, timeout=TIMEOUT)
time.sleep(1)

Path("evidence").mkdir(exist_ok=True)

print(f"{'symbol':<8} {'name':<24} {'last':<6} {'bid':<6} {'ask':<6} {'spread':<6} {'vol':<10}")
print("-" * 70)
for s in SYMS:
    time.sleep(0.5)
    for attempt in (1, 2):
        r = requests.get(f"http://localhost:18080/kabusapi/board/{s}", headers=H, timeout=TIMEOUT)
        if r.status_code == 401 and attempt == 1:
            tok = requests.post("http://localhost:18080/kabusapi/token", json={"APIPassword": pw}, timeout=TIMEOUT).json()["Token"]
            H["X-API-KEY"] = tok
            time.sleep(0.3)
            continue
        break
    if r.status_code != 200:
        print(f"  {s} -> HTTP {r.status_code}: {r.text[:100]}")
        continue
    d = r.json()
    Path(f"evidence/board_{s.replace('@','at')}.json").write_text(
        json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    bp = d.get("Buy1", {}).get("Price")
    ap = d.get("Sell1", {}).get("Price")
    spread = ap - bp if (bp and ap) else None
    print(f"{s:<8} {d.get('SymbolName',''):<24} {d.get('CurrentPrice'):<6} {bp:<6} {ap:<6} {spread:<6} {int(d.get('TradingVolume',0) or 0):<10}")
print()
print("saved JSON dumps in evidence/")
