# pokebot セットアップ手順

GitHub Actions + Supabase (Postgres) + LINE Messaging API で動かす Phase 1 構成。

## 1. Supabase プロジェクト作成

- <https://supabase.com/> にログインし New project を作成
- Region: `Northeast Asia (Tokyo)` / Plan: `Free`
- Database password は控えておく
- 作成後、左メニュー Project Settings → Database → Connection string → **Session pooler** を選び `URI` をコピー
  - 形式: `postgresql://postgres.xxxx:PASSWORD@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres`
  - これが `DATABASE_URL` になる

## 2. LINE チャネル

- <https://developers.line.biz/> で Messaging API チャネル作成
- Channel access token (long-lived) を発行 → `LINE_CHANNEL_ACCESS_TOKEN`
- 自分のユーザー ID (Uxxxxx) を Webhook or Basic ID から取得 → `LINE_USER_ID`

## 3. GitHub リポジトリ

```bash
gh repo create pokecard-alert-bot --private --source=. --remote=origin --push
```

Settings → Secrets and variables → Actions で以下を登録:

- `DATABASE_URL`
- `LINE_CHANNEL_ACCESS_TOKEN`
- `LINE_USER_ID`

任意の環境変数（workflow 内でも上書き可）:

- `MAX_NOTIFY_PER_RUN` (デフォルト 10 / Phase 1 推奨 5)
- `MAX_NOTIFY_PER_DAY` (デフォルト 150)
- `DRY_RUN` (`1` で LINE 実送信を抑止してログ出力のみ)

## 4. 初期化（bootstrap）

```bash
# ローカルから 1 度だけ実行
DATABASE_URL=... python -m pokebot bootstrap
```

これで

- スキーマ (products / product_aliases / sources / lottery_events / lottery_event_sources / notifications) が作成される
- sources テーブルに 7 個のソース（公式系 4 / 小売系 2 / 店舗系 1）が seed される

GHA からも `workflow_dispatch` で `job: bootstrap` を指定すれば同じ挙動。

## 5. ジョブ構成

`python -m pokebot <job>` で実行。`<job>` は:

| job | 役割 |
|---|---|
| `product-sync` | ポケモン公式 products ページから商品マスタを upsert |
| `lottery-watch` | 公式ニュース・ポケセンオンライン/店舗・ヨドバシ・ビック各 adapter から抽選候補を取得し lottery_events に upsert |
| `notify-dispatch` | confirmed & 高信頼のみを LINE に送信（dedupe + per-run / per-day cap） |
| `all` | 上記 3 つを順に実行。cron からはこれを使う想定 |
| `bootstrap` | スキーマ + sources seed のみ |

## 6. 動作確認

- Actions タブ → `pokebot` ワークフロー → Run workflow で手動発火
- 初回は `dry_run=true` のまま動かし、LINE 送信相当のログを確認する
- `python scripts/status.py events` / `sources` / `notifications` で DB 側の状態を CLI で確認

## 7. スケジュール

- Phase 1 は安全確認が取れるまで `on.schedule` をコメントアウトしている
- 再開時は `.github/workflows/pokebot.yml` の該当行を戻し、30 分間隔から検証を始める

## 8. 停止・一時停止

- 完全停止: `.github/workflows/pokebot.yml` の `on.schedule` をコメントアウトして push
- 一時停止: Actions タブ → pokebot → `...` → Disable workflow

## 9. 挙動メモ

- 通知フィルタ: `official_confirmation_status == 'confirmed'` かつ `confidence_score >= 90` のみ LINE 発火
- dedupe: `notifications.dedupe_key` の一意制約でイベント単位に 1 回だけ送信
- 失敗時再送: notifications row は `sent_at IS NULL` で残るので、次回 tick で再送される
- cap: per-run / per-day の両方で洪水防止。Phase 1 は per-run=5 を推奨

## 10. ローカル開発

```bash
# PostgreSQL 16 を用意
brew install postgresql@16
brew services start postgresql@16
createdb pokebot_test

# 依存をインストール
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# テスト
pytest -v

# ローカル実行 (.env に DATABASE_URL / LINE_* / DRY_RUN=1 を書く)
python -m pokebot all
```

`.env` はリポジトリに含めない (`.gitignore` 済)。本番は GitHub Secrets を使う。
