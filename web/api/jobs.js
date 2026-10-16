const { rpc, send, guarded } = require("./_lib");

const ALLOWED = ["new", "ready", "approved", "retry", "preparing", "submitting", "needs_you", "failed", "submitted", "skipped", "expired"];

// Light list (no long text) so all roles fit in one response; open a role to load its full text (/api/job).
module.exports = guarded(async (req, res) => {
  const statuses = String(req.query.status || "ready,approved").split(",").filter((s) => ALLOWED.includes(s));
  const limit = Math.min(parseInt(req.query.limit || "1000", 10) || 1000, 2000);
  send(res, 200, await rpc("ms_list_jobs_lite", { p_statuses: statuses, p_limit: limit }));
});
