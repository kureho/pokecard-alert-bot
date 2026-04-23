// pokecard-alert-bot 用の日本リージョン proxy。
// GHA US ランナーから 403 を食う JP サイト (Yodobashi / Bic / amiami / Amazon 等) を
// Tokyo region (ap-northeast-1) の Supabase edge function 経由で fetch する。
//
// セキュリティ 2 重防御:
//   (1) x-proxy-key header で API key 認証 (PROXY_API_KEY env と完全一致)
//   (2) hostname allowlist (SSRF 防止)
// verify_jwt=false にしているため、Supabase anon/service key は不要。
//
// デプロイ:
//   supabase functions deploy fetch-jp --project-ref <pokebot project ref> --no-verify-jwt
//   supabase secrets set PROXY_API_KEY=<hex key> --project-ref <pokebot project ref>
import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const ALLOWED_HOSTS: Set<string> = new Set([
  // US IP block で disabled になっていた adapter 対象
  "www.yodobashi.com",
  "www.biccamera.com",
  "www.amiami.com",
  "www.amiami.jp",
  "www.amazon.co.jp",
  // 将来の追加候補 (Tier 1 adapter)
  "www.toysrus.co.jp",
  "shop.joshin.co.jp",
  "joshinweb.jp",
  "ec.geo-online.co.jp",
  "www.hmv.co.jp",
  "7net.omni7.jp",
  "www.suruga-ya.jp",
]);

// 最新 Chrome の UA を使う。Yodobashi / Bic の HTTP/2 stream error や amiami の 403 対策。
// 古い UA は容易に Bot 判定される。
const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

function cors(): Record<string, string> {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, x-proxy-key",
  };
}

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: cors() });
  }

  // (1) API key 認証
  const expected = Deno.env.get("PROXY_API_KEY") ?? "";
  const provided = req.headers.get("x-proxy-key") ?? "";
  if (!expected) {
    return new Response("server misconfigured: PROXY_API_KEY not set", {
      status: 500,
      headers: cors(),
    });
  }
  if (!constantTimeEqual(expected, provided)) {
    return new Response("unauthorized", {
      status: 401,
      headers: cors(),
    });
  }

  const url = new URL(req.url);
  const target = url.searchParams.get("url");
  if (!target) {
    return new Response("missing url param", {
      status: 400,
      headers: cors(),
    });
  }

  let parsed: URL;
  try {
    parsed = new URL(target);
  } catch {
    return new Response("invalid url", {
      status: 400,
      headers: cors(),
    });
  }

  // (2) hostname allowlist
  if (!ALLOWED_HOSTS.has(parsed.hostname)) {
    return new Response(`host not allowed: ${parsed.hostname}`, {
      status: 403,
      headers: cors(),
    });
  }

  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    return new Response("invalid protocol", {
      status: 400,
      headers: cors(),
    });
  }

  try {
    // Chrome が送る header を一通り付与して Bot 判定を回避する。
    // Accept-Encoding を付けるとレスポンスが gzip で返ってくるが、Deno fetch は自動展開する。
    const upstream = await fetch(parsed.toString(), {
      headers: {
        "User-Agent": USER_AGENT,
        "Accept":
          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
      },
      redirect: "follow",
    });

    const body = await upstream.text();
    const contentType =
      upstream.headers.get("content-type") || "text/html; charset=utf-8";

    return new Response(body, {
      status: upstream.status,
      headers: {
        ...cors(),
        "Content-Type": contentType,
        "X-Upstream-Status": String(upstream.status),
        "X-Upstream-Host": parsed.hostname,
      },
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return new Response(`fetch failed: ${msg}`, {
      status: 502,
      headers: cors(),
    });
  }
});
