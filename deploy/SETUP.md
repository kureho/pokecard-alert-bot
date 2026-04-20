# pokebot セットアップ手順

GitHub Actions + Supabase (Postgres) + LINE Messaging API で動かす最小構成。

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

## 4. 動作確認

- Actions タブ → `pokebot` ワークフロー → Run workflow で手動発火
- ログで `source=xxx count=N` が出ていれば正常
- 初回起動時に `CREATE TABLE IF NOT EXISTS` が自動実行されるので migration 手順は不要

## 5. スケジュール

- `*/5 * * * *` (UTC) で 5 分ごとに実行
- `concurrency.cancel-in-progress: true` で重複起動を防止
- 1 ジョブは `timeout-minutes: 4` で強制終了

## 6. 停止・一時停止

- 完全停止: `.github/workflows/pokebot.yml` の `on.schedule` をコメントアウトして push
- 一時停止: Actions タブ → pokebot → `...` → Disable workflow

## 7. 挙動メモ

- Daily report: JST 09:00 近辺の tick で前日の検知件数サマリを 1 回だけ送信 (`daily_reports` テーブルで重複排除)
- Silence detector: 各ソースで 5 連続失敗 or 24h 検知ゼロが続くと警告通知 (6h 内は抑制)
- 未送信イベントは `notified_at IS NULL` で残るので、LINE 送信失敗時も次の tick で自動再送

## 8. ローカル開発

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

# ローカル実行 (.env に DATABASE_URL / LINE_* を書く)
python -m pokebot
```

`.env` はリポジトリに含めない (`.gitignore` 済)。本番は GitHub Secrets を使う。
