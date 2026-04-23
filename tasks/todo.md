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

- [ ] **問題1: apply_end_at が過去の active event の自動 archive**
  - 現状: active 11件のうち id=271 (yamada 4/21 終了), id=270 (rakuten 2026-01-26 終了) が active 残存
  - 対策: `lottery_upsert.apply` に `if apply_end_at < now - 1h → event_status='archived'` を追加
  - 追加: `archive-non-tokyo-metro` を `archive-stale-events` にリネーム + 期間終了 event も対象化
  - 実装 + テスト + push: 20分程度

- [ ] **問題2: disabled adapter 由来の orphan active event の cleanup**
  - 現状: active 11件のうち 9件が amazon / pokecawatch / Twitter 経由 (disabled)
  - 対象: id=275, 266, 238, 229, 194, 168, 151 等
  - 対策: cleanup job で retailer in {amazon, pokecawatch, unknown} or store_name LIKE '@%' を archive
  - 実装 + dry-run → execute: 10分程度

### 🟡 優先度中 (後日)

- [ ] **DryRunNotifier に dedupe check 追加**
  - 現状: dry-run で try_claim を skip するため、既に dedupe 済みの event が "would-send" と表示される
  - 影響: dry-run の予測精度が悪い (2026-04-22 の浜松対応で混乱した)
  - 対策: dry-run 時も dedupe_key を SELECT で確認し、衝突なら would-suppressed と表示

- [ ] **updated_at 無条件 bump 修正**
  - 現状: `lottery_upsert.apply` で confidence_score / official_confirmation_status を無条件で updates dict に入れるため、update() SQL が毎 run 走り updated_at bump
  - 影響: dispatch_updates が全 active event をピックアップ (DB クエリ無駄)。通知は has_sent_with_summary で suppress するので実害小
  - 対策: 値が実際に変わった時だけ updates に入れる (`>=` → `>` or `!=` 比較)

- [ ] **TZ 混在 (first_seen_at UTC vs now JST) 修正**
  - 現状: `lottery_events.first_seen_at` は `DEFAULT CURRENT_TIMESTAMP` (DB サーバ TZ = UTC)、`now = datetime.now()` は JST naive
  - 影響: `dispatch.list_active_since(since=now-3days)` の比較で 9h オフセット。fresh_window 境界で 9h 分の誤差
  - 対策: `lottery_repo.create()` で `first_seen_at=$N` を明示的に渡す、または DB TZ を Asia/Tokyo に設定

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
