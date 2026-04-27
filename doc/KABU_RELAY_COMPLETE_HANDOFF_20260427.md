# KABU Relay API 完全実装ハンドオフ

日付: 2026-04-27
目的: この文書だけ読めば、別PC上の実装エージェントが kabu relay を完成まで実装できる状態にする。

---

## 0. 一言で何を作るか

**kabuステーションが動いている Windows PC 上に、観測専用の read-only relay サービスを実装する。**

このサービスは:
- kabuAPI から板情報を取る
- 5秒ごとにローカル DB へ保存する
- LAN 内の別端末へ HTTP API で配信する
- OpenClaw 側はこの relay API だけを叩く

**やってはいけないこと**
- 発注
- 訂正 / 取消
- WAN 公開
- APIPassword や kabu token の露出
- リモート端末から kabuAPI を直接叩かせること

---

## 1. 重要前提

### 1.1 配置
- kabuAPI が使えるのは **Windows PC 上の localhost**
- relay も **その同じ PC 上** で動かす
- OpenClaw は別端末から LAN 経由で relay を使う

### 1.2 50銘柄制約
**kabu の API登録銘柄リストは REST/PUSH 合算で最大 50 銘柄。**

さらに、情報系リクエストは対象銘柄を自動登録する。
つまり:
- `/board/{symbol}` polling でも 50 制約の内側で運用する
- relay config の `symbols` は **50 以下必須**
- 50 超なら起動失敗でよい

### 1.3 銘柄登録の責務
- **ローカルの kabu 接続 PC 上で** relay が管理する
- **API経由** で管理する
- remote client から直接 `/register` や kabu API を叩かせない

---

## 2. 最終的にできること

### 2.1 提供 API
- `GET /health`
- `GET /v1/status`
- `GET /v1/symbols`
- `GET /v1/boards/{api_symbol}`
- `GET /v1/boards?symbols=...`
- `GET /v1/snapshots`
- `GET /v1/price-changes`
- `GET /v1/export/meta`
- `GET /v1/export/sqlite/latest`

### 2.2 収集対象
Phase1 は以下の universe を想定する。
- tier1
  - `4582@3`
  - `7078@3`
  - `9325@2`
  - `4015@3`
  - `3969@2`
- controls
  - `3468@2`
  - `1629@1`

必要なら tier2 を足すが、**50 超は不可**。

### 2.3 観測条件
- polling 5秒
- 前場 `09:00-11:30 JST`
- 後場 `12:30-15:30 JST`
- 観測専用、発注なし

---

## 3. 推奨技術スタック

- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic
- sqlite3
- 標準ライブラリ `urllib` または `requests`

MVP は **単一プロセス** で良い。

---

## 4. ディレクトリ構成

```text
kabu-relay/
  app/
    main.py
    settings.py
    auth.py
    models.py
    db.py
    schema.sql
    collector.py
    token_manager.py
    kabu_client.py
    export_service.py
    status_service.py
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
  requirements.txt
  README.md
```

---

## 5. 環境変数

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

ルール:
- APIPassword を config に書かない
- bearer token を config に書かない
- env override を優先

---

## 6. config 仕様

実装は以下の JSON を読めるようにすること。
参照例: `config/kabu_relay_server_example_20260427.json`

必須:
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

validation:
- `symbols.length <= 50`
- `poll_interval_seconds > 0`
- `listen_port != kabu.port`

---

## 7. 起動順序

起動時は必ずこの順で進める。

1. config 読み込み
2. env override 適用
3. secret 存在確認
4. `symbols <= 50` validation
5. SQLite schema 初期化
6. kabu token 初回取得
7. collector background task 起動
8. FastAPI listen 開始

fail fast 条件:
- APIPassword 未設定
- bearer token 未設定
- `symbols > 50`
- DB 初期化失敗
- 初回 token 取得失敗

---

## 8. kabu client 実装要件

### 必須メソッド
- `fetch_token()`
- `fetch_board(api_symbol)`
- `register_symbols(symbols)` optional

### token endpoint
- `POST http://127.0.0.1:18080/kabusapi/token`
- body: `{"APIPassword": "..."}`

### board endpoint
- `GET http://127.0.0.1:18080/kabusapi/board/{api_symbol}`
- header: `X-API-KEY: <token>`

### register endpoint
- deterministic 運用をしたい場合のみ使用
- MVP では board polling による自動登録でも可

---

## 9. token manager 実装要件

### 持つ state
- `current_token`
- `token_status`
- `token_last_refreshed_at_utc`
- `last_refresh_error`

### refresh ルール
- 起動時に必須
- 401 で 1回だけ再取得
- 毎営業日 `08:55 JST` に refresh
- 失敗時は status degraded

### 禁止
- token を API レスポンスに出さない
- token をログに出さない
- token を DB に保存しない

---

## 10. collector 実装要件

### 10.1 polling
- `config.symbols[]` を順番に巡回
- 各 symbol に対して `/board/{api_symbol}` を呼ぶ
- full cycle の目安 5秒

### 10.2 市場時間 gate
collector は以下のみ取得。
- 前場 `09:00:00-11:30:00 JST`
- 後場 `12:30:00-15:30:00 JST`

市場時間外は idle。

### 10.3 正規化項目
各 board から最低限これを保存。
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

### 10.4 stale 判定
- 15秒以内: fresh
- 15秒超 60秒以内: warning
- 60秒超: stale

市場時間外は stale を異常扱いしない。

