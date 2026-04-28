# kabu-relay

Read-only relay for kabuステーションAPI. Observation only — no order endpoints.

## Constraints

- Active universe is capped at **50 symbols** (kabu's combined REST/PUSH registration limit).
  `symbols > 50` causes startup failure.
- APIPassword and kabu tokens are never exposed in API responses, logs, or exports.
- Exports always return a **frozen copy** of the SQLite DB, never the live file.
- Symbol registration is owned by the local relay; remote clients only call this relay's API.

## Quick start

1. Install dependencies (Python 3.11+):

   ```
   pip install -r requirements.txt
   ```

2. Copy the example config:

   ```
   cp config/relay_config.example.json config/relay_config.json
   ```

3. Set required environment variables:

   ```
   KABU_API_PASSWORD=...                  # kabu station APIPassword
   KABU_RELAY_BEARER_TOKEN=...            # shared bearer for relay clients
   KABU_RELAY_CONFIG=./config/relay_config.json
   ```

   Optional overrides:

   ```
   KABU_RELAY_LISTEN_HOST=0.0.0.0
   KABU_RELAY_LISTEN_PORT=18081
   KABU_HOST=127.0.0.1
   KABU_PORT=18080
   KABU_DB_PATH=./data/kabu_orderbook.db
   KABU_EXPORT_DIR=./exports
   KABU_RELAY_LOG_DIR=./logs
   KABU_RELAY_LOG_LEVEL=INFO
   KABU_RELAY_DISABLE_FILE_LOG=1          # stderr only
   KABU_RELAY_ALLOW_DEGRADED=1            # boot even if initial token fetch fails
   ```

4. Run:

   ```
   python -m app.main
   ```

   or

   ```
   uvicorn app.main:app --host 0.0.0.0 --port 18081
   ```

## Endpoints

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/health` | none | liveness |
| GET | `/v1/status` | bearer + IP | collector/token/storage state |
| GET | `/v1/symbols` | bearer + IP | configured universe |
| GET | `/v1/boards/{api_symbol}` | bearer + IP | latest snapshot for one symbol |
| GET | `/v1/boards?symbols=...` | bearer + IP | bulk latest snapshots |
| GET | `/v1/snapshots?symbol=...` | bearer + IP | history with limit/from/to |
| GET | `/v1/price-changes?symbol=...` | bearer + IP | best-quote change log |
| GET | `/v1/export/meta` | bearer + IP | last frozen export metadata |
| GET | `/v1/export/sqlite/latest` | bearer + IP | download frozen SQLite copy |

All non-`/health` endpoints require:

- `Authorization: Bearer <token>`
- request client IP within `server.allowed_subnets`

## Sample API calls

### Liveness

```bash
curl http://127.0.0.1:18081/health
```

```json
{"ok": true, "service": "kabu-relay", "version": "v1"}
```

### `/v1/status`

```bash
curl -H "Authorization: Bearer $KABU_RELAY_BEARER_TOKEN" \
     http://127.0.0.1:18081/v1/status
```

200 response:

```json
{
  "ok": true,
  "service": "kabu-relay",
  "version": "v1",
  "server_time_utc": "2026-04-27T09:00:05.500000+00:00",
  "collector": {
    "running": true,
    "mode": "poll",
    "poll_interval_seconds": 5,
    "configured_symbol_count": 7,
    "last_success_at_utc": "2026-04-27T09:00:05.123456+00:00",
    "last_error_at_utc": null,
    "last_error_message": null,
    "consecutive_error_count": 0,
    "lag_seconds": 0.4,
    "last_cycle_duration_seconds": 0.832,
    "market_session": "morning",
    "market_open": true,
    "freshness": "fresh"
  },
  "kabu": {
    "reachable": true,
    "host": "127.0.0.1",
    "port": 18080,
    "token_status": "valid",
    "token_last_refreshed_at_utc": "2026-04-27T00:01:05+00:00"
  },
  "storage": {
    "db_path": "./data/kabu_orderbook.db",
    "latest_snapshot_at_utc": "2026-04-27T09:00:05.123456+00:00",
    "snapshot_rows": 12345,
    "price_change_rows": 678
  }
}
```

`401` if the bearer is missing or wrong; `403` if the client IP is outside `server.allowed_subnets`.

### `/v1/boards/{api_symbol}`

```bash
curl -H "Authorization: Bearer $KABU_RELAY_BEARER_TOKEN" \
     http://127.0.0.1:18081/v1/boards/4582@3
```

200 response:

```json
{
  "api_symbol": "4582@3",
  "symbol": "4582",
  "exchange": 3,
  "symbol_name": "シンバイオ製薬",
  "bucket": "tier1",
  "collected_at_utc": "2026-04-27T09:00:05.123456+00:00",
  "source_current_price_time": "2026-04-27T09:00:04+09:00",
  "current_price": 501.0,
  "trading_volume": 150000,
  "vwap": 501.5,
  "best_bid_price": 500.0,
  "best_bid_qty": 200,
  "best_ask_price": 502.0,
  "best_ask_qty": 300,
  "mid_price": 501.0,
  "spread": 2.0,
  "spread_pct": 0.3992,
  "bid_depth_5_jpy": 1195600.0,
  "ask_depth_5_jpy": 1719600.0,
  "bids": [
    {"level": 1, "price": 500.0, "qty": 200},
    {"level": 2, "price": 499.0, "qty": 400}
  ],
  "asks": [
    {"level": 1, "price": 502.0, "qty": 300},
    {"level": 2, "price": 503.0, "qty": 500}
  ],
  "source": "kabu_board_poll",
  "freshness_ms": 850,
  "stale": false
}
```

`404` is returned in two distinct cases — both as `{"error": "symbol_not_found", ...}`:

- the `api_symbol` is not in the relay's configured `symbols[]`
- the symbol is configured, but the collector hasn't recorded a snapshot yet (e.g. you queried before market open)

### `/v1/snapshots`

```bash
curl -H "Authorization: Bearer $KABU_RELAY_BEARER_TOKEN" \
     "http://127.0.0.1:18081/v1/snapshots?symbol=4582@3&limit=100&order=desc"
```

### `/v1/export/sqlite/latest`

```bash
curl -OJ -H "Authorization: Bearer $KABU_RELAY_BEARER_TOKEN" \
     http://127.0.0.1:18081/v1/export/sqlite/latest
# saves `kabu_orderbook_snapshot_<UTC>.db` in cwd
```

The relay first VACUUMs (or backup-copies) the live DB into `exports/` and only then streams that frozen file. The live DB is never handed out directly.

## Config schema

See `config/relay_config.example.json`. Required fields:

- `server.{listen_host,listen_port,bearer_token_env,allowed_subnets}`
- `kabu.{host,port,api_password_env}`
- `collection.{poll_interval_seconds,sessions[]}`
- `storage.{db_path,export_dir}`
- `symbols[]` with `len <= 50`

Validation:

- `len(symbols) <= 50` (hard fail)
- `poll_interval_seconds > 0`
- `server.listen_port != kabu.port`

Optional `collection.extra_closed_dates[]` lets you flag JST dates `"YYYY-MM-DD"` (e.g. year-end / new-year non-holiday closures) on top of weekends and Japanese national holidays, which are detected automatically via the `jpholiday` package.

## SQLite schema

See `app/schema.sql`. Tables:

- `collector_runs` — per-process run record
- `orderbook_snapshots` — normalized board snapshots
- `price_changes` — best-quote change events
- `exports` — frozen export metadata
- `api_errors` — upstream/integration errors

## Logging

- Stderr handler is always active.
- A rotating file handler writes to `${KABU_RELAY_LOG_DIR:-./logs}/relay.log` (10 MiB × 5 files). Set `KABU_RELAY_DISABLE_FILE_LOG=1` to skip the file handler.
- **Use an absolute path for `KABU_RELAY_LOG_DIR`** (e.g. `C:\kabu-relay\logs`). The default `./logs` is resolved against the process's current working directory; if the relay is launched from a different folder (Task Scheduler, Windows service wrapper, IDE), logs land somewhere unexpected. The same applies to `KABU_DB_PATH` and `KABU_EXPORT_DIR`.
- If `logs/` is unwritable at startup, the file handler is skipped and a single `WARNING file logging disabled (continuing with stderr only)` line is emitted to stderr — the process keeps running.
- Each polling cycle emits one start and one end line:

  ```
  2026-04-27 09:00:00,123 INFO app.collector: collector cycle start id=ab12cd34 symbols=7 run=...
  2026-04-27 09:00:00,955 INFO app.collector: collector cycle end   id=ab12cd34 fetched=7 errors=0 duration=0.832s
  ```

- Other lines covered: server started, token refreshed (success/failure), collector cycle start/end, symbol fetch error, export created, auth failure.
- Secrets (`APIPassword`, kabu token, bearer token) are never logged in plaintext by code.

## Operations

### Run as a detached background process

`scripts/Start-Relay.ps1` launches the relay so it survives the spawning shell. Secrets come from `.env` (loaded automatically) and the bearer token comes from `data/.bearer` (auto-generated on first run if missing).

```powershell
# bring it up
.\scripts\Start-Relay.ps1            # starts detached, prints PID and log paths
.\scripts\Status-Relay.ps1           # UP/DOWN, uptime, /health probe
.\scripts\Stop-Relay.ps1             # tree-kill via taskkill /F /T

# foreground (for debugging)
.\scripts\Start-Relay.ps1 -Foreground
```

Files:

| Path | Purpose |
| --- | --- |
| `data/.bearer` | bearer token, generated once on first start. **Treat as a secret.** Rotate by deleting and re-running `Start-Relay.ps1`. |
| `data/relay.pid` | PID of the venv launcher. `Stop-Relay.ps1` reads this and tree-kills the whole process group. |
| `logs/relay.log` (+ `.1`...`.5`) | App-level rotating log (10 MiB × 5). Cycle start/end, token refresh, auth failures, etc. |
| `logs/relay.stdout.log` | uvicorn stdout (small; just startup/shutdown banners). |
| `logs/relay.stderr.log` | uvicorn stderr (small; HTTP request lines if `--access-log` were enabled). |

### Survive a reboot (Task Scheduler)

The detached-process approach keeps the relay running until the next reboot or `Stop-Relay.ps1`. To bring it back automatically after a reboot, register a Scheduled Task. Run once as the user who owns the venv:

```powershell
$action  = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\Users\win_marduk\hyena\kabu_station_API_relay\scripts\Start-Relay.ps1"'
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName 'kabu-relay' `
    -Action $action -Trigger $trigger -Principal $principal -Settings $settings

# manually trigger / verify
Start-ScheduledTask -TaskName 'kabu-relay'
Get-ScheduledTaskInfo -TaskName 'kabu-relay'
```

To remove later:

```powershell
Unregister-ScheduledTask -TaskName 'kabu-relay' -Confirm:$false
```

Notes:

- **kabu-station must already be running and logged in** when the relay starts. Use `-AtLogOn` (above) so the task fires after the user is logged in. `-AtStartup` is too early — kabu requires an interactive session.
- The task runs as the same user, so `.env` and `.venv` resolve normally.
- `RestartCount=3 RestartInterval=5m` covers transient crashes; long-term degradation should still be inspected via `logs/relay.log`.

## Tests

```
pytest -q
```

## Not implemented (out of scope / Phase2)

- Order / modify / cancel endpoints — by design.
- WebSocket / SSE / `/v1/stream` — Phase2.
- Explicit `/register` synchronization — `kabu_client.register_symbols` is implemented but the collector relies on `/board/{symbol}` auto-registration in MVP. Wire it through if deterministic registration is required.
- Windows service / Task Scheduler integration.
- 429 rate limiting.
- Opaque cursor for `/v1/snapshots` (currently a raw `id`).
- HTTP keep-alive via `requests.Session` in the kabu client.
- Tests for: 401-retry path, `ExportBusyError`, `KABU_RELAY_ALLOW_DEGRADED`, scheduled refresh dedupe.

## Real-machine verification status (Gate A)

**Status: PASS** on 2026-04-28 14:23 JST against a live kabu station running on this Windows PC.

Findings that became part of the example config:

- **`kabu.host` must be `"localhost"`, not `"127.0.0.1"`.** kabu's HTTP.sys-backed listener rejects `127.0.0.1` Host headers with `400 Invalid Hostname`. The example config now uses `localhost`.
- **`server.listen_port: 18081` is unusable on this machine.** The kabu station's sandbox endpoint reserves port 18081 in HTTP.sys (`OwningProcess=4` = System), so the relay cannot bind there. The example uses `18091` instead.
- **kabu's board response uses the documented schema:** `Buy1..Buy10` is the bid ladder (best bid first), `Sell1..Sell10` is the ask ladder (best ask first), each level a `{Price, Qty, Sign, Time}` object. `_extract_levels` and `normalize_board` handle this correctly. (Note: kabu's separate top-of-book fields `BidPrice`/`AskPrice` use the inverted Japanese convention and are intentionally **not** used by the relay; we always read off the ladder.)
- **kabu's response is UTF-8** despite the OS being on a Shift_JIS console. Symbol names like `トヨタ自動車` round-trip correctly.
- **401-then-refresh-then-retry actually fires in production** (the kabu test environment cycles tokens roughly every minute under load). The relay's retry path was observed multiple times during the verification window with `fetched=3 errors=0` after the retry.
- **`VACUUM INTO`** succeeded against the live DB while the polling writer was active; no fallback to backup-API was needed.
- **403 on a tightened allowlist (`10.255.255.0/30`) returns the `forbidden_ip` envelope** with the client IP populated.

