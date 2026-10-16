const { rpc, send, guarded } = require("./_lib");

// One role with all its text: description, cover letter, interview prep, gaps, referral notes.
module.exports = guarded(async (req, res) => {
  const id = String(req.query.id || "");
  if (!/^[\w-]{4,40}$/.test(id)) return send(res, 400, { ok: false, error: "bad id" });
  const j = await rpc("ms_get_job", { p_id: id });
  if (!j) return send(res, 404, { ok: false, error: "That role is no longer synced (it may have been skipped or expired)." });
  send(res, 200, j);
});
