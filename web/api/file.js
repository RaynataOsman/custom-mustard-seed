const { rpc, send, guarded } = require("./_lib");

module.exports = guarded(async (req, res) => {
  const job = String(req.query.job || ""), kind = String(req.query.kind || "");
  if (!/^[\w-]{4,40}$/.test(job) || !["resume", "cover"].includes(kind)) return send(res, 400, { ok: false });
  const f = await rpc("ms_get_file", { p_job_id: job, p_kind: kind });
  if (!f || !f.b64) return send(res, 404, { ok: false, error: "This file has not synced yet - is the PC dashboard open?" });
  const buf = Buffer.from(f.b64, "base64");
  res.statusCode = 200;
  res.setHeader("Content-Type", "application/pdf");
  res.setHeader("Content-Disposition", `inline; filename="${String(f.name).replace(/[^\w.\- ]/g, "_")}"`);
  res.setHeader("Cache-Control", "private, no-store");
  res.end(buf);
});
