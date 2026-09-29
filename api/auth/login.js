const crypto = require('crypto');
const { STATE_COOKIE, cookie } = require('../_auth');

// Starts GitHub App login. `back` is the page to return to (same site only).
module.exports = function handler(req, res) {
  const clientId = process.env.LUO_GH_APP_CLIENT_ID;
  if (!clientId) {
    res.status(503).send('login not configured');
    return;
  }
  const url = new URL(req.url, `https://${req.headers.host}`);
  const back = url.searchParams.get('back') || '/proof/gb2312.html';
  const safeBack = back.startsWith('/') && !back.startsWith('//') ? back : '/proof/gb2312.html';
  const state = `${crypto.randomBytes(16).toString('hex')}.${Buffer.from(safeBack).toString('base64url')}`;
  const redirect = `https://${req.headers.host}/api/auth/callback`;
  const target = new URL('https://github.com/login/oauth/authorize');
  target.searchParams.set('client_id', clientId);
  target.searchParams.set('redirect_uri', redirect);
  target.searchParams.set('state', state);
  res.setHeader('Set-Cookie', cookie(STATE_COOKIE, state, 600));
  res.setHeader('Cache-Control', 'no-store');
  res.writeHead(302, { Location: target.toString() });
  res.end();
};
