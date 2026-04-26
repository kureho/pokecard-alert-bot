# pokebot cron 削減作業 引き継ぎメモ（2026-04-26）

## このセッションを開始する前に必ず読むもの

1. このファイル全体
2. `~/.claude/projects/-Users-oharakureho-claude/memory/project_japan_stock_bot_split.md`（GitHub Actions 全体棚卸し）
3. `tasks/lessons.md`（プロジェクト固有の教訓）
4. `~/claude/CLAUDE.md`（ワークスペース全体ルール）

## 背景

- 2026-04-23 から GitHub Actions の月次 usage 枠超過で全 repo 停止
- 2026-04-26 GitHub Billing UI で確認: 純 usage 超過のみ（payment failure ではない）→ **5/1 自動リセット確定**
- 4月実測値で真犯人は **pokeprice + pokecard-alert-bot の2台体制**
- **pokeprice 側は cron 削減 push 済（commit `90d02a2`、月1846→888分予測）**
- **pokebot 側は未対応**。このメモは pokebot 側の作業のため

## pokebot の現状（2026-04-26 確認）

### .github/workflows/pokebot.yml の cron

```yaml
- cron: "0,30 * * * *"   # Full lane (21 adapter + body fetch、6〜8分)
- cron: "15,45 * * * *"  # Fast lane (7 adapter のみ、3分程度)
```

合わせて **15分おき = 1日96回 = 月2880回実行**。

### 4月の usage 実測

- $6.81（GitHub Billing UI、4/1〜4/29 集計）
- 約 716分 / 月（$0.0095/分換算）
- Free 枠 2000分の **約36%** を占有

### 1回の実行時間

- 直近成功 run: 193秒（gh run view 24953077705）
- yaml コメントによると Full 6〜8分、Fast 3分程度

## やること

### Step 1: 直近の成功 run を Full / Fast 別に集計

```bash
cd ~/claude/pokecard-alert-bot
gh run list --workflow pokebot.yml --status success --limit 50 --json databaseId,createdAt,event,name
# 各 run の所要時間を計算 (createdAt → updatedAt)
# event=schedule のものを Full(0,30) / Fast(15,45) で分けて平均化
```

これで「Full 平均 X 分」「Fast 平均 Y 分」を確定させる。

### Step 2: 削減方針をユーザーに提示して選んでもらう

| 案 | cron 変更 | 月削減 | 速報性への影響 |
|---|---|---:|---|
| **A** | Full `0 * * * *` (1時間おき) / Fast `30 * * * *` (1時間おき) | -50% | LINE通知最大1時間遅れ |
| **B** | Full `0 * * * *` (1時間おき) / Fast 撤去 | -75% | 全adapter 1時間ごと一回のみ |
| **C** | Fast 撤去（Full のみ 30分おき維持） | -50% | Fast lane の高速通知は失われる |

**案A 推奨**（速報性と usage のバランス）。最終判断はユーザー。

### Step 3: workflow_dispatch + dry_run=true で削減後の挙動を検証

```bash
# 変更前に DRY_RUN で1回手動実行して挙動確認
gh workflow run pokebot.yml -f job=fast -f dry_run=true
gh workflow run pokebot.yml -f job=all -f dry_run=true
```

`feedback_dryrun_before_external_push.md`（LINE枠140/200燃焼の教訓）に従う。

### Step 4: yaml 編集 → コミット → push

コミットメッセージ例:
```
chore(ci): pokebot cron を 15分おき → 1時間おきに削減

GitHub Actions monthly usage 削減のため。
- Full lane: 0,30 → 0 (毎時0分のみ)
- Fast lane: 15,45 → 30 (毎時30分のみ)
- 月実行回数 2880 → 1440 (-50%)、約 716分 → 358分予測

詳細は tasks/lessons.md。
```

### Step 5: tasks/lessons.md に教訓追記

「2026-04-26: GitHub Actions usage 月次オーバーフロー対策（pokebot 側）」として、
- 変更前後の cron
- 月実測 716分 → 358分予測
- 速報性低下の許容判断（誰が決めたか）
- 巻き戻し方法（`git revert <sha>`）

を残す。

### Step 6: MEMORY.md の `project_japan_stock_bot_split.md` を更新

- 「pokecard-alert-bot 側 — 次セッションのタスク」セクションを「対応済」に書き換え
- 5月予測の数値を更新

## 注意点（必読）

### LINE 無料枠の罠

- `MAX_NOTIFY_PER_DAY: "6"` は LINE 200/月制限の安全圏
- cron 削減は **取得頻度** の話。送信頻度（=通知数）は MAX_NOTIFY_PER_DAY で別途制限されているので、削減で通知が増えることはない

### concurrency group が `pokebot`

- Full と Fast が並列で走らない queue 設計
- 削減で同時実行リスクが上がることはない

### DRY_RUN の挙動

- schedule 実行時: `${{ inputs.dry_run && '1' || '0' }}` → inputs 未定義なので **`0` (実送信)**
- workflow_dispatch 時: ユーザー選択（デフォルト `true` → `1` で DRY_RUN）

cron 変更後の最初の schedule 発火は実送信になる。yaml の編集ミスで全件 LINE 送信が走るリスクに注意。

### 巻き戻し

```bash
git revert <commit-sha>
git push origin main
```

cron 変更は次の schedule 発火タイミングまで猶予がある。Full lane なら最大30分待てば次の発火を観察できる。

## 完了条件

- [x] 4月の Full / Fast 別の所要時間が実測で確定（Full 5.88分 / Fast 5.62分、yaml コメントの「Fast 3分」は古い情報）
- [x] ユーザーが削減方針（A/B/C）を選択（**案A** = 両 lane 1 時間おき、30分オフセット）
- [x] DRY_RUN で挙動確認（fast lane: `notify_dispatch: new=0 update=0 suppressed=9` で LINE 送信抑止確認）
- [x] yaml 変更コミット + push
- [x] tasks/lessons.md 更新（「2026-04-26 GitHub Actions usage 月次オーバーフロー対策（pokebot 側）」追記）
- [x] MEMORY.md `project_japan_stock_bot_split.md` 更新（対応済に書き換え、5月予測更新）
- [ ] 次の schedule 発火を実機観察（**5/1 自動リセット後の最初の Full lane を観察**。月次usage超過のため 5/1 まで動かない）

## 参照

- pokeprice 側の参考実装: `~/claude/pokeprice/.github/workflows/pokeca-chart-prices.yml`（毎日→隔日に変更したコミット 90d02a2）
- pokeprice 側の教訓: `~/claude/pokeprice/tasks/lessons.md` 「2026-04-26: GitHub Actions usage 月次オーバーフロー対策」
- GitHub Billing: https://github.com/settings/billing
