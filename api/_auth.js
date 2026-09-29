// Shared helpers for 众测 GitHub login (GitHub App user-to-server tokens).
// The App is installed on tw93/Luo only with Issues read/write, so a
// reader's token can open issues there and nothing else. The token lives in
// an httpOnly cookie; page JS never sees it.

const COOKIE = 'luo_gh';
const STATE_COOKIE = 'luo_gh_state';

function parseCookies(req) {
  const out = {};
  String(req.headers.cookie || '')
    .split(';')
    .forEach((part) => {
      const i = part.indexOf('=');
      if (i > 0) out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
    });
  return out;
}

function cookie(name, value, maxAge) {
  return `${name}=${encodeURIComponent(value)}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}`;
}

function userToken(req) {
  return parseCookies(req)[COOKIE] || '';
}

async function whoami(token) {
  if (!token) return null;
  const res = await fetch('https://api.github.com/user', {
    headers: { Authorization: `Bearer ${token}`, 'User-Agent': 'luo-feedback', Accept: 'application/vnd.github+json' },
  });
  if (!res.ok) return null;
  const u = await res.json();
  return { login: u.login, avatar: u.avatar_url };
}

module.exports = { COOKIE, STATE_COOKIE, parseCookies, cookie, userToken, whoami };
