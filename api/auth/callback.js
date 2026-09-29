const { COOKIE, STATE_COOKIE, parseCookies, cookie } = require('../_auth');

module.exports = async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  const url = new URL(req.url, `https://${req.headers.host}`);
  const code = url.searchParams.get('code') || '';
  const state = url.searchParams.get('state') || '';
  const saved = parseCookies(req)[STATE_COOKIE] || '';
  if (!code || !state || state !== saved) {
    res.status(400).send('login expired, please try again');
    return;
  }
  let back = '/proof/gb2312.html';
  try {
    const b = Buffer.from(state.split('.')[1] || '', 'base64url').toString();
    if (b.startsWith('/') && !b.startsWith('//')) back = b;
  } catch {}

  const tokenRes = await fetch('https://github.com/login/oauth/access_token', {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({
      client_id: process.env.LUO_GH_APP_CLIENT_ID,
      client_secret: process.env.LUO_GH_APP_CLIENT_SECRET,
      code,
    }),
  });
  const data = await tokenRes.json().catch(() => ({}));
  if (!data.access_token) {
    res.status(502).send('GitHub login failed');
    return;
  }
  // GitHub App user tokens expire after 8 hours; keep the cookie to match.
  res.setHeader('Set-Cookie', [cookie(COOKIE, data.access_token, 8 * 3600), cookie(STATE_COOKIE, '', 0)]);
  res.writeHead(302, { Location: `${back}${back.includes('?') ? '&' : '?'}crowd=1` });
  res.end();
};
