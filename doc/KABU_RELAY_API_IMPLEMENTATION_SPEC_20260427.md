# KABU Relay API 実装仕様書

日付: 2026-04-27
対象: kabuAPI に接続できる別PC上で relay を実装するエージェント
前提: **観測専用 / read-only**。発注系は実装しない。

---

## 1. この実装のゴール

Windows PC 上で kabuステーションAPI を叩き、板データをローカル保存しつつ、LAN 内の別クライアントに対して安全な read-only API を提供する。

この relay が満たすべきこと:
- kabu API token を内部で管理する
- 複数銘柄の board を 5 秒ごとに取得する
- 正規化済み snapshot を SQLite に保存する
- latest / history / status / frozen export を HTTP で返す
- OpenClaw などの別端末は **relay API のみ** を利用する

重要制約:
- **kabu の API登録銘柄リストは REST/PUSH 合算で最大50銘柄**
- 情報系リクエストは対象銘柄を自動登録するため、polling の `/board/{symbol}` も実質この上限の内側で運用する必要がある
- したがってこの relay は **configured symbols が 50 以下であること** を起動時に必ず検証する

この relay がやってはいけないこと:
- 発注
- 訂正 / 取消
- APIPassword や kabu token の外部露出
- kabuAPI の単純プロキシ化
- WAN 公開

---

## 2. 実装方式の推奨

### 推奨スタック
- Python 3.11+
- FastAPI
- Uvicorn
- sqlite3（標準ライブラリで可）
- pydantic
- requests でもよいが、標準ライブラリ `urllib` でも可

### 推奨プロセス構成
最初は **単一プロセス** でよい。

1. API server process
2. background collector loop
3. token manager
4. export service

将来的には分離してよいが、MVP では 1 プロセスにまとめてよい。

---

## 3. 推奨ディレクトリ構成

```text
kabu-relay/
  app/
    main.py                  # FastAPI entrypoint
    settings.py              # env/config loader
    auth.py                  # bearer token + IP allowlist
    models.py                # pydantic response models
    db.py                    # sqlite connection helpers
    schema.sql               # sqlite schema
    collector.py             # polling loop
    token_manager.py         # kabu token refresh
    kabu_client.py           # /token, /board/{symbol}, /register 等
    export_service.py        # frozen sqlite export
    status_service.py        # health/status aggregation
    repositories/
      snapshots.py
      price_changes.py
      collector_runs.py
    routes/
      health.py
      status.py
      symbols.py
      boards.py
      snapshots.py
      price_changes.py
      export.py
  config/
    relay_config.json
  data/
    kabu_orderbook.db
  exports/
  logs/
  tests/
    test_health.py
    test_status.py
    test_boards.py
    test_export.py
  requirements.txt
  README.md
```

---

## 4. 環境変数

最低限これを使う。

```text
KABU_API_PASSWORD=...
KABU_RELAY_BEARER_TOKEN=...
KABU_RELAY_CONFIG=./config/relay_config.json
KABU_RELAY_LISTEN_HOST=0.0.0.0
KABU_RELAY_LISTEN_PORT=18081
KABU_HOST=127.0.0.1
KABU_PORT=18080
KABU_DB_PATH=./data/kabu_orderbook.db
KABU_EXPORT_DIR=./exports
```

### ルール
- APIPassword は config に平文保存しない
- bearer token も config に直接書かず env を優先
- listen host/port は env 上書きを許す

---

## 5. config JSON 仕様

既存の `config/kabu_relay_server_example_20260427.json` をベースにする。

必須項目:
- `server.listen_host`
- `server.listen_port`
- `server.bearer_token_env`
- `server.allowed_subnets`
- `kabu.host`
- `kabu.port`
- `kabu.api_password_env`
- `collection.poll_interval_seconds`
- `collection.sessions[]`
- `storage.db_path`
- `storage.export_dir`
- `symbols[]`

validation rule:
- `len(symbols) <= 50` を必須にする
- 50 超なら起動失敗でよい

### symbol object
```json
{
  "api_symbol": "4582@3",
  "symbol": "4582",
  "exchange": 3,
  "name": "シンバイオ製薬",
  "bucket": "tier1"
}
```

---

## 6. 起動シーケンス

API 起動時は必ずこの順序。

1. config 読み込み
2. env override 適用
3. bearer token / APIPassword env の存在確認
4. SQLite schema 初期化
5. kabu token 初回取得
6. collector background task 起動
7. FastAPI listen 開始

### 起動失敗条件
以下なら process は fail fast でよい。
- APIPassword env 不在
- bearer token env 不在
- DB path 作成不能
- kabu token 初回取得失敗
- `configured symbols > 50`

