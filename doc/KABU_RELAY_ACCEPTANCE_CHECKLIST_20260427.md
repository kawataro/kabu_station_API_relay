# KABU Relay 受け入れチェックリスト

日付: 2026-04-27
用途: 実装エージェントの納品物を確認するためのチェックリスト

---

## A. 基本構成
- [ ] relay は kabu 接続可能な **Windows PC 上** で動く
- [ ] kabuAPI 本体と relay API の port が分離されている
- [ ] リモート側は relay API だけを使う設計になっている
- [ ] 発注機能が含まれていない

## B. 50銘柄制約
- [ ] `symbols <= 50` validation がある
- [ ] `symbols > 50` で起動失敗する
- [ ] polling でも 50銘柄制約の内側で運用する説明がある
- [ ] リモートから直接 register API を叩かせない設計になっている

## C. 認証・セキュリティ
- [ ] `Authorization: Bearer <token>` 認証がある
- [ ] IP allowlist がある
- [ ] `/health` 以外は保護されている
- [ ] APIPassword が config に平文保存されていない
- [ ] bearer token が config に平文保存されていない
- [ ] kabu token が API レスポンスに出ない
- [ ] secrets がログに平文で出ない
- [ ] WAN 公開前提になっていない

## D. token 管理
- [ ] 起動時に token を取得する
- [ ] 401 時に 1回だけ refresh retry する
- [ ] 営業日朝 refresh の設計がある
- [ ] token 状態が status で見える

## E. collector
- [ ] 5秒 polling が実装されている
- [ ] 前場/後場の session gate がある
- [ ] 市場時間外は idle 動作する
- [ ] board を正規化して DB 保存する
- [ ] best quote change を `price_changes` に記録する
- [ ] stale 判定がある

## F. DB
- [ ] `collector_runs` がある
- [ ] `orderbook_snapshots` がある
- [ ] `price_changes` がある
- [ ] `(symbol, collected_at)` などの index がある
- [ ] `raw_json` を保持している

## G. API endpoint
- [ ] `GET /health`
- [ ] `GET /v1/status`
- [ ] `GET /v1/symbols`
- [ ] `GET /v1/boards/{api_symbol}`
- [ ] `GET /v1/boards`
- [ ] `GET /v1/snapshots`
- [ ] `GET /v1/price-changes`
- [ ] `GET /v1/export/meta`
- [ ] `GET /v1/export/sqlite/latest`

## H. export
- [ ] live DB ではなく frozen copy を返す
- [ ] export metadata が取れる
- [ ] export file 名が分かる
- [ ] 古い export の retention が考慮されている

## I. 運用資料
- [ ] `README.md` がある
- [ ] 起動手順がある
- [ ] 必要 env が列挙されている
- [ ] config 例がある
- [ ] endpoint 一覧がある
- [ ] 未実装項目が明示されている

## J. 実動確認
- [ ] 起動確認が取れている
- [ ] 少なくとも1銘柄で snapshot 取得確認がある
- [ ] `/v1/status` の応答例がある
- [ ] `/v1/boards/{api_symbol}` の応答例がある
- [ ] export 実行確認がある

---

## 最終判定
- [ ] MVP 合格
- [ ] 要修正あり
- [ ] 再提出必要
