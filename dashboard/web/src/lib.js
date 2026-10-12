// Formatting, API access and the Slack/markdown renderer shared by every page.

export const enc = encodeURIComponent;

export async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(`${res.status} ${body.detail || res.statusText}`);
  }
  return res.json();
}

export const fmtNum = (n) => (n ?? 0).toLocaleString();
export const tsDate = (ts) => new Date(parseFloat(ts) * 1000);
export const isoDate = (iso) => (iso ? new Date(iso) : null);

export function fmtTime(d) {
  if (!d || isNaN(d)) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function fmtDateTime(d) {
  if (!d || isNaN(d)) return "—";
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function fmtDay(d) {
  return d.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
}

export function fmtDur(s) {
  if (s === null || s === undefined || isNaN(s)) return "—";
  if (s < 60) return `${(+s).toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return m < 60 ? `${m}m ${sec}s` : `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function fmtAgo(iso, now = Date.now()) {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((now - new Date(iso)) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

export const durBetween = (a, b) => (a && b ? (new Date(b) - new Date(a)) / 1000 : null);

export const runHref = (ref, call) => `/run/${ref.agent}/${enc(ref.dir)}/${enc(ref.file)}${call ? `/${enc(call)}` : ""}`;
export const threadHref = (ch, threadTs, msgTs) => `/c/${enc(ch)}/t/${enc(threadTs)}${msgTs ? `/${enc(msgTs)}` : ""}`;

export const agentLabel = { orchestrator: "Orchestrator", github_agent: "GitHub agent", sandbox: "Sandbox Claude" };

export function convLabel(c, userName) {
  if (!c) return "";
  if (c.type === "im") return userName(c.dm_user_id || c.members?.find((m) => m !== "bot")) || c.id;
  if (c.type === "mpim") return (c.members || []).map(userName).join(", ") || c.name || c.id;
  return c.name || c.id;
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// Slack mrkdwn + the markdown the models write, built from escaped text only (the content is untrusted).
export function renderMarkdown(text, userName = (id) => id, channelName = (id) => id) {
  const holders = [];
  const hold = (html) => `\u0000${holders.push(html) - 1}\u0000`;
  const inline = (raw) => {
    let s = esc(raw);
    s = s.replace(/`([^`\n]+)`/g, (_, c) => hold(`<code>${c}</code>`));
    s = s.replace(/&lt;@([UW]\w+)(?:\|[^&]*)?&gt;/g, (_, id) => hold(`<span class="mention-chip">@${esc(userName(id))}</span>`));
    s = s.replace(/&lt;#(C\w+)(?:\|([^&]*))?&gt;/g, (_, id, label) => hold(`<a href="#/c/${id}">#${esc(label || channelName(id))}</a>`));
    s = s.replace(/&lt;!(here|channel|everyone)[^&]*&gt;/g, (_, k) => hold(`<span class="mention-chip">@${k}</span>`));
    s = s.replace(/&lt;(https?:\/\/[^\s|]+?)(?:\|(.+?))?&gt;/g, (_, url, label) => hold(`<a href="${url}" target="_blank" rel="noopener">${label || url}</a>`));
    s = s.replace(/&lt;(mailto:[^\s|]+?)\|(.+?)&gt;/g, (_, url, label) => hold(`<a href="${url}">${label}</a>`));
    s = s.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) => hold(`<a href="${url}" target="_blank" rel="noopener">${label}</a>`));
    s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)\u0000]+)/g, (_, pre, url) => pre + hold(`<a href="${url}" target="_blank" rel="noopener">${url}</a>`));
    s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s.,:;!?)]|$)/g, "$1<strong>$2</strong>");
    s = s.replace(/(^|[\s(])_([^_\n]+)_(?=[\s.,:;!?)]|$)/g, "$1<em>$2</em>");
    s = s.replace(/(^|[\s(])~([^~\n]+)~(?=[\s.,:;!?)]|$)/g, "$1<del>$2</del>");
    s = s.replace(/^#{1,4} (.+)$/gm, "<strong>$1</strong>");
    s = s.replace(/^&gt; ?(.*)$/gm, '<span class="quote">$1</span>');
    s = s.replace(/^(\s*)[-•] /gm, "$1• ");
    s = s.replace(/\n/g, "<br>");
    return s;
  };
  // markdown pipe tables: a header row, a |---| separator row, then body rows
  const cells = (line) => line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  const withTables = (raw) => {
    const lines = raw.split("\n");
    const out = [];
    let text = [];
    for (let i = 0; i < lines.length; i++) {
      if (/^\s*\|.*\|\s*$/.test(lines[i]) && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1] || "")) {
        const head = cells(lines[i]);
        const body = [];
        i += 2;
        while (i < lines.length && /^\s*\|/.test(lines[i])) body.push(cells(lines[i++]));
        i -= 1;
        out.push(inline(text.join("\n")));
        text = [];
        out.push(hold(`<div class="table-wrap"><table class="md-table"><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead>`
          + `<tbody>${body.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`));
      } else {
        text.push(lines[i]);
      }
    }
    out.push(inline(text.join("\n")));
    return out.join("");
  };
  let html = String(text ?? "").split("```").map((part, i) => {
    if (i % 2) return hold(`<pre><code>${esc(part.replace(/^[\w+-]*\n/, ""))}</code></pre>`);
    return withTables(part);
  }).join("");
  for (let pass = 0; pass < 3 && html.includes("\u0000"); pass++) {
    html = html.replace(/\u0000(\d+)\u0000/g, (_, i) => holders[i]);
  }
  return html;
}

export function argsPreview(args) {
  if (!args || typeof args !== "object") return String(args ?? "");
  const entries = Object.entries(args);
  if (entries.length === 1 && typeof entries[0][1] === "string") return entries[0][1].split("\n")[0];
  return entries
    .map(([k, v]) => `${k}=${typeof v === "string" ? JSON.stringify(v.length > 60 ? v.slice(0, 60) + "…" : v) : JSON.stringify(v)}`)
    .join("  ");
}
