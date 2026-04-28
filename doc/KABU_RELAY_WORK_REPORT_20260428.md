# KABU Relay 作業報告

日付: 2026-04-28
範囲: spec 受領から C-11 テスト完了 / 常駐運用開始まで
担当: 実装エージェント (Windows PC, kabu ステーション稼働マシン上)

---

## 0. 一行まとめ

**MVP 実装 → Gate A 実機疎通 PASS → C-11 追加テスト PASS → detached 常駐稼働中。残るは Phase2 のみ。**

---

## 1. 全体タイムライン

| フェーズ | 内容 | 状態 |
| --- | --- | --- |
| Phase 0 | spec 6 文書を読み込み、要件理解 | 完了 |
| Phase 1 | MVP 実装一式 (app/, routes, collector, token mgr, export, auth, tests) | 完了 |
| Phase 1.5 (P1 fillin) | jpholiday / file logging / cycle log / README サンプル応答 | 完了 |
| D-14/15/18 (gap fill) | log fallback 修正 / extra_closed_dates 追加 / 絶対パス推奨明記 | 完了 |
| Gate A | 実機疎通 8 ステップ全件実行 | **PASS** |
| 常駐セットアップ | Start/Stop/Status PowerShell スクリプト + Operations 章 | 完了 |
| Allowlist 拡張 | OpenClaw 側 IP (100.91.183.90) 追加 | 完了 |
| Gate C-11 | 4 種の追加 automated test | **PASS** |

---

## 2. 実装成果物

### 2.1 アプリケーション本体

```
app/
  main.py              # FastAPI entrypoint, lifespan による起動シーケンス
  settings.py          # config + env loader, symbols<=50 / port衝突 hard validation
  auth.py              # bearer + IP allowlist middleware (/health のみ exempt)
  models.py            # Pydantic レスポンスモデル
  db.py                # SQLite connection helpers (WAL モード)
  schema.sql           # 初期 schema (orderbook_snapshots / price_changes / collector_runs / api_errors / exports)
  collector.py         # JST セッション gate (祝日含む) + 5秒 polling + 板正規化 + price_change 検出
  token_manager.py     # token state, refresh policy
  kabu_client.py       # /token + /board + /register (発注系なし)
  export_service.py    # frozen SQLite export (VACUUM INTO + backup() フォールバック + retention)
  status_service.py    # /v1/status の集約
  routes/
    health.py            # GET /health (no auth)
    status.py            # GET /v1/status
    symbols.py           # GET /v1/symbols
    boards.py            # GET /v1/boards/{api_symbol}, GET /v1/boards
    snapshots.py         # GET /v1/snapshots
    price_changes.py     # GET /v1/price-changes
    export.py            # GET /v1/export/meta, GET /v1/export/sqlite/latest
  repositories/
    snapshots.py
    price_changes.py
    collector_runs.py
```

### 2.2 設定 / 運用資材

| ファイル | 用途 |
| --- | --- |
| `config/relay_config.example.json` | 例 config(実機 Gate A の発見を反映: `kabu.host="localhost"`, `listen_port=18091`, `extra_closed_dates`)|
| `requirements.txt` | fastapi, uvicorn, pydantic, requests, jpholiday, tzdata (Windows), pytest, httpx |
| `scripts/Start-Relay.ps1` | .env ロード + bearer 自動生成/読込 + detached 起動 + PID 記録 |
| `scripts/Stop-Relay.ps1` | tree-kill (taskkill /F /T) + port-holder fallback |
| `scripts/Status-Relay.ps1` | UP/DOWN, PID, uptime, /health probe |
| `README.md` | クイックスタート、API 仕様、サンプル応答、Operations、Gate A 結果、On-machine 確認手順 |
| `.gitignore` | data/, exports/, logs/, evidence/, .env, .venv |

### 2.3 テスト

