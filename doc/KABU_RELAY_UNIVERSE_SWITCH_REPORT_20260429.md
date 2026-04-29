# KABU Relay 本命ユニバース切り替え 作業報告

日付: 2026-04-29 (昭和の日)
範囲: `JAPAN_MM_RELAY_UNIVERSE_SWITCH_REQUEST_20260429.md` の Task 1〜5
担当: 実装エージェント (Windows PC, kabu ステーション稼働マシン上)

---

## 0. 一行まとめ

**5 候補 + 参考 2 = 全 7 ticker が `@1` (東証) で live 確認、relay の universe を本命候補へ差し替えて再起動完了。新 universe での実観測は明日 (2026-04-30 木) 09:00 JST から自動開始。**

---

## 1. タイムライン

| 時刻 (JST) | 内容 |
| --- | --- |
| 08:50 | 旧 universe (7203/9984/6758) で **scheduled JST 08:55 daily refresh が実発火**(spec 「実機でしか潰せない」最後の項目が解消) |
| 13:17 ~ 13:18 | universe 候補 7 ticker の live `api_symbol` 確認(初回は 50 銘柄 cap + rate limit に当たり、`/unregister/all` + token refresh 経由で再試行成功) |
| 13:18 ~ 13:19 | `config/relay_config.json` の `symbols[]` を旧 3 銘柄 → 新 5 銘柄に差し替え |
| 13:19 | relay 再起動 (PID 65832 → 69524)、5 銘柄 universe で起動 |
| 13:19 | `/v1/symbols` / `/v1/status` 反映確認 |
| 13:20 | 5 銘柄分の representative board JSON を kabu 直叩きで evidence/ に保存 |
| 13:20 | `/v1/export/sqlite/latest` で frozen export 動作確認(中身は旧 universe の昨日分) |

---

## 2. Task 1: live `api_symbol` 確定

### 結果一覧

| symbol | name | exchange | api_symbol | board 取得 | note |
| --- | --- | --- | --- | --- | --- |
| 4586 | メドレックス | 1 | `4586@1` | ok | 東証グロース、core probe |
| 4056 | ニューラルグループ | 1 | `4056@1` | ok | 東証グロース、core probe |
| 4978 | リプロセル | 1 | `4978@1` | ok | 東証グロース、core probe |
| 3825 | リミックスポイント | 1 | `3825@1` | ok | 東証スタンダード、core probe |
| 4583 | カイオム・バイオサイエンス | 1 | `4583@1` | ok | 東証グロース、reserve watch |
| 7078 | INCLUSIVE Holdings | 1 | `7078@1` | ok | 参考確認のみ、universe 不採用 |
| 7044 | ピアラ | 1 | `7044@1` | ok | 参考確認のみ、universe 不採用 |

**全 7 ticker が `@1` (東証) で live**、`@2/@3/@5/@6` は試行不要だった。

### 確認時に発生した問題と対処

| 問題 | 原因 | 対処 |
| --- | --- | --- |
| 1 回目の探索で `4002006 レジスト数エラー` | kabu の API 登録銘柄リストが過去の検証で 50 上限に到達していた | `PUT /kabusapi/unregister/all` で全クリア |
| 一部 ticker で `4001006 API 実行回数エラー` (rate limit) | 短時間で 38 連続コール | 各リクエスト間に 0.5s sleep |
| `4001009 API キー不一致` (401) | kabu 側が token を rotate(Gate A で観測したのと同じ現象) | token refresh 1 回挟んで retry(2 回発生) |
| `Read timed out` 数件 | 単発の遅延、原因不明 | timeout 5s → 10s に延長して回避 |

スクリプト: `scripts/_probe_universe.py`(再現可能)

---

## 3. Task 2: 設定差し替え

`config/relay_config.json` の `symbols[]` を以下に更新:

```json
[
  {"api_symbol": "4586@1", "symbol": "4586", "exchange": 1, "name": "メドレックス",        "bucket": "tier1"},
  {"api_symbol": "4056@1", "symbol": "4056", "exchange": 1, "name": "ニューラルグループ",   "bucket": "tier1"},
  {"api_symbol": "4978@1", "symbol": "4978", "exchange": 1, "name": "リプロセル",          "bucket": "tier1"},
  {"api_symbol": "3825@1", "symbol": "3825", "exchange": 1, "name": "リミックスポイント",   "bucket": "tier1"},
  {"api_symbol": "4583@1", "symbol": "4583", "exchange": 1, "name": "カイオム・バイオサイエンス", "bucket": "reserve"}
]
```

