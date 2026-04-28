# KABU Relay C-11 実装エージェント向け指示書

日付: 2026-04-28
対象: Windows PC 側で relay 実装コードを保持・実行しているエージェント
目的: Gate A 実機疎通を通過した現行 relay 実装に対して、次段の **C-11 追加テスト** を実装し、必要なら最小限の修正を入れたうえでテストを通す。

---

## 0. 結論

あなたにやってほしいことはシンプルです。

1. relay 実装 repo に対して、C-11 の4本の追加テストを書く
2. テストを書く過程で実装上の小さな不足があれば、**最小限** 修正する
3. `pytest` を回して通す
4. 結果を持ち帰る

今回の主目的は、**実機で通った重要挙動を、再現可能な automated test として固定すること** です。

---

## 1. 背景

Gate A 実機疎通はすでに通過済みです。

外部確認で通ったもの:
- `/health` 200
- `/v1/status` 200
  - `ok=true`
  - `kabu.token_status=valid`
  - `collector.market_open=true`
  - `collector.freshness=fresh`
- `/v1/symbols` 200
  - live symbols は `7203@1`, `9984@1`, `6758@1`
- `/v1/boards/7203@1` 200
  - `stale=false`
  - `freshness_ms < 6000`
  - bid/ask 10段
- `/v1/snapshots?symbol=7203@1&limit=50` 200
- `/v1/export/meta` 200
- `/v1/export/sqlite/latest` 200
- no bearer 401
- wrong bearer 401

つまり relay は **外から使える状態** まで来ています。

次に必要なのは、落ちやすい境界条件をテスト化して、
- token refresh
- export 排他
- degraded 起動
- scheduled refresh 重複防止
を固定することです。

---

## 2. 今回のスコープ

今回やるのは **C-11 の4本だけ** です。

### 実装するテスト
1. `test_collector_401_retry.py`
2. `test_export_busy.py`
3. `test_degraded_boot.py`
4. `test_scheduled_refresh_dedupe.py`

### 今回やらないもの
- WebSocket / SSE
- `/v1/stream` / `/v1/events`
- `requests.Session` 化
- `register_symbols` の deterministic 起動時同期
- opaque cursor 化
- 429 rate limit
- Windows service 化

これらは Phase2 以降です。今回の対象ではありません。

---

## 3. 作業方針

### 原則
- **テストを先に書く** でもよい
- ただし、今回に限っては Gate A 実機観測がすでにあるので、**観測済み挙動をテストへ反映する** のが正しい順序
- テストを書くために不足する部分があれば、**実装修正は最小限に留める**
- 本番 API 契約を勝手に変えない
- 実機で通った挙動を壊さない

### 実装姿勢
- 今回は「新機能追加」ではなく **品質固定**
- 大きなリファクタは不要
- テストしやすい seam を足す程度ならよい
- 既存の public contract を壊す変更は避ける

---

## 4. テスト 1: collector 401 retry

### ファイル名
`tests/test_collector_401_retry.py`

### 目的
collector が board 取得時に一度 `401 Unauthorized` を受けても、
- token refresh
- 1回だけ retry
- 200 で復帰
- snapshot 保存まで通る
ことを確認する。

### 背景
実運用では token 期限切れが起きうる。ここで collector が止まると relay の価値が大きく落ちる。

### シナリオ
1. 初回 `fetch_board()` が 401 を返す
2. token manager が refresh を1回実行する
3. 同じ board fetch を retry する
4. retry 後は 200 と正常 board payload を返す
5. collector が board を正規化し、snapshot を保存する

### 期待する検証点
- token refresh 呼び出し回数 = 1
- board retry 回数 = 1
- snapshot row が1件以上保存される
- `consecutive_error_count` が不必要に積み上がらない
- collector loop 全体が failure へ落ちない

### 推奨実装方法
- `kabu_client.fetch_board()` を stub / fake 化する
- 1回目だけ `HTTPError(401)` 相当を投げる
- 2回目で正常 board JSON を返す
- token manager の refresh 関数呼び出し回数を assertion する
- snapshot repository / DB insert の結果も見る

### テストで確認すべき payload
正常 board は実機に合わせた最低限の形にする。
以下のフィールドが正規化可能であること。
- best bid / ask
- bid / ask 10段
- current price
- volume
- current price time

live symbol 名自体は `7203@1` を使ってもよいが、テスト上はダミー symbol でも可。重要なのは **形**。

### PASS 条件
- 401 → refresh → retry → 200 → snapshot 保存 が通る

---

## 5. テスト 2: export busy

### ファイル名
`tests/test_export_busy.py`

### 目的
`/v1/export/sqlite/latest` が同時に2回叩かれた時、
- 1本だけ export を実行
- 後続は `409 export_in_progress`
となることを確認する。

### 背景
frozen export は運用上重要。並列要求で破損ファイルや0 byteファイルが出るのは避けたい。

### シナリオ
1. export 処理を遅延させた状態で2本並列に起動
2. 先行 request が lock / busy flag を取得
3. 後続 request は 409 を返す
4. 先行 request の export は正常完了する

### 期待する検証点
- 片方は HTTP 200
- 片方は HTTP 409
- 409 body は `error=export_in_progress`
- 成功側は有効な SQLite bytes を返す
- 中途半端なファイルが残らない