ただし将来的には `--allow-degraded-start` を追加してもよい。

---

## 7. kabu token manager 仕様

### 責務
- 起動時 token 取得
- 401 発生時 1 回だけ再取得して再試行
- 毎営業日朝の再取得
- 最新 token のみを memory 上に保持

### state
```json
{
  "token_status": "valid",
  "token_last_refreshed_at_utc": "2026-04-27T00:01:05Z",
  "last_refresh_error": null
}
```

### refresh policy
- 起動時: 必須
- 401 発生時: 1 回だけ refresh
- JST `08:55:00` に refresh 試行
- refresh 失敗時は `status` を degraded にする

### 禁止
- token を API レスポンスに出さない
- token を export DB に保存しない
- token をログに平文出力しない

---

## 8. collector 仕様

### モード
- 初期は polling only
- push / websocket は実装不要

### polling 対象
- `config.symbols[]`
- 1 銘柄ずつ `/kabusapi/board/{api_symbol}` を巡回取得
- ただし **全 active symbol 数は 50 以下** に固定する

補足:
- kabu docs 上、情報系リクエストは対象銘柄を自動で API登録銘柄リストに追加する
- この API登録銘柄リストは REST/PUSH 合算で最大 50
- よって「push を使わないから 50 制約は無関係」とは扱わない

### 銘柄登録の責務
ここは **ローカルの kabu 接続マシン上で、relay が API 経由で管理する** のが正しい。

つまり整理すると:
- **登録処理の実行場所** = kabuステーションが動いているローカルPC
- **登録手段** = そのPC上の kabu API (`localhost:18080`) 経由
- **登録の責任主体** = relay / collector
- **OpenClaw などのリモート側** = 登録を直接やらない

推奨方針:
1. symbol universe は relay config を正本にする
2. relay 起動時にその universe を local API 前提で同期する
3. remote client は `/v1/symbols` を見るだけにする

実装上の扱い:
- polling-only の MVP では、`/board/{api_symbol}` 要求で自動登録される挙動を利用してよい
- ただし deterministic にしたい場合は、relay 起動時に local machine 上で `/register` を使って明示同期してもよい
- どちらの場合でも、**リモート側から kabu の register API を直接叩かせない**

### 間隔
- 全 universe を **5 秒で 1 巡** するのが目標
- 実装簡略化のため MVP では「全銘柄取得後に 5 秒 sleep」でもよい
- 後で per-symbol schedule に改善してよい

### 市場時間 gate
collector は以下のみ取得する。
- 前場 `09:00:00-11:30:00 JST`
- 後場 `12:30:00-15:30:00 JST`

市場時間外は idle でよい。

### 収集結果
各 board レスポンスから最低限これを正規化する。
- `best_bid_price`
- `best_bid_qty`
- `best_ask_price`
- `best_ask_qty`
- `mid_price`
- `spread`
- `spread_pct`
- `bid_depth_5_jpy`
- `ask_depth_5_jpy`
- `bids_json`
- `asks_json`
- `trading_volume`
- `vwap`
- `current_price`
- `current_price_time`
- `collected_at`
- `raw_json`

### stale rule
- 15 秒以内 = fresh
- 15 秒超 60 秒以内 = warning
- 60 秒超 = stale

市場時間外は stale を異常扱いしない。

---

## 9. DB schema

`orderbook_snapshots`, `price_changes`, `collector_runs` は必須。
既存 `scripts/kabu_orderbook_collect.py` の schema と互換でよい。

### 必須テーブル

#### collector_runs
- `run_id TEXT PRIMARY KEY`
- `started_at TEXT NOT NULL`
- `config_path TEXT NOT NULL`
- `db_path TEXT NOT NULL`
- `status TEXT NOT NULL` (`running|completed|failed`)
- `notes TEXT`

#### orderbook_snapshots
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `run_id TEXT NOT NULL`
- `collected_at TEXT NOT NULL`
- `symbol TEXT NOT NULL`
- `symbol_name TEXT`
- `bucket TEXT`
- `exchange INTEGER`
- `api_symbol TEXT`
- `best_bid_price REAL`
- `best_bid_qty REAL`
- `best_ask_price REAL`
- `best_ask_qty REAL`
- `mid_price REAL`
- `spread REAL`
- `spread_pct REAL`
- `bid_depth_5_jpy REAL`
- `ask_depth_5_jpy REAL`
- `bids_json TEXT`
- `asks_json TEXT`
- `trading_volume REAL`
- `vwap REAL`
- `current_price REAL`
- `current_price_time TEXT`
- `raw_json TEXT NOT NULL`

