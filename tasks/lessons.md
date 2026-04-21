# Lessons Learned (pokecard-alert-bot)

## 2026-04-20 LINE 無料枠 140/200 を初回テストで消費した事故

### 何が起きたか
- 初回 workflow を本番 secrets で走らせたら、pokemon-card.com の過去 140 件の news が全件 LINE push された
- LINE Messaging API 無料枠は月 200 通。その 70% を意図しない「テスト」で燃焼
- ユーザーが欲しい「BOX 抽選/再販」ではなく、大会告知/イベント情報が大半で、実用価値もゼロ

### 根本原因
1. 外部通知を行うバッチを本番モードで初回実行する前に **dry-run フェーズが存在しなかった**
2. ソースが返す件数の事前見積もり (N件とれるか) を計算していなかった
3. LINE 無料枠 200/月という消費制約を設計段階で反映していなかった
4. auto mode だったとしても、消費系リソース (API 枠・LINE・SMS・課金) は通常のコード実行とは別次元の慎重さが必要だった

### 再発防止ルール (ブロッキング要件)
- **外部通知系バッチを本番 secrets で実行する前に必ず dry-run を走らせる**
  - `DRY_RUN=1` 環境変数で LINE/SMS/メール等の送信をログ置換にする実装をデフォルトで用意する
  - 最初の本番実行の前に **何件送る予定か** を必ずログで確認する
- **無料枠・API 上限を設計時点で明記する**
  - spec に「月あたり N 通まで」を書く
  - Bot に `MAX_NOTIFY_PER_RUN` / `MAX_NOTIFY_PER_DAY` の上限を持たせ、超過時は送信せずログに残す
- **初回スクレイプ洪水防止パターン (seed モード) を最初から組み込む**
  - 新しいソースが追加された瞬間、過去データは `notified_at` 済みで DB 投入、LINE には流さない
  - このプロジェクトでは fix 済み (sink.py の is_first_run 判定)
- **通知対象の kind / priority を allowlist で厳格に絞る**
  - このプロジェクトでは fix 済み (NotifyWorker.NOTIFY_KINDS)

### Claude Code への学び
- 「動かして確認する」は良い原則だが、**外部への副作用 (通知・課金・メール) を伴うバッチでは別物**
- auto mode は実行許可であって、消費資源に対するフリーパスではない
- ユーザーの個人資源 (LINE 枠、API クレジット、メール送信数) を扱うときは、事前に「これを実行すると N 件消費される」を宣言してから実行する
- dry-run モードが存在しない状態で本番実行するのは、ハンマーを目隠しで振るのと同じ

## 2026-04-21 SCHEMA_SQL に列追加したとき `CREATE INDEX` が `ALTER TABLE` より前にあると既存 DB で落ちる

### 何が起きたか
- `lottery_events` に `product_name_normalized` 列を追加するのに `CREATE TABLE IF NOT EXISTS` だけでは既存 DB に列が作られない
- `ALTER TABLE ADD COLUMN IF NOT EXISTS` を用意したが、SCHEMA_SQL 内の順序で `CREATE INDEX ... ON lottery_events(product_name_normalized)` が先に実行されて `UndefinedColumnError`

### ルール
- **冪等 migration SQL を同じ SCHEMA_SQL に書くときは、`ALTER TABLE` を対応する `CREATE INDEX` より先に配置する**
- 「新規 DB は CREATE TABLE で済み、既存 DB は ALTER で追随」というパターンを使う場合、依存する index / FK 等のオブジェクトは ALTER の後ろに置く
- テストで TRUNCATE しているだけの test DB は既存 DB と同じ扱い (テーブル定義は再作成されない) なので、順序バグは test 一回で顕在化する

## 2026-04-21 TOP ページ → 個別告知 URL パターンマッチの調査優先度

### 教訓
- 「/information/」「/news/」一覧ページが JS 動的だと 1KB しか取れない (例: yamada-denki.jp の information root)
- 一覧ページが空に見えたら **TOP ページに貼られているバナーリンク** を最初に確認する
- ヤマダの場合: `yamada-denki.jp/` トップ内に `/information/YYMMDD_pokemon-card/` が href 直書きされている
- regex 抽出で個別告知 URL を取り、各ページに fetch して本文解析するほうが確実

### 類似パターンで確認すべき箇所
- ヨドバシカメラ (403 for US IP): Twitter `@Yodobashi` 経由が現実的
- エディオン (TOP 直 link なし): 告知が不定期・Twitter `@edion_official` 経由が現実的
- あみあみ (403 for US IP): 代替経路検討
