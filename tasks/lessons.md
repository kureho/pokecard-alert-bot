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

## 2026-04-22 update 通知が同一内容で 6時間ごとに再発火 (カードラボ浜松事案)

### 何が起きたか
- ユーザーから「カードラボ浜松の通知がめっちゃ来る」報告
- 同じ告知 (同じ商品・同じ応募期間) の update 通知が 6 時間おきに LINE に届いていた
- 1 event につき最大 4回/日、MAX_NOTIFY_PER_DAY=6 の枠を特定店舗で消化

### 根本原因
`services/notification.py` で update 通知の dedupe_key 生成に `last_seen_at` を使っていた:
```python
content_version = event.last_seen_at.isoformat(timespec="minutes")
```
`last_seen_at` はスクレイプ毎に `CURRENT_TIMESTAMP` へ bump されるため、内容が全く変わっていなくても 6時間 (UPDATE_COOLDOWN) 経過ごとに dedupe_key が更新され、`try_claim` が成功し再送される構造だった。

### 再発防止ルール
- **通知 dedupe_key の content_version は "ユーザーに見える情報" (商品名・期間・sales_type・status・条件) のハッシュから組む。内部タイムスタンプ (last_seen_at / updated_at) は絶対に含めない**
- **update 通知では「同一 payload_summary が既に sent 済みか」を try_claim 前に確認する**。万一 dedupe_key 設計が崩れても、文面ベースで二重送信を防げる
- cooldown (時間ベース) は最大頻度の上限であり、**内容不変ならそもそも発火しない**ことを保証する設計が正しい

### 類似パターンで確認すべき箇所
- `deadline` / `result` など今後追加する通知 type でも、content_version を時刻由来にしない
- schema の `first_seen_at` と `last_seen_at` を混同しない (first は通知の鮮度判定用、last は再観測用で**両者はユーザー向け情報ではない**)

## 2026-04-22 quiet hours (21:00-10:00 JST) 導入

### 背景
ユーザー要望「夜21時から朝10時までは送らないで」。睡眠中に LINE 通知で起こされないように、全 LINE 送信経路に共通で時間帯抑止をかける。

### 設計のポイント
- **純粋関数** `lib/quiet_hours.is_quiet_hours(now: datetime)` として切り出し、dispatcher 側は 1 行でガードするだけに留める
- **抑止対象は全 LINE 通知** (new / update / deadline / daily_summary / silence)。一部だけ抑止すると「夜中に監視アラートで起きる」「早朝に daily summary で起きる」といった抜けが残る
- **daily_summary の既定時刻を 10:00 に変更** (09:00 のままだと quiet hours 内で永久に発火しない)
- **GHA TZ=Asia/Tokyo 前提**。hour 判定は naive datetime を使うので、TZ 設定が外れると境界がズレる。TZ=Asia/Tokyo が deploy ルール化されていることが前提

## 2026-04-26 GitHub Actions usage 月次オーバーフロー対策（pokebot 側）

### 何が起きたか
- 2026-04-23 に Actions 月次無料枠（2000分）超過で全 repo 停止
- 4月実測の真犯人は pokeprice (820分/42%) と pokecard-alert-bot (716分/37%) の 2 台体制
- pokeprice は別途 cron 削減 push 済（commit `90d02a2`、月 820 → 約 360 分）
- 5/1 自動リセット待ちの間に pokebot 側も削減して再発防止する

### 削減前後の cron

| lane | 旧 cron | 新 cron | 月実行回数 |
|---|---|---|---:|
| Full lane (全 21 adapter + body fetch) | `0,30 * * * *` | `0 * * * *` | 1440 → 720 |
| Fast lane (公式 + 主要販路 entry_page) | `15,45 * * * *` | `30 * * * *` | 1440 → 720 |
| 合計 | 30分間隔 | 60分間隔 (Full と Fast を 30分オフセット) | 2880 → 1440 (-50%) |

### 実測値と予測

- 直近 100 success run の平均所要時間: Full 5.88分 / Fast 5.62分（yaml コメントの「Fast 3分」は古い情報。adapter 増加で実態は両 lane ほぼ同じ）
- 4月実測: 月 716 分
- 5月予測: 約 358 分 (-50%)

### 速報性低下の許容判断

- 旧: Full と Fast が交互に 15 分ごとに走っていたので、新規告知の検知遅延は最大 15 分
- 新: Full と Fast が交互に 30 分ごと → 新規告知の検知遅延は最大 30 分
- LINE 通知頻度は `MAX_NOTIFY_PER_DAY=6` で別途制限されているため、削減で通知が減ることはあっても増えることはない
- ユーザー判断 (kureho、2026-04-26): 案 A (両 lane 1 時間おき、30分オフセット) を採用

### 検証手順 (今回実施したもの)

1. `gh run list --status success --limit 100` で Full / Fast 別の所要時間を実測集計
2. `gh workflow run pokebot.yml -f job=fast -f dry_run=true` で DRY_RUN 検証 → `notify_dispatch: new=0 update=0 suppressed=9` で LINE 送信抑止を確認 (`feedback_dryrun_before_external_push.md` 準拠)
3. yaml の cron + Determine job ロジックの cron 文字列マッチを同時更新（cron 変更時の見落とし定番ポイント）
4. 5/1 までは Actions 無料枠超過で schedule 発火しないため、最初の本番発火は 5/1 以降に観察する

### ルール (再発防止)

- **GitHub Actions の使用量は月単位で算定される。schedule 系 workflow を増やしたり cron 間隔を狭めたりするときは、月実行回数 × 1回あたりの分数 で 2000 分枠への影響を必ず試算する**
- **cron 式を変更する時は、cron 行だけでなく、`github.event.schedule` で cron 文字列をマッチしている分岐ロジックも同時に更新する**（今回も Determine job の `if` を更新する必要があった）
- **削減前に必ず Full / Fast 別の所要時間を実測する**。yaml コメントは作成時点の見積もりなので、半年以上経つと実態とずれる可能性が高い

### 巻き戻し方法

```bash
cd ~/claude/pokecard-alert-bot
git revert <commit-sha>
git push origin main
```

cron 変更は次の schedule 発火タイミングまで猶予がある。Full lane なら最大 1 時間待てば次の発火を観察できる。