### 推奨実装方法
- export service のコア関数に intentional delay を入れられるなら mock する
- FastAPI の test client か、service 層の直接呼び出しでもよい
- 並列性は thread / asyncio / futures のどれでもよいが、再現性を優先

### PASS 条件
- 200/409 が安定再現
- 失敗側が 500 にならない

---

## 6. テスト 3: degraded boot

### ファイル名
`tests/test_degraded_boot.py`

### 目的
`KABU_RELAY_ALLOW_DEGRADED=1` のとき、初回 token 取得失敗でも relay が boot を継続できることを確認する。

### 背景
kabu 側が一時不調でも、プロセス自体を完全停止させず health/status を出したいケースがある。

### シナリオ
1. 起動時 token fetch を失敗させる
2. `KABU_RELAY_ALLOW_DEGRADED=1` を有効にする
3. API server が listen 開始まで到達する
4. `/health` は 200
5. `/v1/status` は degraded 相当の state を返す

### 必須の比較シナリオ
同じ token failure 条件で、
- `ALLOW_DEGRADED=1` なら起動継続
- flag なしなら fail fast

この差を必ず確認すること。

### 期待する検証点
- degraded ON でプロセスが落ちない
- degraded OFF で従来どおり起動失敗
- health は alive を返す
- status から token failure を読み取れる

### 注意
degraded boot は「発注機能なし」「read-only relay」であることが前提で比較的安全。
この前提を壊す変更はしないこと。

### PASS 条件
- degraded ON/OFF の振る舞い差が明確に確認できる

---

## 7. テスト 4: scheduled refresh dedupe

### ファイル名
`tests/test_scheduled_refresh_dedupe.py`

### 目的
同一営業日内で `08:55 JST` の scheduled refresh 判定が複数回呼ばれても、refresh は1回だけになることを確認する。

### 背景
market loop や timer tick の都合で同一時間帯判定が複数回走る可能性がある。毎回 refresh してはいけない。

### シナリオ
1. 時刻 source を固定またはモックする
2. 同一日の `08:55` 近辺判定を複数回実行
3. refresh 呼び出し回数が1回だけであることを確認
4. 日付を翌営業日に進める
5. 再び refresh 1回だけ実行されることを確認

### 期待する検証点
- 同日 refresh 回数 = 1
- 翌営業日では再度1回実行
- 同一日の repeated tick で refresh storm が起きない

### 推奨実装方法
- token manager / scheduler が参照する clock を差し替える
- もし現状差し替え seam が無ければ、最小限の dependency injection を足す

### PASS 条件
- daily refresh dedupe が再現性をもって確認できる

---

## 8. 実装時に許される修正

テストを成立させるため、以下の種類の修正は許可する。

- 時刻 source の注入
- export lock 状態の観測しやすさ向上
- collector / token manager の小さな dependency injection
- testability 向上のための関数分離
- mock しやすくするためのラッパ追加

ただし、以下は避ける。
- API 契約の無関係な変更
- 大規模リファクタ
- 本番設定の変更を前提にしたテスト
- Phase2 項目の先行実装

---

## 9. 推奨作業順

この順で進めることを推奨する。

1. `test_collector_401_retry.py`
2. `test_export_busy.py`
3. `test_degraded_boot.py`
4. `test_scheduled_refresh_dedupe.py`
5. `pytest` 全体

理由:
- 401 retry は最も運用事故に直結する
- export busy はデータ破損防止の意味で重要
- degraded boot は fail-fast と対になる重要挙動
- scheduled refresh dedupe は最後に切り出しやすい

---

## 10. 実行コマンドの期待

少なくとも以下を実行して結果を返してほしい。

```bash
pytest -q
```

可能なら、対象テストだけの実行結果も欲しい。

```bash
pytest -q tests/test_collector_401_retry.py
pytest -q tests/test_export_busy.py
pytest -q tests/test_degraded_boot.py
pytest -q tests/test_scheduled_refresh_dedupe.py
```

---

## 11. 納品時に返してほしいもの

以下をまとめて返すこと。

1. **変更ファイル一覧**
2. **追加したテストファイル一覧**
3. **実装側に入れた補助修正の要約**
4. **`pytest` 結果**
5. **各テストの要点**
   - 何をモックしたか
   - 何を assertion したか
6. **まだ残っている未対応項目**
   - あれば列挙

---

## 12. 受け入れ条件

今回の受け入れ条件は以下。

- 4本の C-11 テストが追加されている
- `pytest` が通る
- 実機で確認済みの挙動と矛盾しない
- 無関係な API 契約変更がない
- Phase2 項目を勝手に混ぜていない

---

## 13. 参考文書

以下を参照してよい。

- `strategies/KABU_RELAY_C11_TEST_PLAN_20260428.md`
- `results/kabu_relay_gate_a_pass_20260428.md`
- `results/kabu_relay_external_probe_20260428_auth.md`
- `results/kabu_relay_external_probe_20260428_auth.json`

---

## 14. 最後に

今回のタスクは、relay を「動く」から「再現可能に正しい」へ進めるためのものです。

**実機で通った重要挙動を、テストとして固定する**。
これが目的です。

余計な拡張はしなくていいです。C-11 に集中してください。

