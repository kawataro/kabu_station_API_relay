# KABU Relay 文書セット

日付: 2026-04-27
用途: 実装エージェントへ渡す書類一式の読み順と役割を明示する。

---

## 1. まず渡す主文書

### `strategies/KABU_RELAY_COMPLETE_HANDOFF_20260427.md`
- これが **主文書**
- まず最初に読む
- これだけで全体像と実装要件が分かる

---

## 2. そのまま貼る依頼文

### `strategies/KABU_RELAY_AGENT_REQUEST_20260427.md`
- 実装エージェントへそのまま渡す依頼文
- 何を作るか、何を作らないか、返してほしいものがまとまっている

---

## 3. 補助仕様

### `strategies/KABU_RELAY_API_SPEC_20260427.md`
- relay の基本設計思想
- API の役割
- セキュリティ原則

### `strategies/KABU_RELAY_API_IMPLEMENTATION_SPEC_20260427.md`
- 実装要件の詳細
- token manager / collector / auth / export などの仕様

---

## 4. 設定ファイル例

### `config/kabu_relay_server_example_20260427.json`
- relay config の JSON 例
- symbols / session / storage / auth などの初期値の参考

### `config/kabu_relay_openapi_like_20260427.yaml`
- OpenAPI 風 endpoint 定義
- request / response schema の参考

---

## 5. 受け入れ確認

### `strategies/KABU_RELAY_ACCEPTANCE_CHECKLIST_20260427.md`
- 実装納品物をレビューするための checklist
- 漏れ確認用

---

## 6. 推奨の渡し方

実装エージェントには次の順で渡す。

1. `strategies/KABU_RELAY_AGENT_REQUEST_20260427.md`
2. `strategies/KABU_RELAY_COMPLETE_HANDOFF_20260427.md`
3. `config/kabu_relay_server_example_20260427.json`
4. `config/kabu_relay_openapi_like_20260427.yaml`
5. `strategies/KABU_RELAY_ACCEPTANCE_CHECKLIST_20260427.md`

補助で必要に応じて:
- `strategies/KABU_RELAY_API_SPEC_20260427.md`
- `strategies/KABU_RELAY_API_IMPLEMENTATION_SPEC_20260427.md`

---

## 7. 一言まとめ

- **依頼文** = `KABU_RELAY_AGENT_REQUEST_20260427.md`
- **主仕様書** = `KABU_RELAY_COMPLETE_HANDOFF_20260427.md`
- **レビュー用** = `KABU_RELAY_ACCEPTANCE_CHECKLIST_20260427.md`

この3つが中心。