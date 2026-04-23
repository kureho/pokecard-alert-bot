# Pokebot TODO (2026-04-23 引き継ぎ)

## セッション間引き継ぎ

### 直近の完了事項 (commit 履歴参照)
- `27a03d5` fix+feat: カードラボ浜松重複通知対策 / 東京近郊フィルタ / quiet hours (21-10 JST)
- `e7f7aa1` fix: 長期失敗 adapter 5個を disable + Twitter pacing 2s→10s
- `b0ae857` fix: pokemoncenter_online_guide を disable (health check 専用で価値なし)
- `600181d` fix: Twitter syndication 7アカウントを一時無効化 (全 429)

### 現在の稼働 adapter (8個)
pokemon_official_news / pokemoncenter_online_lottery / pokemoncenter_store_voice /
c_labo_blog (東京近郊8店舗のみ) / nyuka_now_news / rakuten_books_entry /
yamada_lottery / hbst_lottery

### 無効化中の adapter (seeds.DISABLED_SOURCES, 13個)
yodobashi / biccamera / amiami / amazon_search / pokecawatch_chusen /
pokemoncenter_online_guide / twitter_× 7

## 次セッションで対応する項目

### 🔴 優先度高 (即やる)

- [x] **問題1: apply_end_at が過去の active event の自動 archive** (2026-04-23 実装済)
  - `lottery_upsert.apply` に `APPLY_END_GRACE=1h` 超過で `event_status='archived'` を追加
  - `archive-non-tokyo-metro` を `archive-stale-events` にリネーム。reason を 3 カテゴリ化
  - 新規テスト: test_apply_end_at_past_is_archived_on_create / test_existing_active_event_archived_when_apply_end_passes 等

- [x] **問題2: disabled adapter 由来の orphan active event の cleanup** (2026-04-23 実装済)
  - `archive-stale-events` に `_DISABLED_ADAPTER_RETAILERS` (amazon/pokecawatch/yodobashi/biccamera/amiami/unknown) と `store LIKE '@%'` 判定を追加
  - dry-run → execute は GHA workflow_dispatch で `cleanup_execute=true` 選択時のみ
  - **次セッションで dry-run 実行 → 件数確認 → 本番 execute の運用手順を踏むこと**

### 🟡 優先度中 (後日)

- [x] **DryRunNotifier に dedupe check 追加** (2026-04-23 実装済)
  - `NotificationRepo.is_dedupe_claimed()` 追加 (READ-only)
  - dispatch_for_event / _dispatch_deadline_for_event の dry-run 分岐で ndk 衝突時は `result.suppressed += 1`
  - ログに `[DRY_RUN] would-suppressed event=... (dedupe claimed)` 出力

- [x] **updated_at 無条件 bump 修正** (2026-04-23 実装済)
  - `lottery_upsert.apply` で confidence_score / official_confirmation_status / confidence_level / evidence_score / evidence_summary を「値が変化した時だけ」updates に入れる
  - 内容不変の再観測は touch_last_seen 経由 (updated_at bump なし、last_seen_at のみ更新)

- [x] **TZ 混在 (first_seen_at UTC vs now JST) 修正** (2026-04-23 実装済)
  - `LotteryEventRepo.create()` / `update()` に optional `now` パラメータを追加。COALESCE で渡された now 優先、未指定時は CURRENT_TIMESTAMP にフォールバック
  - `lottery_upsert.apply` で now を両方に渡し、DB タイムスタンプ 3 種 (first_seen_at / last_seen_at / updated_at) を JST naive で揃える

### 🔵 優先度低 (nice to have)

- [ ] silence_detector の FAILURE_ALERT_THRESHOLD 5 → 10 (flaky source 対策)
- [ ] `tests/storage/test_repos.py:45` の未使用 `sid` を修正 (pre-existing lint warning)
- [ ] `__main__.py` 756 行の refactor (job 関数を services/ 配下に移動)
- [ ] coverage ツール (pytest-cov) 導入

### 🚫 復旧要監視 (いずれ再開したい)

- [ ] Twitter syndication 429 の根本対応: 公式 API v2 移行 (月 1500 tweet 無料枠) or 代替経路
- [ ] Yodobashi / Amiami / Amazon の US IP block 回避: self-hosted runner (日本リージョン) or proxy
- [ ] Biccamera / pokecawatch_chusen の構造変更対応

## 運用メモ

- 稼働中の GHA cron: 30分間隔 (full) + 15分間隔 (fast)
- cron 遅延は GitHub 側で稀に 1-2h 発生する。workflow_dispatch で手動 kick 可能
- quiet hours: 21:00-10:00 JST は全 LINE 抑止 (daily_summary / silence 含む)
- MAX_NOTIFY_PER_DAY=6, MAX_NOTIFY_PER_RUN=2
- DAILY_REPORT_JST 既定 10:00 (quiet hours 明け直後)

## ロールバック

- archive の巻き戻し SQL: `deploy/ACCEPTANCE.md` 参照
- adapter の disable 解除: `seeds.DISABLED_SOURCES` と `__main__.LOTTERY_WATCH_ADAPTERS` から該当名を外す
- コード巻き戻し: `git revert <commit>` 後 `git push`

## 教訓アーカイブ

詳細は `tasks/lessons.md` を参照:
- カードラボ浜松の通知重複 (last_seen_at 依存の dedupe key は NG)
- quiet hours 設計 (全 LINE 経路で共通ガード)
- GHA US IP block / Twitter 429 の外部要因