index:
- `(symbol, collected_at)`
- `(api_symbol, collected_at)`

#### price_changes
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `run_id TEXT NOT NULL`
- `detected_at TEXT NOT NULL`
- `symbol TEXT NOT NULL`
- `change_type TEXT NOT NULL`
- `prev_best_bid REAL`
- `prev_best_ask REAL`
- `new_best_bid REAL`
- `new_best_ask REAL`
- `prev_spread_pct REAL`
- `new_spread_pct REAL`
- `best_bid_duration_sec REAL`
- `best_ask_duration_sec REAL`

### 追加推奨テーブル

#### api_errors
- `id`
- `occurred_at`
- `component`
- `symbol`
- `error_type`
- `message`
- `retryable`

#### exports
- `id`
- `created_at`
- `file_path`
- `file_size_bytes`
- `snapshot_rows`
- `price_change_rows`
- `latest_snapshot_at`

---

## 10. API contract

Base path: `/v1`
Auth: `Authorization: Bearer <token>`

### 10.1 GET `/health`
認証不要でもよい。

response:
```json
{
  "ok": true,
  "service": "kabu-relay",
  "version": "v1"
}
```

### 10.2 GET `/v1/status`
返すべき fields:
- `ok`
- `server_time_utc`
- `collector.running`
- `collector.mode`
- `collector.poll_interval_seconds`
- `collector.configured_symbol_count`
- `collector.last_success_at_utc`
- `collector.last_error_at_utc`
- `collector.consecutive_error_count`
- `collector.lag_seconds`
- `collector.market_session`
- `collector.market_open`
- `kabu.reachable`
- `kabu.host`
- `kabu.port`
- `kabu.token_status`
- `kabu.token_last_refreshed_at_utc`
- `storage.db_path`
- `storage.latest_snapshot_at_utc`
- `storage.snapshot_rows`
- `storage.price_change_rows`

### 10.3 GET `/v1/symbols`
query:
- `bucket` optional

response:
```json
{
  "count": 7,
  "symbols": [
    {
      "api_symbol": "4582@3",
      "symbol": "4582",
      "exchange": 3,
      "name": "シンバイオ製薬",
      "bucket": "tier1"
    }
  ]
}
```

### 10.4 GET `/v1/boards/{api_symbol}`
path:
- `api_symbol`: example `4582@3`

response:
- latest snapshot 1 件

404:
- config 未登録 symbol
- まだ snapshot が 1 件もない symbol

### 10.5 GET `/v1/boards`
query:
- `symbols` optional, comma separated
- 未指定なら全 symbol

response:
```json
{
  "count": 2,
  "snapshots": [ ... ]
}
```

### 10.6 GET `/v1/snapshots`
query:
- `symbol` required (`4582@3`)
- `from` optional ISO8601 UTC
- `to` optional ISO8601 UTC
- `limit` optional default 500, max 5000
- `cursor` optional
- `order` optional `asc|desc`, default `desc`

cursor strategy:
- MVP は `cursor` なしでも可
- 代替として `before_id` / `after_id` でも可

response:
```json
{
  "symbol": "4582@3",
  "count": 500,
  "next_cursor": null,
  "rows": [
    {
      "id": 123,
      "collected_at_utc": "2026-04-27T09:00:05.123456+00:00",
      "best_bid_price": 500.0,
      "best_bid_qty": 200,
      "best_ask_price": 502.0,
      "best_ask_qty": 300,
      "spread_pct": 0.3992,
      "trading_volume": 150000,
      "current_price": 501.0
    }
  ]
}
```

### 10.7 GET `/v1/price-changes`
query:
- `symbol` required
- `from` optional
- `to` optional
- `limit` optional default 500

response:
- `price_changes` rows

### 10.8 GET `/v1/export/meta`
response:
```json
{
  "latest_export": {
    "created_at_utc": "2026-04-27T09:10:00Z",
    "file_name": "kabu_orderbook_snapshot_20260427T091000Z.db",
    "file_size_bytes": 12345678,
    "snapshot_rows": 34567,
    "price_change_rows": 890,
    "latest_snapshot_at_utc": "2026-04-27T09:09:55Z"
  }
}
```

### 10.9 GET `/v1/export/sqlite/latest`
動作:
- まず live DB を copy して temp/frozen DB を作る
- その file を返す
- 返す直前に row counts を meta へ保存してもよい

レスポンス:
- `Content-Type: application/octet-stream`
- download filename 付き

注意:
- live DB の直 path を返さない
- file handle を live DB に貼り付けない

