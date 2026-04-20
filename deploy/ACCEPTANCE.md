# 受け入れ条件チェックリスト

spec §16 の受け入れ条件を現行実装に突き合わせた結果。

| # | 条件 | 状態 | 根拠 |
|---|---|---|---|
| 1 | 短命タスクで 5 分ごとに cron 実行 | ✅ | `.github/workflows/pokebot.yml` (`cron: "*/5 * * * *"`) |
| 2 | 全 enabled=true ソースが 1 回以上成功で health 記録 | ✅ | `tests/test_sink.py::test_sink_inserts_events_and_records_success` |
| 3 | BOX 抽選イベントが LINE に届く | ✅ | `tests/e2e/test_acceptance.py::test_detect_and_notify_box_lottery` |
| 4 | 同一告知が別ソースから入ったら 10 分後に集約通知 | ✅ | `tests/e2e/test_acceptance.py::test_duplicate_source_becomes_aggregation` |
| 5 | 起動時に日次レポート発火 (JST 09:00 近辺) | ✅ | `tests/test_health.py::test_daily_report_*` |
| 6 | 5 連続失敗で警告 | ✅ | `tests/test_health.py::test_silence_detector_warns_on_5_consecutive_failures` |
| 7 | 再起動後に未送信イベントが再送 | ⚠️ | 短命モードでは「次の cron 実行で自動再送」として担保。`notified_at IS NULL` の DB 永続化で再送。 `tests/e2e/test_acceptance.py::test_unnotified_events_retry_across_ticks` |
| 8 | `.env` が chmod 600 | ⚠️ | GHA Secrets を使うため本番では N/A。`.env` はローカル開発用のみ。 |

## メモ

- ⚠️ は仕様上の「常駐前提」の条件を、短命タスク構成で読み替えた項目。
- テスト件数: 59 passed (unit 56 + e2e 3)。