| ファイル | 件数 | 内容 |
| --- | --- | --- |
| `tests/test_settings.py` | 8 | 50 銘柄 cap, env override, port衝突, secret 不在 |
| `tests/test_health.py` | 1 | /health no-auth |
| `tests/test_auth.py` | 4 | 401 (no/wrong bearer), 403 (allowlist 外), 200 |
| `tests/test_status_and_symbols.py` | 3 | /v1/status のシェイプ + secret 漏洩なし、/v1/symbols 全件 + bucket フィルタ |
| `tests/test_boards.py` | 6 | latest board 200/404, bulk, unknown symbol 400 |
| `tests/test_snapshots.py` | 4 | history, cursor invalid, limit 5000 cap |
| `tests/test_export.py` | 3 | meta empty, frozen DB SQLite header, meta after export |
| `tests/test_collector_normalization.py` | 8 | 板正規化, market session (前場/後場/昼休み/週末/祝日/extra_closed_dates), staleness |
| `tests/test_collector_401_retry.py` ★C-11 | 2 | 401→refresh→retry→200 path, 持続 401 時の無限ループ防止 |
| `tests/test_export_busy.py` ★C-11 | 2 | サービス層並列 ExportBusyError, ルート層 409 envelope |
| `tests/test_degraded_boot.py` ★C-11 | 5 | fail-fast vs DEGRADED, on_start=false パス |
| `tests/test_scheduled_refresh_dedupe.py` ★C-11 | 4 | 同日 dedupe, window 境界, disabled 時, token_mgr 上の state 配置 |
| **計** | **50** | **全 PASS** |

---

## 3. Gate A 実機疎通結果

### 3.1 実施情報

- 実施日時: 2026-04-28 14:23 JST(後場場中)
- 実施銘柄: 7203@1 (トヨタ自動車), 9984@1 (ソフトバンクG), 6758@1 (ソニーG)
- 実施時間: 約 5 分の検証 + その後常駐稼働継続中

### 3.2 PASS 条件 (全 4/4 達成)

| # | 条件 | 結果 |
| --- | --- | --- |
| 1 | `kabu.token_status == "valid"` | ✅ |
| 2 | snapshot 行数の単調増加 (30 秒で +21 行) | ✅ |
| 3 | `/v1/boards/{api_symbol}` で `stale: false` | ✅ |
| 4 | 401 / 403 / 200 想定どおり | ✅ |

### 3.3 spec で「実機でしか潰せない」とされた 6 項目の解消状況

| 項目 | 状態 |
| --- | --- |
| `POST /kabusapi/token` 形状 | ✅ `{"ResultCode":0,"Token":"<32 chars>"}` |
| `GET /board/{sym}` フィールド名 | ✅ `Buy1..Sell10`, `Price`/`Qty`, `CurrentPrice`/`VWAP` 等仕様どおり |
| 401→refresh→retry 実トリガ | ✅ 検証中複数回観測, retry 後 `fetched=3 errors=0` |
| 08:55 JST daily refresh | ⚠ 時刻外、未観測。同一の `TokenManager.refresh()` パスは 401 経路で動作確認済 |
| `VACUUM INTO` 並行競合 | ✅ live DB に書き込み中の export 成功, fallback 不要 |
| 非ループバック allowlist | ⚠ 単一ホスト検証のみ (`10.255.255.0/30` で 403 確認, OpenClaw 配備時に 100.91.183.90/32 で再確認推奨) |

### 3.4 実機で初めて分かった重要事項 (例 config に反映済)

| 発見 | 影響 | 対応 |
| --- | --- | --- |
| **kabu は Host header `127.0.0.1` を拒否**(`400 Invalid Hostname`)。`localhost` のみ受け付ける | spec 通りの `kabu.host=127.0.0.1` だと board fetch 全失敗 | `config/relay_config.example.json` の `kabu.host` を **`localhost`** に変更 |
| **kabu は port 18081 を sandbox 用に kernel HTTP.sys 予約済** | spec の relay listen_port=18081 は bind 失敗 | listen_port を **`18091`** に変更 |
| **spec の Phase1 universe (4582@3 等) は 2024 年に上場廃止済** | kabu が `4002001 not found` を返す | 検証用 universe を live 銘柄 (7203/9984/6758) に置換、本番運用時に再確定が必要 |

### 3.5 証跡 (`evidence/`, gitignore 済)

| ファイル | サイズ | 内容 |
| --- | --- | --- |
| `relay.log` | 21 KB | startup → 1 cycle 以上, cycle start/end, token refresh, 401 retry |
| `v1_status.json` | 775 B | `token_status=valid`, `freshness=fresh`, `market_open=true` |
| `v1_boards_7203.json` | 1.4 KB | 板 10 段 + best/mid/spread/depth, `stale=false` |
| `kabu_raw_board_7203.json` | 2.5 KB | kabu 生 JSON (normalize_board の前提検証用) |
| `exported.db` | 568 KB | frozen SQLite (magic header OK, 124 rows) |

