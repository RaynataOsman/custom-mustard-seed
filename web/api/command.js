const { rpc, send, guarded, body } = require("./_lib");

const ACTIONS = ["approve", "retry", "skip", "reopen", "done", "allow"];
const RUNS = ["scan", "prepare", "submit", "all", "backfill", "tiers", "retriage", "sweep", "referrals", "expire", "replies", "board"];

module.exports = guarded(async (req, res) => {
  if (req.method !== "POST") return send(res, 405, { ok: false });
  const b = await body(req);
  let payload;
  if (b.kind === "job_action" && ACTIONS.includes(b.action) && /^[\w-]{4,40}$/.test(b.id || ""))
    payload = { id: b.id, action: b.action, note: String(b.note || "").slice(0, 500), override: !!b.override, discard: !!b.discard };
  else if (b.kind === "edit_text" && ["resume", "cover"].includes(b.what) && /^[\w-]{4,40}$/.test(b.id || "") &&
           typeof b.text === "string" && b.text.length > 0 && b.text.length <= 20000)
    payload = { id: b.id, what: b.what, text: b.text, force: !!b.force };
  else if (b.kind === "resume_text" && /^[\w-]{4,40}$/.test(b.id || "")) payload = { id: b.id };
  else if (b.kind === "contact_sent" && Number.isInteger(b.id)) payload = { id: b.id };
  else if (b.kind === "followed_up" && /^[\w-]{4,40}$/.test(b.id || "")) payload = { id: b.id };
  else if (b.kind === "approve_all") payload = { min_score: Number(b.min_score) || 60 };
  else if (b.kind === "run" && RUNS.includes(b.job) && (b.arg == null || /^[\w-]{1,40}$/.test(b.arg) || (b.job === "board" && /^[\w .()&,'/-]{2,80}$/.test(b.arg))))
    payload = { job: b.job, arg: b.arg ?? null };
  else return send(res, 400, { ok: false, error: "unknown command" });
  const id = await rpc("ms_add_command", { p_kind: b.kind, p_payload: payload });
  send(res, 200, { ok: true, id });
});
