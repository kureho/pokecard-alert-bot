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
