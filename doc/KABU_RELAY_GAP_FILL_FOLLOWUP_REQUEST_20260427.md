# KABU Relay ギャップ修正フォローアップ依頼

日付: 2026-04-27
用途: 初回実装レビュー後の不足分を、次の実装エージェントへそのまま依頼するための文書。

---

## 結論

**今回は「全部」ではなく、優先度 1 の不足を先に埋めてください。**

具体的には:
- **今すぐ対応してほしい:** 1, 2, 4, 5, 6
- **今回の完了条件からは外すが、明示が必要:** 3
- **後回しでよい:** NICE / Phase2 項目

つまり、今回のゴールは:
- README / docs の受け入れ基準不足を埋める
- 実運用で困る holiday / file logging / cycle log を入れる
- 実機疎通未確認は **未検証事項として明示** する

---

## 優先順位

### P1: 必ず今回埋める

#### 1. README に `/v1/status` のサンプル応答を追加
必須。

最低限入れるもの:
- curl 実行例
- 200 response 例(JSON)
- 認証ヘッダ例

#### 2. README に `/v1/boards/{api_symbol}` のサンプル応答を追加
必須。

最低限入れるもの:
- curl 実行例
- 200 response 例(JSON)
- 404 の簡単な説明

#### 4. 日本の祝日を collector が休むようにする
必須。

推奨:
- `jpholiday` を依存追加して holiday 判定
- もし依存追加を避けたいなら config ベースの holiday list でもよい
- ただし **祝日に collector が動かない** ことをコードで保証すること

#### 5. `logs/relay.log` へのファイル出力を追加
必須。

要件:
- `logs/` を作る
- `RotatingFileHandler` を使う
- stderr と file の両方へ出してよい
- secret はマスク / 非出力

#### 6. collector cycle start / end ログを追加
必須。

最低限:
- cycle start 1行
- cycle end 1行
- duration / fetched count / error count があるとよい

---

### P1.5: 今回は block 明記でよい

#### 3. 実 kabu ステーション接続での疎通確認
これは **この環境では block** です。

今回やってほしいこと:
- README に「実 kabu 接続は未検証」と明記
- `未実装項目` とは別に、**未検証事項 / Environment Blockers** セクションを作る
- stub / mocked 起動確認しかしていないことを書く
- 後で実機 PC で確認すべき手順を README に追加する

重要:
- これは「隠す」のではなく、**受け入れ時に分かるように明記する** こと

---

## README に追加してほしい章

最低限この章を入れてください。

1. `サンプル API 呼び出し`
2. `サンプル応答`
3. `未実装項目`
4. `未検証事項 / Environment Blockers`
5. `実機 kabu ステーション接続時の確認手順`

---

## 今回は後回しでよい項目

以下は今回の P1 修正には含めなくてよいです。

- `requests.Session` 化
- 401 retry 追加テストの拡充
- `ExportBusyError` テスト
- `KABU_RELAY_ALLOW_DEGRADED` テスト
- scheduled refresh 重複防止テスト
- opaque cursor 化
- WebSocket / SSE / `/v1/stream`
- 明示的 `/register` 同期の collector 組み込み
- Windows サービス化
- 429 rate limit

これらは **Phase2 / quality pass** でよいです。

---

## 今回の納品条件

以下を満たしたら今回の修正は完了です。

- README に `/v1/status` サンプル応答あり
- README に `/v1/boards/{api_symbol}` サンプル応答あり
- README に `未実装項目` セクションあり
- README に `未検証事項 / Environment Blockers` セクションあり
- 日本の祝日判定が collector に入っている
- `logs/relay.log` へファイル出力がある
- collector cycle start/end ログがある
- 実機疎通未確認が明示されている

---

## 返却時にほしい内容

修正完了時は以下を返してください。

1. 変更したファイル一覧
2. README に追加した章の一覧
3. holiday 判定の実装方法
4. logging の出力先とローテーション設定
5. cycle log の出力例
6. 実機未検証の明記箇所
7. まだ残っている後回し項目

---

## 一言まとめ

**今回は「全部」ではない。**

やることは:
- README の受け入れ基準不足を埋める
- holiday / file log / cycle log を実装する
- 実機未検証は blocker として正直に明記する

ここまでやれば、次の実機接続フェーズへ進める品質になります。