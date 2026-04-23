# pokecard-alert-bot

ポケモンカードのBox抽選・再販情報を監視し、LINE で通知する個人用 Bot。

## 概要

- GitHub Actions cron（5分毎）で起動するスケジュール実行型
- 状態管理は Supabase Postgres
- 通知は LINE Messaging API

## 必要な環境変数

`.env.example` をコピーして `.env` を作成する。

| 変数 | 用途 |
|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API のチャネルアクセストークン |
| `LINE_USER_ID` | 通知先の LINE User ID |
| `DATABASE_URL` | Supabase Postgres 接続文字列 |
| `LOG_LEVEL` | ログレベル（既定 `INFO`） |
| `DAILY_REPORT_JST` | 日次サマリの送信時刻 JST（既定 `09:00`） |
| `DISCORD_WEBHOOK_URL` | (オプション) Discord sidecar。未設定なら無効 |

### Discord sidecar (オプション)

LINE は無料枠 200通/月の制約があるため、**同じ通知を Discord にもミラー送信**して監視ログ代わりに使える。Discord は無料・無制限。

- 閾値・dedupe・quiet hours は LINE と同じ (質優先)。LINE が送らないものは Discord にも送らない
- LINE 側が dedupe / cap / quiet で suppress した event は Discord にも流れない
- Discord 送信失敗は fire-and-forget。LINE 送信には影響しない

**セットアップ手順:**
1. Discord サーバ設定 → 連携サービス → ウェブフック → 「新しいウェブフック」
2. 対象チャネルを選び URL をコピー
3. GitHub → Settings → Secrets and variables → Actions → New repository secret
4. Name: `DISCORD_WEBHOOK_URL`、Value: コピーした URL
5. 次回 cron から Discord へもミラー送信される

## ローカル開発

Python 3.12 が必要。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

ローカルで実行する場合は Postgres（Supabase もしくは手元の Postgres）に接続できる `DATABASE_URL` を `.env` に設定する。

## デプロイ

デプロイは GitHub Actions 経由のみ。`main` への push で cron ワークフローが有効化される。手動実行は `workflow_dispatch` から。
