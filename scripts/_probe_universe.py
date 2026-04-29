"""Probe candidate symbols against kabu /board, find live api_symbol per ticker.

Robust version:
- /unregister/all to clear the 50-cap slot list at start
- 10s timeout (kabu sometimes responds slowly)
- token auto-refresh on 401 (mimicking the relay's behavior)
- 0.5s throttle between calls
- @1 first (most listings), fall through to @3/@5/@6
"""
from __future__ import annotations
import os, requests, time

CANDIDATES = ["4586", "4056", "4978", "3825", "4583", "7078", "7044"]
EXCHANGES_FALLBACK = [1, 3, 5, 6]
THROTTLE_S = 0.5
TIMEOUT_S = 10.0


class TokenHolder:
    def __init__(self, pw: str):
        self.pw = pw
        self.tok = self._fetch()
        self.refresh_count = 0

    def _fetch(self) -> str:
        return requests.post(
            "http://localhost:18080/kabusapi/token",
            json={"APIPassword": self.pw}, timeout=TIMEOUT_S,
        ).json()["Token"]

    def refresh(self) -> None:
        self.tok = self._fetch()
        self.refresh_count += 1


def fetch_board(holder: TokenHolder, api_sym: str):
    for attempt in (1, 2):
        try:
            r = requests.get(
                f"http://localhost:18080/kabusapi/board/{api_sym}",
                headers={"X-API-KEY": holder.tok},
                timeout=TIMEOUT_S,
            )
        except requests.RequestException as e:
            return ("ERR", None, str(e)[:60])
        if r.status_code == 200:
            return ("OK", r.json(), None)
        # try to read error body
        try:
            code = r.json().get("Code")
            msg  = r.json().get("Message", "")
        except Exception:
            code, msg = "?", r.text[:30]
        if r.status_code == 401 and attempt == 1:
            holder.refresh()
            time.sleep(0.3)
            continue
        return ("HTTP", r.status_code, f"{code} {msg}")
    return ("HTTP", 401, "still 401 after refresh")


def main():
    pw = os.environ["KABU_API_PASSWORD"]
    holder = TokenHolder(pw)

    # Clear any stale registrations.
    print("[1] unregister/all ...", end=" ")
    r = requests.put(
        "http://localhost:18080/kabusapi/unregister/all",
        headers={"X-API-KEY": holder.tok}, timeout=TIMEOUT_S,
    )
    print(f"HTTP {r.status_code}")
    time.sleep(2)

    print()
    print(f"{'sym':<6} {'@ex':<4} {'res':<5} {'detail':<60} {'name':<22} {'price':<8}")
    print("-" * 110)
    results = {}
    for tk in CANDIDATES:
        results[tk] = None
        for ex in EXCHANGES_FALLBACK:
            time.sleep(THROTTLE_S)
            api_sym = f"{tk}@{ex}"
            kind, payload, detail = fetch_board(holder, api_sym)
            if kind == "OK":
                d = payload
                name, mkt, price = d.get("SymbolName"), d.get("ExchangeName"), d.get("CurrentPrice")
                print(f"{tk:<6} @{ex:<3} 200   ok                                                            {name:<22} {price}")
                results[tk] = {
                    "exchange": ex, "api_symbol": api_sym, "name": name,
                    "mkt": mkt, "price": price,
                    "type": d.get("SecurityType"),
                }
                break
            elif kind == "HTTP":
                print(f"{tk:<6} @{ex:<3} {payload:<5} {detail[:60]:<60}")
            else:
                print(f"{tk:<6} @{ex:<3} ERR   {detail[:60]:<60}")

    print()
    print("=" * 95)
    print(f"SUMMARY  (token refreshes during probe: {holder.refresh_count})")
    print("=" * 95)
    print(f"{'ticker':<7} {'api_symbol':<12} {'name':<24} {'market':<10} {'last':<8}")
    for tk, info in results.items():
        if info:
            print(f"{tk:<7} {info['api_symbol']:<12} {info['name']:<24} {info['mkt']:<10} {info['price']}")
        else:
            print(f"{tk:<7} -- not live --")


if __name__ == "__main__":
    main()