Items that remain not directly observable on a single host:

- IP allowlist behavior across **multiple physical hosts on the LAN** — verified by tightening the allowlist on the same machine. Multi-host execution is still recommended for the OpenClaw deployment phase.
- Daily JST 08:55 token refresh — the scheduled trigger was not exercised during the verification window. The 401-driven refresh path was verified, which exercises the same `TokenManager.refresh()` code.

## On-machine verification steps (post-deployment)

**Run during market hours** (前場 09:00–11:30 / 後場 12:30–15:30 JST, business days). Outside the window, snapshots won't accumulate and `stale=false` cannot be confirmed.

### Evidence to capture and bring back

Save these three artifacts as the verification record:

1. The relevant slice of `logs/relay.log` (covering startup → at least one full cycle).
2. The full `/v1/status` JSON during market hours.
3. **One raw board JSON** — query a known symbol and save the response. Useful for diffing kabu's actual field names against this code's assumptions in `app/collector.py:normalize_board`.

### Pass criteria (fixed)

The verification is **PASS** if all four hold:

- `/v1/status` shows `kabu.token_status == "valid"`
- `orderbook_snapshots` row count is monotonically increasing across two consecutive checks (`SELECT COUNT(1) FROM orderbook_snapshots;` taken ~30 s apart)
- `/v1/boards/{api_symbol}` returns `stale: false` for at least one configured symbol during market hours
- LAN-client checks return the expected codes: `401` for missing/wrong bearer, `403` for IP outside allowlist, `200` for both correct

