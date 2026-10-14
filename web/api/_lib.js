// Shared helpers for the Mustard Seed online dashboard (Vercel serverless functions).
// Secrets live only in Vercel env vars: SUPABASE_URL, SUPABASE_ANON_KEY, MS_TOKEN, SESSION_SECRET.
const crypto = require("crypto");

const COOKIE = "ms_session";
const DAYS = 30;

function env(name) {
  const v = process.env[name];
  if (!v) throw new Error(`Server is missing ${name}`);
  return v;
}

async function rpc(name, args = {}) {
  const url = env("SUPABASE_URL").replace(/\/$/, "");
  const key = env("SUPABASE_ANON_KEY");
  const r = await fetch(`${url}/rest/v1/rpc/${name}`, {
    method: "POST",
    headers: { apikey: key, Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({ p_token: env("MS_TOKEN"), ...args }),
  });
  const text = await r.text();
  if (!r.ok) throw new Error(`database ${r.status}: ${text.slice(0, 200)}`);
  return text ? JSON.parse(text) : null;
}

function sign(exp) {
  return crypto.createHmac("sha256", env("SESSION_SECRET")).update(String(exp)).digest("base64url");
}

function makeCookie() {
  const exp = Date.now() + DAYS * 864e5;
  return `${COOKIE}=${exp}.${sign(exp)}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${DAYS * 86400}`;
}

function clearCookie() {
  return `${COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0`;
}

function signedIn(req) {
  const raw = (req.headers.cookie || "").split(/;\s*/).find((c) => c.startsWith(COOKIE + "="));
  if (!raw) return false;
  const [exp, mac] = raw.slice(COOKIE.length + 1).split(".");
  if (!exp || !mac || Number(exp) < Date.now()) return false;
  const good = sign(exp);
  return mac.length === good.length && crypto.timingSafeEqual(Buffer.from(mac), Buffer.from(good));
}

function sameOrigin(req) {
  const origin = req.headers.origin;
  if (!origin) return true;
  try {
    return new URL(origin).host === req.headers.host;
  } catch {
    return false;
  }
}

function send(res, code, body) {
  res.statusCode = code;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(body));
}

// Wraps a handler: requires a session, and for POSTs a JSON body from this site.
function guarded(fn) {
  return async (req, res) => {
    try {
      if (!signedIn(req)) return send(res, 401, { ok: false, error: "signed out" });
      if (req.method === "POST") {
        if (!sameOrigin(req) || !(req.headers["content-type"] || "").startsWith("application/json"))
          return send(res, 403, { ok: false, error: "refused" });
      }
      return await fn(req, res);
    } catch (e) {
      return send(res, 500, { ok: false, error: String(e.message || e) });
    }
  };
}

async function body(req) {
  if (req.body && typeof req.body === "object") return req.body;
  const chunks = [];
  for await (const c of req) chunks.push(c);
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
  } catch {
    return {};
  }
}

module.exports = { rpc, makeCookie, clearCookie, signedIn, sameOrigin, send, guarded, body };
