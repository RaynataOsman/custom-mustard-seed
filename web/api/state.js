const { rpc, send, guarded } = require("./_lib");

module.exports = guarded(async (req, res) => {
  send(res, 200, await rpc("ms_get_state"));
});
