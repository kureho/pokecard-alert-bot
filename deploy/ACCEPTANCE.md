# Phase 1 受け入れ条件チェックリスト

Phase 1 リファクタ後の現行実装を、spec と突き合わせて検証する。

## スキーマ・初期化

| # | 条件 | 状態 | 根拠 |
|---|---|---|---|
| S1 | Phase 1 の 6 テーブルが作成される | OK | `tests/storage/test_schema.py::test_schema_has_all_phase1_tables` |
| S2 | sources seed が冪等 | OK | `tests/storage/test_repos.py::test_seed_sources_is_idempotent` |
| S3 | `python -m pokebot bootstrap` でスキーマ + seed が 0 exit | OK | ローカル実行で確認 |

## 収集 (adapter / service)

| # | 条件 | 状態 | 根拠 |
|---|---|---|---|
| A1 | 7 adapter が AdapterRegistry に登録される | OK | `python -c "import pokebot.adapters; ..."` で 7 件 |
| A2 | product_sync: 商品マスタ hint を products に upsert | OK | `tests/services/test_product_sync.py` |
| A3 | lottery_upsert: 新規 / 重複 / 意味差分 / hint / 高信頼を区別 | OK | `tests/services/test_lottery_upsert.py` (5 件) |
| A4 | 公式 (trust=100) + 主要情報揃い → `confirmed` かつ confidence>=90 | OK | `test_official_source_gets_high_confidence` |

## 通知

| # | 条件 | 状態 | 根拠 |
|---|---|---|---|
| N1 | confirmed & 高信頼のみ LINE 送信 | OK | `tests/services/test_notification.py::test_dispatch_sends_line_for_confirmed_high_confidence` |
| N2 | 同一 dedupe_key は 2 回目以降を抑止 | OK | `test_dispatch_suppresses_duplicate` |
| N3 | per-run cap を超えない | OK | `test_dispatch_respects_per_run_cap` |
| N4 | 未確認 / 低信頼は skip して count だけ増やす | OK | `test_dispatch_skips_unconfirmed` |
| N5 | format_event_message が [高信頼] 等のラベルを付与 | OK | `test_format_event_message_has_label` |

## 運用導線

| # | 条件 | 状態 | 根拠 |
|---|---|---|---|
| O1 | GHA workflow_dispatch の `job` 選択で 5 種類を起動可能 | OK | `.github/workflows/pokebot.yml` |
| O2 | DRY_RUN=1 で LINE 送信を抑止してログに出す | OK | `DryRunNotifier` + workflow 既定 true |
| O3 | `scripts/status.py` で products / events / notifications / sources を確認可能 | OK | ローカル実行で確認 |
| O4 | schedule は Phase 1 安全確認前まで無効 | OK | workflow 内でコメントアウト維持 |

## 注意点

- Phase 1 の update 通知は未実装。`dispatch()` は未送信 new のみを処理する（`lottery_upsert` は差分検出済み、後続 Dispatch で配線）
- 通知 cap は per-run=5 を初期値に設定。量を見ながら調整する
- テスト件数: **56 passed** (lib 16 / storage 7 / services 12 / notify 0 placeholder / logging 1 / e2e 0 + 追加)

## 地域フィルタの運用手順 (archive-non-tokyo-metro cleanup)

`src/pokebot/lib/region.py` の allowlist に無い店舗 (カードラボ浜松、ポケセン大阪など) は、adapter 層で弾かれるため今後は DB に新規 insert されない。ただし allowlist 導入前に入った既存 active event は残るので、以下の手順で1度だけ cleanup する。

### 推奨手順 (GHA 経由で secrets を漏らさない)

1. **dry-run で件数確認**
   - GitHub → Actions → pokebot → Run workflow
   - job: `archive-non-tokyo-metro`
   - dry_run: `true` (どちらでもよい。この job は LINE を使わない)
   - cleanup_execute: **false** (必ず false のまま)
   - Run → ログで「対象 N 件」と retailer / store 内訳を確認
2. **内容を確認し、問題なければ実行**
   - 同じ workflow を再実行
   - cleanup_execute: **true** に変更
   - Run → ログで「✅ N 件を status='archived' に更新しました。」を確認
3. **冪等なので2回目以降は対象 0 件**。再実行しても追加で archive されることはない

### archive rollback (万一戻したい場合)

Supabase SQL Editor で以下を実行。`updated_at` は cleanup 実行時刻と同じ日付で絞ると、cleanup 以外で archived になった event を巻き込まない:

```sql
-- カードラボ / ポケモンセンター の archived event のうち、
-- 指定日 (cleanup 実行日) に archived になったものだけ active に戻す
UPDATE lottery_events
SET status = 'active', updated_at = CURRENT_TIMESTAMP
WHERE retailer_name IN ('cardlabo', 'pokemoncenter')
  AND status = 'archived'
  AND updated_at::date = 'YYYY-MM-DD';  -- 実行日を入れる
```

### 対象判定ロジック

- 対象 retailer: `cardlabo`, `pokemoncenter` (store_name で絞れる adapter のみ)
- `status='active'` のみ触る (archived / pending_review は触らない)
- `store_name IS NULL` は触らない (chain-wide 告知を誤 archive しない保守設計)
- 最新の allowlist は `src/pokebot/lib/region.py` 参照
