# KABU Relay API 仕様書

日付: 2026-04-27
目的: kabuステーションAPI に接続できる別PC上で、板情報を取得し、OpenClaw など別端末からローカルネットワーク経由で安全に参照できる read-only relay API を定義する。

## 1. 結論

今回の用途では、**kabuAPI をそのまま LAN に公開するのではなく、別PC上で read-only relay を1枚かませる** のが最適。

理由:
- kabu の APIPassword / token を他端末へ配らずに済む
- OpenClaw 側は `localhost:18080` 前提から解放される
- 5秒観測や複数銘柄の収集を relay 側で一本化できる
- 将来の Phase1 分析で必要な `latest snapshot`, `history`, `export` を同じ API で出せる
- 発注 API を混ぜず、**観測専用** に固定できる

重要な制約として、**kabuステーションAPI の API登録銘柄リストは REST/PUSH 合算で最大50銘柄** である。しかも情報系リクエストは **要求した銘柄を自動で API登録銘柄リストに載せる** ため、`/board/{symbol}` の polling を使う場合でもこの上限を意識する必要がある。したがって relay の configured universe は **1インスタンスあたり 50 銘柄以下** を前提に設計する。

## 2. スコープ

### やること
- kabuAPI から板情報を取得する
- 取得結果を正規化してローカル保存する
- LAN 内のクライアントへ read-only API として配信する
- collector の健全性、token 状態、データ鮮度を API で見えるようにする

### やらないこと
- 発注
- 訂正 / 取消
- kabu token の外部配布
- WAN 公開
- ブローカー認証情報の中継

## 3. 推奨アーキテクチャ

### 3.1 構成
- **PC-A**: kabuステーションが動く Windows PC
  - kabuステーション
  - relay agent
  - relay API server
  - local SQLite (`kabu_orderbook.db`)
- **PC-B / OpenClaw 側**
  - relay API client
  - snapshot import / analysis

### 3.2 データフロー
1. relay agent が PC-A 上で kabuAPI token を取得
2. relay agent が対象銘柄を 5秒間隔で巡回取得
3. 正規化した snapshot を `kabu_orderbook.db` に保存
4. relay API が latest / history / status / export を LAN に配信
5. OpenClaw 側は relay API だけを叩く

### 3.3 設計原則
- **pass-through proxy ではなく cache-first relay** にする
- 外部クライアントは kabu の raw token を知らない
- relay は **read-only / observation-only** を厳守
- collector と API server は同一プロセスでも分離プロセスでもよいが、責務は分ける
- **1 relay / 1 kabu session あたり active universe は 50 銘柄以下** に抑える
- **銘柄登録の実務責任は local relay 側に持たせ、remote client から直接 kabu register を叩かせない**

## 4. 通信とセキュリティ

## 4.1 listen
- relay API の待受例: `http://0.0.0.0:18081`
- kabuAPI 本体は従来どおり `http://127.0.0.1:18080`

## 4.2 認証
LAN 用途なので、Phase1 は以下で十分。
- `Authorization: Bearer <shared token>`
- 追加で IP allowlist

推奨:
- bearer token は環境変数管理
- allowlist は `192.168.x.0/24` のように subnet 単位で制限
- 無認証運用はしない

## 4.3 禁止事項
- router の port forward をしない
- WAN 公開しない
- APIPassword や kabu Token を API レスポンスに含めない
- relay API に発注系 endpoint を生やさない

## 5. データモデル

relay API の canonical symbol は **`api_symbol`** とする。
- 例: `4582@3`
- `symbol=4582`
- `exchange=3`

### 5.1 latest snapshot の標準形
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

### 5.2 collector status の標準形
```json
{
  "ok": true,
  "server_time_utc": "2026-04-27T09:00:05.500000+00:00",
  "collector": {
    "running": true,
    "mode": "poll",
    "poll_interval_seconds": 5,
    "configured_symbol_count": 12,
    "last_success_at_utc": "2026-04-27T09:00:05.123456+00:00",
    "last_error_at_utc": null,
    "consecutive_error_count": 0,
    "lag_seconds": 0.4
  },
  "kabu": {
    "reachable": true,
    "host": "127.0.0.1",
    "port": 18080,
    "token_status": "valid",
    "token_last_refreshed_at_utc": "2026-04-27T00:01:05+00:00"
  },
  "storage": {
    "db_path": "C:\\kabu-relay\\data\\kabu_orderbook.db",
    "latest_snapshot_at_utc": "2026-04-27T09:00:05.123456+00:00",
    "snapshot_rows": 123456,
    "price_change_rows": 9876
  }
}
```

## 6. API 仕様

すべて `/v1/...` で versioning する。

### 6.1 `GET /health`
用途:
- 死活監視
- 認証前でも最小限の応答を返してよい

レスポンス例:
```json
{"ok": true, "service": "kabu-relay", "version": "v1"}
```

### 6.2 `GET /v1/status`
用途:
- collector 稼働確認
- token freshness
- データ遅延確認

返すもの:
- collector running
- poll interval
- configured symbol count
- last success
- consecutive error count
- kabu reachability
- token status
- latest snapshot timestamp
- stale 判定

### 6.3 `GET /v1/symbols`
用途:
- relay に登録済みの universe 確認

クエリ:
- `bucket=tier1|tier2|controls` 任意

レスポンス例:
```json
{
  "symbols": [
    {"api_symbol": "4582@3", "symbol": "4582", "exchange": 3, "name": "シンバイオ製薬", "bucket": "tier1"}
  ]
}
```

### 6.4 `GET /v1/boards/{api_symbol}`
用途:
- 単銘柄の latest snapshot 取得

例:
- `GET /v1/boards/4582@3`

