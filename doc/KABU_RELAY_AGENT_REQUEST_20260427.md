# KABU Relay 実装エージェント向け依頼文

以下をそのまま実装タスクとして受け取ってください。

---

## 依頼

Windows PC 上で動く **kabuステーションAPI 用 read-only relay サービス** を実装してください。

目的は、kabuAPI に接続できるローカルPC上で板情報を取得し、それを LAN 内の別端末から安全に参照できるようにすることです。

この relay は **観測専用** です。発注機能は実装しません。

---

## 最重要制約

1. **発注機能を実装しないこと**
   - 注文
   - 訂正
   - 取消
   は対象外です。

2. **kabuAPI を直接 LAN 公開しないこと**
   - relay 経由でのみ外部公開すること

3. **APIPassword / kabu token を外部へ露出しないこと**
   - API レスポンスに含めない
   - ログに平文で出さない
   - export DB に保存しない

4. **50銘柄制約を必ず守ること**
   - API登録銘柄リストは REST/PUSH 合算で最大 50 銘柄
   - `/board/{symbol}` polling でもこの制約の内側で運用すること
   - `configured symbols > 50` は **起動失敗** にすること

5. **銘柄登録の責務はローカル relay 側に置くこと**
   - リモートクライアントから kabu の register API を直接叩かせないこと

6. **SQLite export は frozen copy のみ返すこと**
   - growing live DB を直読みさせないこと

---

## まず読むべき文書

最優先:
- `strategies/KABU_RELAY_COMPLETE_HANDOFF_20260427.md`

次に参照:
- `strategies/KABU_RELAY_API_SPEC_20260427.md`
- `strategies/KABU_RELAY_API_IMPLEMENTATION_SPEC_20260427.md`
- `config/kabu_relay_server_example_20260427.json`
- `config/kabu_relay_openapi_like_20260427.yaml`

**主文書は `KABU_RELAY_COMPLETE_HANDOFF_20260427.md` です。**
他は補助です。

---

## 実装ゴール

以下を満たす read-only relay を作成してください。

### 収集
- kabu token をローカルで取得
- 5秒 polling で board を収集
- 前場 `09:00-11:30 JST`
- 後場 `12:30-15:30 JST`
- 取得結果を SQLite 保存

### API
- `GET /health`
- `GET /v1/status`
- `GET /v1/symbols`
- `GET /v1/boards/{api_symbol}`
- `GET /v1/boards?symbols=...`
- `GET /v1/snapshots`
- `GET /v1/price-changes`
- `GET /v1/export/meta`
- `GET /v1/export/sqlite/latest`

### セキュリティ
- bearer token auth
- IP allowlist
- `/health` 以外は保護

### export
- frozen SQLite copy を返す
- latest export metadata を API で確認可能

---

## 推奨スタック

- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic
- sqlite3

MVP は単一プロセスで構いません。

---

## 実装対象ディレクトリ例

```text
kabu-relay/
  app/
  config/
  data/
  exports/
  logs/
  tests/
  requirements.txt
  README.md
```

詳細な推奨ファイル構成は handoff 文書に従ってください。

---

## 期待する成果物

最低限これを納品してください。

1. 実装コード一式
2. `README.md`
   - 起動方法
   - 環境変数
   - config 例
   - API 一覧
3. `requirements.txt`
4. `config/relay_config.example.json`
5. SQLite schema
6. 最低限のテスト
7. 起動確認ログまたは実行結果メモ

---

## 受け入れ条件

以下を満たしたら完了です。

- config/env を読んで起動できる
- `symbols > 50` を起動時 reject する
- token 初回取得成功で collector が動く
- snapshot が DB に蓄積する
- `/v1/status` が健全性を返す
- `/v1/boards/{api_symbol}` が latest を返す
- `/v1/snapshots` が履歴を返す
- `/v1/export/sqlite/latest` が frozen DB を返す
- auth なしで 401
- allowlist 外で 403
- secrets が漏れない

---

## 実装時の判断ルール

迷ったら以下を優先してください。

1. 安全性
2. 観測専用であること
3. 50銘柄制約の順守
4. frozen export の正しさ
5. 単純で壊れにくい実装

WebSocket や push 最適化は後回しで構いません。まずは polling で完成させてください。

---

## 最後に返してほしいもの

実装完了時には以下を返してください。

1. 実装したファイル一覧
2. 起動方法
3. 必要な環境変数一覧
4. 実装した endpoint 一覧
5. 未実装項目があればその一覧
6. 残課題・注意点

以上。