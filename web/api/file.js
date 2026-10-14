const { rpc, send, guarded } = require("./_lib");

// Opens a resume / cover letter PDF. PDFs that are not online yet are fetched from the PC:
// the first visit queues a request, and the page refreshes itself until the PDF arrives.
function waiting(res, url, tries, msg) {
  res.statusCode = 202;
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  const refresh = tries < 25 ? `<meta http-equiv="refresh" content="3;url=${url}">` : "";
  res.end(`<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">${refresh}
<title>Fetching PDF</title><body style="font:15px system-ui;background:#f7f5ef;color:#292c24;display:grid;place-items:center;min-height:90vh;margin:0">
<div style="max-width:340px;text-align:center;padding:16px"><img src="/seed.svg" width="44" alt=""><p>${msg}</p></div></body>`);
}

module.exports = guarded(async (req, res) => {
  const job = String(req.query.job || ""), kind = String(req.query.kind || "");
  const tries = parseInt(req.query.t || "0", 10) || 0;
  if (!/^[\w-]{4,40}$/.test(job) || !["resume", "cover"].includes(kind)) return send(res, 400, { ok: false });
  const f = await rpc("ms_get_file", { p_job_id: job, p_kind: kind });
  if (!f || !f.b64) {
    if (tries === 0) await rpc("ms_add_command", { p_kind: "file", p_payload: { id: job, kind } });
    const next = `/api/file?job=${encodeURIComponent(job)}&kind=${kind}&t=${tries + 1}`;
    return waiting(res, next, tries, tries < 25
      ? "Getting this PDF from your PC... this page refreshes by itself (usually under 20 seconds)."
      : "Your PC did not answer. Open the Mustard Seed dashboard on your PC (start.bat), then reload this page.");
  }
  const buf = Buffer.from(f.b64, "base64");
  res.statusCode = 200;
  res.setHeader("Content-Type", "application/pdf");
  res.setHeader("Content-Disposition", `inline; filename="${String(f.name).replace(/[^\w.\- ]/g, "_")}"`);
  res.setHeader("Cache-Control", "private, no-store");
  res.end(buf);
});