---

## 4. データ正確性検証

実機で kabu 生 JSON と relay 出力を **同一タイムスタンプ (`collected_at`) で突き合わせ**:

| カテゴリ | 結果 |
| --- | --- |
| top-of-book (bid/ask price/qty) | kabu raw と完全一致 |
| 10 段ラダー (40 値: 20 levels × price/qty) | mismatch 0 |
| `current_price` / `vwap` / `trading_volume` | 完全一致 |
| 計算系 (mid_price / spread / spread_pct / bid_depth_5_jpy / ask_depth_5_jpy) | 浮動小数点で diff 0.00e+00 |

**API が提供するデータは正確**。kabu 応答は加工せず `raw_json` で丸ごと保持しているため、後段で別の指標に再計算可能。鮮度は polling 由来で最大 5 秒、`freshness_ms` で API がクライアントに開示する。

---

## 5. 現在の運用状態

```
relay PID:        71764
listen:           0.0.0.0:18091 (Tailscale + LAN 全 NIC で到達可能)
uptime:           ~80 分 (14:30 JST 起動)
allowed_subnets:  127.0.0.1/32, 192.168.0.0/24, 100.91.183.90/32
DB:               data/kabu_orderbook.db (~10 MiB, 2,400+ rows)
exports/:         3 ファイル (keep_exports=10)
logs/:            relay.log (rotating 10 MiB × 5)
```

- 後場 15:30 JST で collector は idle に遷移済 (snapshot は止まる、API は引き続き応答)
- 明日 (2026-04-29) は **昭和の日 (国民の祝日)** のため、jpholiday により collector は終日 idle のはず
- 翌営業日 2026-04-30 (木) 09:00 JST から自動再開、08:55 JST に scheduled token refresh が発火する想定
- detached process なので、このセッションが切れても relay は走り続ける(reboot まで)

---

## 6. アーキテクチャ要点

### 6.1 cache-first relay (pass-through ではない)

```
kabu本体 ──5秒polling──▶ collector ──▶ ローカル SQLite ◀── /v1/* (全部ここを読む)
                                                       ▲
                                                       └── /v1/export/* は frozen copy を返す
```

クライアントが `/v1/*` を叩いても kabu には届かない。常にローカル DB 経由。
- 鮮度: 最大 5 秒(`freshness_ms` で開示)
- kabu 一時不達でも relay は直近データを返せる
- 同一データを複数クライアントで共有

### 6.2 セキュリティ二段ロック

すべての `/v1/*` は **bearer + IP allowlist の両方** を要求。`/health` のみ exempt。

- bearer (`hmac.compare_digest` で定数時間比較)
- IP allowlist (`server.allowed_subnets`, CIDR 表記)
- secrets (kabu APIPassword / token / bearer) は config / DB / log / API レスポンスに **一切出さない設計** (テストで検証済み)

### 6.3 銘柄 50 上限の hard fail

`config.symbols` が 50 を超えると Pydantic validation で `ConfigError`、process は起動拒否。kabu の REST/PUSH 合算 50 銘柄上限の防御。

### 6.4 frozen export

`/v1/export/sqlite/latest` は live DB を直接掴ませず、`VACUUM INTO` (失敗時 backup API fallback) で別ファイルに焼き、それを返却。`exports/` 配下に retention (`keep_exports`) で保持。

---

## 7. 残タスク (Phase2 / 後回し指定)

すべて spec / gap-fill 文書で **明示的に後回し指定** されているもの:

| 項目 | 指定元 | 優先度 |
| --- | --- | --- |
| WebSocket / SSE / `/v1/stream` | spec §6.10 | 低 |
| `requests.Session` 化 (HTTP keep-alive) | gap-fill | 低 |
| `register_symbols` の collector 起動時同期 | spec §8 | 中 (deterministic 銘柄登録が必要になったら) |
| opaque cursor 化 | spec §10.6 | 低 (現状は raw id で機能) |
| 429 rate limit | spec §7 (optional) | 低 |
| Windows サービス化 / Task Scheduler 自動登録 | spec §17 | 中 (reboot 後の自動復帰必要なら) |