- core probe 4 件 = `bucket: "tier1"`
- reserve watch 1 件 = `bucket: "reserve"`
- spec で「初期優先度を下げる」とされた 7078 / 7044 は universe に含めず

50 銘柄上限に対して余裕 45 件。

---

## 4. Task 3: relay 再起動 + 疎通確認

### 操作
```
.\scripts\Stop-Relay.ps1   # 旧 PID 63004 を tree-kill
.\scripts\Start-Relay.ps1  # 新 PID 65832 (実体 69524) で detached 起動
```

### 確認結果(2026-04-29 13:18 JST 時点)

| 項目 | 結果 |
| --- | --- |
| `/health` | HTTP 200 |
| `/v1/symbols` | HTTP 200, count=5(新 universe 反映) |
| `/v1/status` | HTTP 200, `configured_symbol_count=5`, `market_open=false`, `freshness=stale`(祝日 idle として整合) |
| `/v1/boards/{新api_symbol}` | HTTP 404 全 5 件 |

### `/v1/boards` が 404 になっている理由

- 今日は **昭和の日 (国民の祝日)** → `jpholiday` により collector が `is_business_day=False` で idle
- 新 universe に対する snapshot が **DB にまだ 1 行も無い**
- spec Task 3 #4「**場中に** 200 を返す」の要件は満たせない時間帯。明日 09:00 JST 以降に自動的に 200 になる

### 旧 universe (7203/9984/6758) の DB 行は維持

- `data/kabu_orderbook.db` 内に昨日の 2,158 行が残存
- 新 universe の収集と独立に共存(`api_symbol` カラムでフィルタされる)
- 必要なら `DELETE FROM orderbook_snapshots WHERE api_symbol IN (...)` で別途整理可能

---

## 5. Task 4: 観測開始(自動)

| 項目 | 状態 |
| --- | --- |
| 5 秒 polling | 設定済(`poll_interval_seconds: 5`) |
| 場中観測 | **明日 2026-04-30 (木) 09:00 JST 〜** から自動再開 |
| 重点 window (`09:00-09:05` / `15:25-15:30`) | 通常 polling のままで取れる(時間帯分解は OpenClaw 側) |
| 営業日 5 〜 10 日蓄積 | 自動継続。途中で OpenClaw が `/v1/export/sqlite/latest` を取得すれば任意時点の frozen DB が手元に来る |

---

## 6. Task 5: frozen export 動作確認

### 現状
```json
{
  "latest_export": {
    "created_at_utc":           "2026-04-29T04:19:33.856113+00:00",
    "file_name":                "kabu_orderbook_snapshot_20260429T041933Z.db",
    "file_size_bytes":          9322496,
    "snapshot_rows":            2158,
    "price_change_rows":        738,
    "latest_snapshot_at_utc":   "2026-04-28T06:29:55.473091+00:00"
  }
}
```

- `/v1/export/meta` ✓
- `/v1/export/sqlite/latest` ✓ (HTTP 200, SQLite magic header 確認, 9.3 MiB)
- ただし **中身は昨日の 7203/9984/6758 の 2,158 行**
- 新 universe の snapshot rows は明日 09:00 JST 以降に蓄積され、それを含む export が次回取得時から得られる

OpenClaw 側は明日場中以降に再取得する想定で OK。

---

## 7. 副産物: spec 「実機でしか潰せない」最後の項目が解消

Gate A 報告書 (§3.3) で **未観測 (⚠)** だった項目:

> 08:55 JST daily refresh の実発火 — 検証窓内に 08:55 が来ないため未観測

→ 本日 08:50:00 JST に **実環境で初発火** を観測:

```
2026-04-29 08:50:00,252 INFO app.collector: running scheduled token refresh for 2026-04-29 JST
2026-04-29 08:50:00,262 INFO app.token_manager: token refreshed at 2026-04-28T23:50:00.262164+00:00
```