### Tolerated (not a fail)

- `VACUUM INTO failed ...; falling back to backup API` in `relay.log` — the `backup()` fallback is by design and produces an equally valid frozen file.

### Steps

Run these on the kabu-connected Windows PC, in order:

1. Confirm kabuステーション is running and reachable on `127.0.0.1:18080`:
   ```bash
   curl -X POST -H "Content-Type: application/json" \
        -d '{"APIPassword":"'"$KABU_API_PASSWORD"'"}' \
        http://127.0.0.1:18080/kabusapi/token
   ```
   Expected: `200 OK` with `{"ResultCode": 0, "Token": "..."}`. **Never paste the token into logs / chat.**

2. Start the relay:
   ```bash
   python -m app.main
   ```
   `logs/relay.log` should contain `kabu-relay started`, `token refreshed`.

3. From the same machine, hit `/health`:
   ```bash
   curl http://127.0.0.1:18081/health
   ```

4. From the same machine, hit `/v1/status` with bearer:
   ```bash
   curl -H "Authorization: Bearer $KABU_RELAY_BEARER_TOKEN" \
        http://127.0.0.1:18081/v1/status
   ```
   `kabu.token_status` should be `"valid"`. Outside market hours, `collector.market_open` is `false` and `latest_snapshot_at_utc` may be `null` — that is expected.