加えて運用上の判断ポイント:

| 項目 | 判断 |
| --- | --- |
| Phase1 universe の live 銘柄での再確定 | 別途決定が必要 (現在の 3 銘柄は検証用) |
| OpenClaw 側からの bearer 経由 `/v1/status` 以降の疎通最終確認 | 別経路で bearer 配布後、OpenClaw 側で実施 |
| 08:55 JST scheduled refresh の実環境観測 | 翌営業日 (2026-04-30 木) で実観測可能 |

---

## 8. 受け入れ条件チェック (spec の checklist 全項)

### A. 基本構成
- [x] relay は kabu 接続可能な Windows PC 上で動く
- [x] kabuAPI 本体と relay API の port が分離 (18080 / 18091)
- [x] リモート側は relay API だけを使う設計
- [x] 発注機能なし

### B. 50 銘柄制約
- [x] `symbols <= 50` validation あり
- [x] `symbols > 50` で起動失敗
- [x] polling でも 50 銘柄制約の内側で運用する説明あり (README)
- [x] リモートから直接 register API を叩かせない設計

### C. 認証・セキュリティ
- [x] `Authorization: Bearer <token>` 認証
- [x] IP allowlist
- [x] `/health` 以外は保護
- [x] APIPassword が config に平文保存されていない (env 経由のみ)
- [x] bearer token が config に平文保存されていない
- [x] kabu token が API レスポンスに出ない (テストで検証)
- [x] secrets がログに平文で出ない
- [x] WAN 公開前提になっていない (LAN + Tailscale のみ)

### D. token 管理
- [x] 起動時に token 取得
- [x] 401 時に 1 回だけ refresh retry (テスト + 実機観測)
- [x] 営業日朝 refresh の設計 (08:55 JST, dedupe あり)
- [x] token 状態が status で見える

### E. collector
- [x] 5 秒 polling
- [x] 前場/後場の session gate
- [x] 市場時間外は idle 動作
- [x] board を正規化して DB 保存
- [x] best quote change を `price_changes` に記録
- [x] stale 判定 (15s/60s)

### F. DB
- [x] `collector_runs` / `orderbook_snapshots` / `price_changes` あり
- [x] `(symbol, collected_at)` 等の index
- [x] `raw_json` を保持

### G. API endpoint (全 9 件)
- [x] GET /health
- [x] GET /v1/status
- [x] GET /v1/symbols
- [x] GET /v1/boards/{api_symbol}
- [x] GET /v1/boards
- [x] GET /v1/snapshots
- [x] GET /v1/price-changes
- [x] GET /v1/export/meta
- [x] GET /v1/export/sqlite/latest

### H. export
- [x] live DB ではなく frozen copy を返す
- [x] export metadata 取得可能
- [x] export file 名が分かる
- [x] 古い export の retention (`keep_exports`)

### I. 運用資料
- [x] README.md
- [x] 起動手順 (env, config, scripts/)
- [x] 必要 env が列挙されている
- [x] config 例
- [x] endpoint 一覧
- [x] 未実装項目が明示されている (README "Not implemented" 章)
- [x] 未検証事項が明示されている (README "Real-machine verification status" 章)

### J. 実動確認
- [x] 起動確認
- [x] 少なくとも 1 銘柄で snapshot 取得確認
- [x] `/v1/status` の応答例 (README + Gate A 証跡)
- [x] `/v1/boards/{api_symbol}` の応答例 (README + Gate A 証跡)
- [x] export 実行確認

### 最終判定
- [x] **MVP 合格**

---

## 9. 数字で見るスケール

| 指標 | 値 |
| --- | --- |
| Python ファイル (アプリ) | 17 |
| テストファイル | 12 |
| テストケース | 50 |
| schema テーブル | 5 |
| HTTP endpoint | 9 |
| 環境変数 | 9 (必須 2, 任意 7) |
| 1 日の収集量 (3 銘柄, 5 秒 polling, 場中 5h) | ~10,800 rows / day / 3 symbols |
| DB 増分目安 | ~10 MiB / day |

---

## 10. 一言

実装フェーズ・実機検証フェーズ・テスト固定フェーズの 3 段すべて完了。

`動く` から `再現可能に正しい` まで進んだ。

残るは Phase2 と運用判断だけ。