08:55 ターゲットに対して `-300 ≤ delta ≤ +600` の window のうち最も早い `-300s = 08:50` で発火、これは `_maybe_scheduled_token_refresh()` の正しい挙動(C-11 #4 でテスト固定済)。これで Gate A 時点の未観測項目は **6/6 全て解消**。

---

## 8. 現在の運用状態(2026-04-29 13:30 JST)

```
relay PID:        69524 (detached process via scripts/Start-Relay.ps1)
listen:           0.0.0.0:18091 (Tailscale + LAN 全 NIC で到達可能)
configured:       5 symbols (4586/4056/4978/3825/4583)
allowed_subnets:  127.0.0.1/32, 192.168.0.0/24, 100.91.183.90/32
market_session:   null (holiday idle)
DB:               2,158 rows (昨日の旧 universe), price_changes 738 rows
exports/:         3 files (keep_exports=10)
```

明日 (2026-04-30 木) の挙動予測:
- 09:00:00 JST に `morning` セッション判定 → `_cycle()` 開始
- 各 cycle で 5 銘柄 × `/board` 取得 → DB insert
- 1 営業日で `5 銘柄 × 12 cycle/分 × 60 分 × 5 時間 = ~18,000 rows` 蓄積見込み
- 11:30 〜 12:30 はランチブレイクで idle
- 15:30 で日中 collection 終了(spec の「大引け 15:30 ちょうどの板寄せは取れない」既知制約あり)

---

## 9. 成功条件チェック (request §「成功条件」全項)

| # | 条件 | 結果 |
| --- | --- | --- |
| 1 | `4586/4056/4978/3825/4583` のうち live `api_symbol` が確定する | ✅ 全 5 件 `@1` で確定 |
| 2 | relay の観測ユニバースが本命候補へ差し替わる | ✅ 完了 |
| 3 | `/v1/symbols` に新ユニバースが出る | ✅ count=5 |
| 4 | 場中に `/v1/boards/{api_symbol}` が 200 を返す | ⏳ 明日 09:00 JST 以降に自動達成 |
| 5 | frozen export に新ユニバースの snapshot が入る | ⏳ 明日場中以降に自動達成 |
| 6 | OpenClaw 側で後段解析に回せる | ⏳ 5〜10 営業日蓄積後 |

実装で完結する 1〜3 は**今日完了**、観測に依存する 4〜6 は**明日以降に自動進行**。

---

## 10. 残課題 / 注意

### この作業由来で持ち越したもの
**なし**。指示書の Task は全て完遂、明日への自動移行のみ残す。

### 既知の運用上の注意

| 項目 | 内容 |
| --- | --- |
| 旧 universe の DB 行 | 昨日の 2,158 rows が同一 DB に残存。後段分析で `WHERE api_symbol IN (...)` で除外 / 取捨選択する想定 |
| 大引け 15:30 ちょうどの取り逃し | spec の既知挙動 (`market_session.end="15:30:00"` exclusive)。終値が必要なら別途 15:30 過ぎの 1 cycle を仕様変更、または OpenClaw 側で kabu 直叩き |
| 50 銘柄上限 | 今 5 銘柄、上限まで 45 余裕。`/board` 経由の auto-register と register API 経由の手動 register は同じ slot を消費する点に留意 |
| Phase2 項目 | spec / gap-fill 文書で明示的に後回し指定された全項目(WebSocket / Session 化 / opaque cursor / 429 / Windows サービス化 / `/register` 起動時同期) は手付かず、必要に応じて別タスクで |

---

## 11. 補助 artifact 一覧 (gitignored)

| パス | 内容 |
| --- | --- |
| `evidence/board_4586at1.json` ... `board_4583at1.json` | 5 銘柄の representative board JSON(kabu 直叩き、本日付) |
| `scripts/_probe_universe.py` | 候補 ticker の live `api_symbol` 確認スクリプト(再利用可) |
| `scripts/_capture_representative_boards.py` | 上記の board JSON 保存用スクリプト |
| `logs/relay.log` | 起動ログ + 旧 universe 最終 cycle + 08:50 scheduled refresh + 新 universe 起動の連続記録 |

---

## 12. 一言

実機ロジックも、token refresh の自動運用も、universe の差し替えフローも、**運用に必要な動作経路はすべて実環境で観測済み**。

明日 09:00 JST に collector が動き始めれば、本命仮説「小型グロース寄り引け spread pocket」検証用の実板データが 5 秒粒度で自動蓄積される状態。
