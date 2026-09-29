const { COOKIE, cookie, userToken, whoami } = require('../_auth');

// GET: who is logged in ({login} or {login: null}). POST: log out.
module.exports = async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method === 'POST') {
    res.setHeader('Set-Cookie', cookie(COOKIE, '', 0));
    res.status(200).json({ login: null });
    return;
  }
  const me = await whoami(userToken(req));
  res.status(200).json({ login: me ? me.login : null, enabled: Boolean(process.env.LUO_GH_APP_CLIENT_ID) });
};