### 10.5 price change 判定
前回 snapshot と比べて
- `best_bid_price`
- `best_ask_price`
のいずれかが変われば `price_changes` に記録。

---

## 11. DB schema

既存の `scripts/kabu_orderbook_collect.py` と互換でよい。

### 必須テーブル
- `collector_runs`
- `orderbook_snapshots`
- `price_changes`

### orderbook_snapshots に必要な列
- `id`
- `run_id`
- `collected_at`
- `symbol`
- `symbol_name`
- `bucket`
- `exchange`
- `api_symbol`
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
- `raw_json`

index:
- `(symbol, collected_at)`
- `(api_symbol, collected_at)`

---

## 12. HTTP API 仕様

### 12.1 `GET /health`
認証不要でよい。

返却例:
```json
{"ok": true, "service": "kabu-relay", "version": "v1"}
```

### 12.2 `GET /v1/status`
返すもの:
- collector running
- poll interval
- configured symbol count
- last success
- last error
- consecutive error count
- lag seconds
- market session
- market open
- kabu reachable
- token status
- latest snapshot timestamp
- snapshot row count
- price change row count

### 12.3 `GET /v1/symbols`
query:
- `bucket=tier1|tier2|controls` optional

### 12.4 `GET /v1/boards/{api_symbol}`
返すもの:
- symbol の latest snapshot 1 件

404 条件:
- config 未登録
- snapshot 未取得

### 12.5 `GET /v1/boards?symbols=...`
query:
- `symbols=4582@3,7078@3`
- 未指定なら全 symbols

### 12.6 `GET /v1/snapshots`
query:
- `symbol` required
- `from` optional
- `to` optional
- `limit` optional default 500 max 5000
- `cursor` optional
- `order=asc|desc` optional

### 12.7 `GET /v1/price-changes`
query:
- `symbol` required
- `from` optional
- `to` optional
- `limit` optional

### 12.8 `GET /v1/export/meta`
返すもの:
- last export created_at
- filename
- file size
- snapshot row count
- price change row count
- latest snapshot time

### 12.9 `GET /v1/export/sqlite/latest`
**重要:** live DB をそのまま返さない。

動作:
1. live DB を frozen path にコピー
2. row count / latest timestamp を計測
3. `application/octet-stream` で返却

filename 例:
- `kabu_orderbook_snapshot_20260427T091000Z.db`

---

## 13. 認証

### bearer token
- `Authorization: Bearer <token>` 必須
- 不一致なら 401

### IP allowlist
- `request.client.host` を評価
- allowlist 外なら 403

### exempt
- `/health` のみ exempt でよい

---

## 14. エラー仕様

形式:
```json
{
  "error": "symbol_not_found",
  "message": "Unknown api_symbol: 9999@3"
}
```

主な error code:
- `unauthorized`
- `forbidden_ip`
- `symbol_not_found`
- `invalid_query`
- `kabu_unreachable`
- `collector_not_ready`
- `export_in_progress`
- `internal_error`

---

## 15. ログ

最低限記録:
- server started
- token refreshed
- token refresh failed
- collector cycle start/end
- symbol fetch error
- export created
- export failed
- auth failure

ログ禁止:
- APIPassword 平文
- bearer token 平文
- kabu token 平文

---

## 16. frozen export 実装

必須ルール:
- live DB とは別 path にコピー
- 可能なら `VACUUM INTO`
- 難しければ file copy でも可
- old exports は `keep_exports` を超えたら削除

---

## 17. 実装手順

### Step 1
settings loader
- config + env merge
- `symbols <= 50` check

### Step 2
DB init
- schema.sql
- startup auto init

### Step 3
kabu client
- token fetch
- board fetch

### Step 4
token manager
- startup refresh
- 401 retry refresh
- scheduled refresh state

### Step 5
collector
- session gate
- polling loop
- normalize
- insert snapshots
- detect price changes

### Step 6
repositories
- latest snapshot by symbol
- latest bulk snapshots
- historical query
- counts / latest timestamp

### Step 7
routes
- health
- status
- symbols
- boards
- snapshots
- price-changes
- export/meta
- export/sqlite/latest

### Step 8
auth middleware
- bearer
- allowlist

### Step 9
export service
- frozen copy
- metadata
- retention cleanup

### Step 10
tests
- health
- auth
- latest board
- snapshots query
- export

---

## 18. 受け入れ基準

MVP 完了条件:
- config/env 読み込み成功
- `symbols > 50` を起動拒否
- token 初回取得成功
- collector が市場時間中に動く
- snapshot が DB に蓄積
- `/v1/status` が健全性を返す
- `/v1/boards/{api_symbol}` が latest を返す
- `/v1/snapshots` が履歴を返す
- `/v1/export/sqlite/latest` が frozen DB を返す
- auth なしで 401
- allowlist 外で 403
- secrets が漏れない

---

## 19. 実装者への明示指示

- 発注は実装しない
- remote client に kabu token を見せない
- OpenClaw は relay API のみ叩く
- symbol 登録責任は local relay 側に置く
- 50銘柄制約を hard fail で守る
- export は frozen copy のみ返す
- まずは polling で完成させる

---

## 20. 参照ファイル

この handoff の補助資料:
- `strategies/KABU_RELAY_API_SPEC_20260427.md`
- `strategies/KABU_RELAY_API_IMPLEMENTATION_SPEC_20260427.md`
- `config/kabu_relay_server_example_20260427.json`
- `config/kabu_relay_openapi_like_20260427.yaml`

ただし、**まず読むべき主文書はこのファイル** とする。