レスポンス:
- 5.1 の snapshot 形式

### 6.5 `GET /v1/boards`
用途:
- 複数銘柄の latest snapshot 一括取得

クエリ:
- `symbols=4582@3,7078@3,9325@2`
- 未指定なら登録済み全銘柄

レスポンス例:
```json
{
  "count": 3,
  "snapshots": [ ... ]
}
```

### 6.6 `GET /v1/snapshots`
用途:
- 履歴取得

クエリ:
- `symbol=4582@3` 必須
- `from=2026-04-27T00:00:00Z`
- `to=2026-04-27T06:00:00Z`
- `limit=1000`
- `cursor=<opaque>` 任意

レスポンス例:
```json
{
  "symbol": "4582@3",
  "count": 1000,
  "next_cursor": "opaque-token",
  "rows": [ ... ]
}
```

### 6.7 `GET /v1/price-changes`
用途:
- 最良気配変化ログの取得
- quote duration や queue proxy 分析の下流入力

クエリ:
- `symbol=4582`
- `from=...`
- `to=...`
- `limit=1000`

### 6.8 `GET /v1/export/sqlite/latest`
用途:
- OpenClaw 側が frozen snapshot を取り込むための export

仕様:
- relay 側で DB を安全にコピーして返す
- growing DB 本体をそのまま掴ませない

レスポンス:
- `application/octet-stream`
- filename 例: `kabu_orderbook_snapshot_20260427T090005Z.db`

重要:
- **export は必ず frozen copy を返す**
- live DB の直読みは避ける

### 6.9 `GET /v1/export/meta`
用途:
- 最新 export の中身確認

返すもの:
- snapshot timestamp
- row counts
- symbol counts
- DB hash 任意
- file size

### 6.10 `GET /v1/stream` または `/v1/events`
これは Phase2。

推奨:
- Phase1 は不要
- まずは REST pull だけで始める
- 必要なら SSE を追加
- WebSocket は最後でよい

## 7. エラー仕様

### HTTP status
- `200` 正常
- `400` query 不正
- `401` bearer token 不正
- `403` allowlist 外
- `404` symbol 不明
- `409` export 生成中
- `429` rate limit
- `503` kabu 不達 or collector stale

### エラー本文
```json
{
  "error": "symbol_not_found",
  "message": "Unknown api_symbol: 9999@3"
}
```

## 8. 鮮度ルール

relay 側で stale 判定を持つ。

推奨:
- `fresh`: 最終更新が 15秒以内
- `warning`: 15秒超 60秒以内
- `stale`: 60秒超

市場時間外は stale をそのまま異常扱いしないため、status に session 情報を含める。

## 9. collector 仕様

### 9.0 銘柄数上限
- **API登録銘柄リストは REST/PUSH 合算で最大 50 銘柄**
- 情報系リクエストは対象銘柄を自動登録するため、`GET /board/{api_symbol}` の polling でも上限対象になる
- したがって collector は **configured symbols <= 50** を起動前 validation で必須にする
- 推奨は Phase1 では `tier1 + controls` など、**まず 50 を大きく下回る universe** で運用する
- 将来 50 を超える universe を観測したい場合は、**単一 relay で回避しようとせず、relay を分割** するのが第一候補

## 9.1 収集方式
Phase1 推奨は polling。
- 5秒ごとに1巡
- universe は既存 `config/japan_stock_mm_phase1_observation_20260427.json` に従う
- 前場 `09:00-11:30 JST`
- 後場 `12:30-15:30 JST`

## 9.2 token 管理
- 起動時に token 取得
- 毎営業日朝に token refresh
- 401 発生時は 1回だけ自動 refresh して再試行
- それでも失敗したら collector status を degraded にする

## 9.3 保存
最低でも以下を保持。
- `collector_runs`
- `orderbook_snapshots`
- `price_changes`

必要なら追加:
- `api_errors`
- `exports`
- `symbol_registry`

## 10. 最小実装と拡張順

### Phase1 最小実装
- `GET /health`
- `GET /v1/status`
- `GET /v1/symbols`
- `GET /v1/boards/{api_symbol}`
- `GET /v1/boards?symbols=...`
- `GET /v1/snapshots`
- `GET /v1/export/sqlite/latest`

### Phase1.5
- `GET /v1/price-changes`
- `GET /v1/export/meta`
- stale / session status 強化

### Phase2
- SSE または WebSocket
- register/unregister
- push 更新

## 11. OpenClaw 側から見た前提

OpenClaw 側はこの relay に対して以下だけ分かればよい。
- `base_url` 例: `http://192.168.0.20:18081`
- `bearer_token`
- `symbols` universe
- `export` endpoint

つまり、OpenClaw 側は **kabu そのものではなく relay だけを相手にする**。

## 12. 推奨判断

私の推奨はこれ。

- **read-only relay** にする
- **cache-first** にする
- **REST pull-first** にする
- **export endpoint を最初から入れる**
- **発注機能は絶対に入れない**
- **configured universe は 50 銘柄以下に固定する**

この構成なら、今の Phase1 観測要件にぴったり合う。
特に大事なのは、**「別PC上で取れたデータを、そのまま API で見せる」だけでなく、「あとで OpenClaw が frozen snapshot として安全に持ってこられる」こと**。

## 13. この仕様で次に実装するもの

別PCの agent には、まず以下だけ依頼すればよい。
- relay server
- token manager
- board poll collector
- SQLite 保存
- latest/history/export/status API

優先順位:
1. `status`
2. `symbols`
3. `latest boards`
4. `history snapshots`
5. `sqlite export`

---

必要なら次に、これをそのまま実装者へ渡せるように **OpenAPI風の endpoint 一覧** か **FastAPI 用の request/response schema** まで落とす。