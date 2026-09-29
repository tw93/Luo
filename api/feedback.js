// 众测 feedback: the proof page posts here, this creates a GitHub issue on
// tw93/Luo with the reader's note and optional screenshot. The token lives
// only in the Vercel env (LUO_FEEDBACK_TOKEN, fine-grained: Luo repo,
// Issues + Contents read/write). Screenshots go to the feedback-assets
// branch, which has Vercel deployments disabled in vercel.json.

const { userToken, whoami } = require('./_auth');

const REPO = 'tw93/Luo';
const LABEL = '众测';
const ASSET_BRANCH = 'feedback-assets';
const MAX_NOTE = 1200;
const MAX_IMAGE_BYTES = 1.5 * 1024 * 1024;
const ASPECTS = ['笔画粗细', '笔画形状', '结构重心', '整体不协调', '其他'];
const SIZES = ['标题大字', '正文', '小字', '各个字号'];

function isCjk(ch) {
  const cp = ch.codePointAt(0);
  return (cp >= 0x4e00 && cp <= 0x9fff) || (cp >= 0x3400 && cp <= 0x4dbf);
}

function clean(text, max) {
  return String(text || '').replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '').trim().slice(0, max);
}

async function gh(path, token, init = {}) {
  const res = await fetch(`https://api.github.com${path}`, {
    ...init,
    headers: {
      Accept: 'application/vnd.github+json',
      Authorization: `Bearer ${token}`,
      'User-Agent': 'luo-feedback',
      'X-GitHub-Api-Version': '2022-11-28',
      ...(init.headers || {}),
    },
  });
  const body = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, body };
}

async function ensureAssetBranch(token) {
  const head = await gh(`/repos/${REPO}/git/ref/heads/${ASSET_BRANCH}`, token);
  if (head.ok) return true;
  // Branch off main once; later uploads only add files to it.
  const main = await gh(`/repos/${REPO}/git/ref/heads/main`, token);
  if (!main.ok) return false;
  const made = await gh(`/repos/${REPO}/git/refs`, token, {
    method: 'POST',
    body: JSON.stringify({ ref: `refs/heads/${ASSET_BRANCH}`, sha: main.body.object.sha }),
  });
  return made.ok || made.status === 422;
}

async function uploadImage(dataUrl, char, token) {
  const m = /^data:image\/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$/.exec(dataUrl || '');
  if (!m) return null;
  const bytes = Buffer.from(m[2], 'base64');
  if (bytes.length === 0 || bytes.length > MAX_IMAGE_BYTES) return null;
  if (!(await ensureAssetBranch(token))) return null;
  const ext = m[1] === 'jpeg' ? 'jpg' : m[1];
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const code = char.codePointAt(0).toString(16).toUpperCase();
  const path = `feedback/${stamp.slice(0, 10)}/${code}-${stamp}.${ext}`;
  const put = await gh(`/repos/${REPO}/contents/${path}`, token, {
    method: 'PUT',
    body: JSON.stringify({ message: `feedback: screenshot for ${char}`, content: m[2], branch: ASSET_BRANCH }),
  });
  if (!put.ok) return null;
  return `https://raw.githubusercontent.com/${REPO}/${ASSET_BRANCH}/${path}`;
}

async function findOpenIssue(title, token) {
  const label = encodeURIComponent(LABEL);
  for (let page = 1; page <= 5; page += 1) {
    const r = await gh(`/repos/${REPO}/issues?labels=${label}&state=open&per_page=100&page=${page}`, token);
    if (!r.ok || !Array.isArray(r.body) || r.body.length === 0) return null;
    const hit = r.body.find((it) => !it.pull_request && it.title === title);
    if (hit) return hit;
    if (r.body.length < 100) return null;
  }
  return null;
}

module.exports = async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') {
    res.status(405).json({ error: 'method' });
    return;
  }
  const token = process.env.LUO_FEEDBACK_TOKEN;
  const dry = process.env.LUO_FEEDBACK_DRY === '1';
  if (!token && !dry) {
    res.status(503).json({ error: 'not_configured' });
    return;
  }

  let data = req.body;
  if (typeof data === 'string') {
    try { data = JSON.parse(data); } catch { data = {}; }
  }
  data = data || {};

  // Honeypot: the page never fills this field.
  if (data.website) {
    res.status(200).json({ ok: true });
    return;
  }

  const char = Array.from(clean(data.char, 4))[0] || '';
  if (!char || !isCjk(char)) {
    res.status(400).json({ error: 'char' });
    return;
  }
  const code = `U+${char.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')}`;
  const aspects = (Array.isArray(data.aspects) ? data.aspects : []).filter((a) => ASPECTS.includes(a));
  const size = SIZES.includes(data.size) ? data.size : '';
  const note = clean(data.note, MAX_NOTE);
  if (!note && aspects.length === 0 && !data.image) {
    res.status(400).json({ error: 'empty' });
    return;
  }
  const version = clean(data.version, 40);
  const viewport = clean(data.viewport, 40);

  if (dry) {
    res.status(200).json({ ok: true, dry: true, char, code, aspects, size, note, hasImage: Boolean(data.image), as: userToken(req) ? 'user' : 'anonymous' });
    return;
  }

  const imageUrl = data.image ? await uploadImage(String(data.image), char, token) : null;

  const lines = [
    `### 字\n\n${char}`,
    `### 码位\n\n${code}`,
    `### 哪里还能更好\n\n${aspects.length ? aspects.map((a) => `- ${a}`).join('\n') : '未勾选'}`,
    `### 在多大的字号下看到\n\n${size || '未选择'}`,
    `### 具体说说\n\n${note || '（未填写）'}`,
  ];
  if (imageUrl) lines.push(`### 截图\n\n![${char}](${imageUrl})`);
  // Logged-in readers post as themselves; everyone else goes through the bot.
  const reader = userToken(req);
  const me = reader ? await whoami(reader) : null;
  const meta = [me ? `来自常用字校准页众测` : `来自常用字校准页众测 · 匿名读者`, version && `字体版本 ${version}`, viewport && `视口 ${viewport}`]
    .filter(Boolean)
    .join(' · ');
  lines.push(`<sub>${meta}</sub>`);

  // One open issue per glyph: later reports for the same glyph become
  // comments, so every note about 灏 sits in one thread.
  const title = `[众测] ${char} ${code}`;
  const body = lines.join('\n\n');
  const author = me ? reader : token;
  const existing = await findOpenIssue(title, token);
  if (existing) {
    const c = await gh(`/repos/${REPO}/issues/${existing.number}/comments`, author, {
      method: 'POST',
      body: JSON.stringify({ body }),
    });
    if (!c.ok) {
      res.status(502).json({ error: 'github', status: c.status });
      return;
    }
    res.status(200).json({ ok: true, url: c.body.html_url, number: existing.number, added: true, as: me ? me.login : null });
    return;
  }
  const issue = await gh(`/repos/${REPO}/issues`, author, {
    method: 'POST',
    body: JSON.stringify({ title, body, labels: [LABEL] }),
  });
  if (!issue.ok) {
    res.status(502).json({ error: 'github', status: issue.status });
    return;
  }
  res.status(200).json({ ok: true, url: issue.body.html_url, number: issue.body.number, as: me ? me.login : null });
};
