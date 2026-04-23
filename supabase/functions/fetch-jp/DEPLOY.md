# fetch-jp edge function デプロイ手順

GHA US ランナー で 403 を食う JP サイトを、Tokyo region (ap-northeast-1) の
Supabase edge function 経由で fetch するプロキシ。

## セキュリティ 2 重防御

1. `x-proxy-key` header で API key 認証 (`PROXY_API_KEY` env と完全一致チェック、タイミング攻撃耐性あり)
2. hostname allowlist で SSRF 防止 (index.ts の `ALLOWED_HOSTS` で制限)

`verify_jwt=false` で deploy する (API key で自前認証するため)。

## 初回デプロイ

### 1. Supabase CLI 準備

```bash
# インストール
brew install supabase/tap/supabase

# ログイン (ブラウザ経由で access token 取得)
supabase login

# プロジェクト確認 (pokebot プロジェクト ID: ppsvkzeybgzlsbbvgbfv)
supabase projects list
```

### 2. API key 生成

```bash
openssl rand -hex 32
# 例: 0313ee5e60c4ffd9caf70a6258821ab4c0aa6f1fbadf49a401e8cfc50682d59c
```

**生成した key は以下 3 箇所で同じ値を使う:**
- Supabase function secret (下記 3.)
- GHA secret `SUPABASE_FETCH_JP_KEY` (下記 4.)
- ローカル `.env` (開発時のみ、任意)

### 3. Supabase function secret に登録

```bash
# プロジェクト root (pokecard-alert-bot/) で実行
supabase secrets set PROXY_API_KEY=<生成した hex key> \
  --project-ref ppsvkzeybgzlsbbvgbfv
```

または Supabase Dashboard → Project → Edge Functions → Manage secrets で追加。

### 4. GHA secrets に登録

```bash
gh secret set SUPABASE_FETCH_JP_URL \
  --body "https://ppsvkzeybgzlsbbvgbfv.supabase.co/functions/v1/fetch-jp" \
  --repo kureho/pokecard-alert-bot

gh secret set SUPABASE_FETCH_JP_KEY \
  --body "<生成した hex key>" \
  --repo kureho/pokecard-alert-bot
```

### 5. function をデプロイ

```bash
# プロジェクト root (pokecard-alert-bot/) で実行
supabase functions deploy fetch-jp \
  --project-ref ppsvkzeybgzlsbbvgbfv \
  --no-verify-jwt
```

`--no-verify-jwt` は重要。verify_jwt=true のままだと独自 API key 認証より先に Supabase JWT チェックが入ってしまう。

### 6. 動作確認

```bash
# 実 URL を fetch できるか (JP IP 経由でヨドバシのトップを取得)
curl -I \
  -H "x-proxy-key: <生成した hex key>" \
  "https://ppsvkzeybgzlsbbvgbfv.supabase.co/functions/v1/fetch-jp?url=https://www.yodobashi.com/"
# → HTTP/2 200 が返れば成功

# 認証失敗の確認 (key なし)
curl -I "https://ppsvkzeybgzlsbbvgbfv.supabase.co/functions/v1/fetch-jp?url=https://www.yodobashi.com/"
# → HTTP/2 401

# allowlist 外の拒否確認
curl -I \
  -H "x-proxy-key: <生成した hex key>" \
  "https://ppsvkzeybgzlsbbvgbfv.supabase.co/functions/v1/fetch-jp?url=https://evil.example.com/"
# → HTTP/2 403
```

## allowlist に追加したい場合

`index.ts` の `ALLOWED_HOSTS` セットに hostname を足して再 deploy する。

```bash
supabase functions deploy fetch-jp \
  --project-ref ppsvkzeybgzlsbbvgbfv \
  --no-verify-jwt
```

## 無料枠

- Supabase Edge Functions: **500,000 invocation/月 無料**
- pokebot の想定実使用: 約 1,000-3,000 invocation/日 = 月 3-9 万 invocation
- 十分な余裕あり

## トラブルシュート

| 症状 | 原因 / 対処 |
|---|---|
| 401 unauthorized | `x-proxy-key` header が不一致。GHA secret と Supabase secret が同じか確認 |
| 500 PROXY_API_KEY not set | Supabase secret 未登録。`supabase secrets set PROXY_API_KEY=...` を再実行 |
| 403 host not allowed | `ALLOWED_HOSTS` に未登録。index.ts を編集して再 deploy |
| 502 fetch failed | upstream サイト側の問題 (その URL が実際にアクセス不可) |
