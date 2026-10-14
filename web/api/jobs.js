const { rpc, send, guarded } = require("./_lib");

const ALLOWED = ["new", "ready", "approved", "retry", "preparing", "submitting", "needs_you", "failed", "submitted", "skipped"];

module.exports = guarded(async (req, res) => {
  const statuses = String(req.query.status || "ready,approved").split(",").filter((s) => ALLOWED.includes(s));
  const limit = Math.min(parseInt(req.query.limit || "300", 10) || 300, 600);
  send(res, 200, await rpc("ms_list_jobs", { p_statuses: statuses, p_limit: limit }));
});