---

## 11. 認証・認可 middleware 仕様

### bearer auth
- `Authorization` header 必須
- `Bearer <token>` のみ許可
- token 不一致なら 401

### IP allowlist
- `request.client.host` を評価
- `allowed_subnets` に含まれない場合 403
- ローカル開発用に `127.0.0.1/32` を追加してよい

### auth exemption
- `/health` は exempt でもよい
- それ以外は認証必須

---

## 12. エラー仕様

標準 JSON:
```json
{
  "error": "symbol_not_found",
  "message": "Unknown api_symbol: 9999@3"
}
```

error code examples:
- `unauthorized`
- `forbidden_ip`
- `symbol_not_found`
- `invalid_query`
- `kabu_unreachable`
- `collector_not_ready`
- `export_in_progress`
- `internal_error`

HTTP status:
- 400 invalid query
- 401 auth error
- 403 allowlist error
- 404 unknown symbol
- 409 export busy
- 429 optional rate limit
- 503 upstream unavailable / stale

---

## 13. ログ仕様

最低限出すもの:
- server started
- token refreshed
- token refresh failed
- collector cycle start/end
- symbol fetch error
- export created
- export failed
- auth failure

禁止:
- APIPassword の平文
- bearer token の平文
- kabu token の平文

---

## 14. frozen export の実装要件

これは重要。

### 必須動作
1. collector が使っている live DB とは別 path にコピーする
2. 可能なら `VACUUM INTO`、難しければ file copy でも可
3. export 完了後に file size / row counts / latest snapshot time を記録
4. クライアントへ返す

### 返却 filename 例
- `kabu_orderbook_snapshot_20260427T091000Z.db`

### cleanup
- `keep_exports` 件だけ残す
- 古い export を削除してよい

---

## 15. 実装タスク分解

### Task 1: settings loader
- env + JSON config merge
- validation
- `symbols <= 50` hard check

### Task 2: DB schema/init
- schema.sql
- init on startup

### Task 3: kabu client
- `fetch_token()`
- `fetch_board(api_symbol)`

### Task 4: token manager
- initial refresh
- 401 retry refresh
- scheduled refresh metadata

### Task 5: collector
- session gate
- polling loop
- snapshot normalization
- DB insert
- simple `price_changes` detection

### Task 6: repositories
- latest snapshot by symbol
- latest snapshots bulk
- historical snapshots query
- row count / latest timestamp

### Task 7: API routes
- `/health`
- `/v1/status`
- `/v1/symbols`
- `/v1/boards/{api_symbol}`
- `/v1/boards`
- `/v1/snapshots`
- `/v1/price-changes`
- `/v1/export/meta`
- `/v1/export/sqlite/latest`

### Task 8: auth middleware
- bearer token
- IP allowlist

### Task 9: export service
- frozen copy
- download response
- metadata tracking

### Task 10: tests
- health test
- auth test
- latest board test
- snapshots query test
- export test

---

## 16. 受け入れ基準

以下を満たしたら MVP 完了。

### 起動
- config/env を読んで起動できる
- kabu token 初回取得成功で collector が動き出す
- `symbols > 50` の config は起動時に reject される

### collector
- 市場時間中に 5 秒ごと収集できる
- 7 銘柄以上を連続収集できる
- DB に snapshot が蓄積する

### API
- `/health` が返る
- auth ありで `/v1/status` が返る
- `/v1/boards/{api_symbol}` が最新 1 件を返す
- `/v1/snapshots` が履歴を返す
- `/v1/export/sqlite/latest` が frozen DB を返す

### security
- bearer token なしで 401
- allowlist 外で 403
- token / password がレスポンスやログに漏れない

### operations
- kabu 一時不達でも process が即死しない
- status に degraded 状態が出る
- export が live DB を壊さない

---

## 17. 実装者への明示的な指示

- **発注機能は実装しないこと**
- **kabu token を API で返さないこと**
- **OpenClaw は relay API のみを叩く前提で作ること**
- **SQLite export は frozen copy で返すこと**
- **MVP は polling でよく、WebSocket は後回しにすること**
- **configured universe は 50 銘柄以下で hard fail させること**
- **Windows サービス化やタスクスケジューラ対応は後回しでよいが、再起動しやすい構造にすること**

---

## 18. まず実装すべき最短順

1. config/env loader
2. DB init
3. kabu token fetch
4. single-symbol `fetch_board`
5. collector 1 周
6. latest board endpoint
7. status endpoint
8. snapshots endpoint
9. frozen export
10. auth / allowlist hardening

これで実装者は迷わず着手できるはず。