5. During market hours (前場 09:00–11:30 / 後場 12:30–15:30 JST, business days), confirm a snapshot lands:
   ```bash
   curl -H "Authorization: Bearer $KABU_RELAY_BEARER_TOKEN" \
        http://127.0.0.1:18081/v1/boards/4582@3
   ```
   Should return the schema documented above with `stale=false` and `freshness_ms` near the polling interval.

6. From the LAN client (e.g. OpenClaw machine), repeat steps 3–5 against `http://<relay-host>:18081/...`. A `403` here means the client's IP is outside `server.allowed_subnets`; a `401` means the bearer doesn't match.

7. Pull a frozen export and inspect it offline:
   ```bash
   curl -OJ -H "Authorization: Bearer $KABU_RELAY_BEARER_TOKEN" \
        http://127.0.0.1:18081/v1/export/sqlite/latest
   sqlite3 kabu_orderbook_snapshot_*.db "SELECT COUNT(1) FROM orderbook_snapshots;"
   ```

8. Force a 401 path: stop kabuステーション, wait for the next collector cycle, then restart it. `logs/relay.log` should show one `token refresh` after the failure and the collector should resume on the next cycle.

If any of steps 1–8 deviates from the expected behavior, capture `logs/relay.log` (with secrets already masked by design) and `/v1/status`'s response and feed them back into a follow-up task.
