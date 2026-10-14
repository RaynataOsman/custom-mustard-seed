const { rpc, makeCookie, clearCookie, sameOrigin, send, body } = require("./_lib");

const tries = new Map(); // ip -> [count, firstAt]  (best effort; resets when the function cold-starts)

module.exports = async (req, res) => {
  try {
    if (req.method === "DELETE") {
      res.setHeader("Set-Cookie", clearCookie());
      return send(res, 200, { ok: true });
    }
    if (req.method !== "POST" || !sameOrigin(req)) return send(res, 405, { ok: false });
    const ip = String(req.headers["x-forwarded-for"] || "").split(",")[0] || "?";
    const t = tries.get(ip) || [0, Date.now()];
    if (Date.now() - t[1] > 15 * 60e3) { t[0] = 0; t[1] = Date.now(); }
    if (t[0] >= 8) return send(res, 429, { ok: false, error: "Too many tries - wait 15 minutes." });
    const { password } = await body(req);
    const ok = await rpc("ms_check_password", { p_password: String(password || "") });
    if (!ok) {
      t[0] += 1; tries.set(ip, t);
      await new Promise((r) => setTimeout(r, 700));
      return send(res, 401, { ok: false, error: "Wrong password." });
    }
    tries.delete(ip);
    res.setHeader("Set-Cookie", makeCookie());
    return send(res, 200, { ok: true });
  } catch (e) {
    return send(res, 500, { ok: false, error: String(e.message || e) });
  }
};
