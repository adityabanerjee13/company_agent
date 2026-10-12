import { Link, useNavigate } from "react-router-dom";
import { enc, fmtDateTime, fmtDay, fmtTime, isoDate, runHref, threadHref, tsDate } from "../lib.js";
import { useDirectory } from "../live.jsx";
import { Avatar, Badge, Markdown } from "./ui.jsx";

const stop = (e) => e.stopPropagation();

export function Message({ m, channel, inThread, highlight, showChannel, isNew }) {
  const navigate = useNavigate();
  const { userName, isBot, channelName } = useDirectory();
  const bot = isBot(m.user_id);
  const d = tsDate(m.ts);

  if (m.subtype === "channel_join" || m.subtype === "channel_leave") {
    return (
      <div className="msg system" id={`m-${m.ts}`}>
        <div />
        <div className="muted small">{userName(m.user_id)} {m.subtype === "channel_join" ? "joined" : "left"} the channel · {fmtTime(d)}</div>
      </div>
    );
  }

  const openRun = m.run ? (e) => { if (!e.target.closest("a")) navigate(runHref(m.run)); } : undefined;
  return (
    <div
      className={`msg${m.mentions_bot ? " mention" : ""}${highlight ? " highlight" : ""}${isNew ? " new" : ""}`}
      id={`m-${m.ts}`}
      style={m.run ? { cursor: "pointer" } : undefined}
      title={m.run ? "Open the orchestrator trace for this message" : undefined}
      onClick={openRun}
    >
      <Avatar userId={m.user_id} />
      <div>
        <div className="msg-head">
          <Link className="msg-name" to={`/u/${enc(m.user_id)}`} onClick={stop}>{userName(m.user_id)}</Link>
          {bot && <Badge>APP</Badge>}
          <span className="msg-time" title={d.toISOString()}>{showChannel ? fmtDateTime(d) : fmtTime(d)}</span>
          {m.edited_at && <span className="muted small">(edited)</span>}
          {m.subtype === "thread_broadcast" && <span className="muted small">also sent to the channel</span>}
        </div>
        <Markdown text={m.text} className="msg-text" />
        {m.files?.length > 0 && (
          <div className="msg-actions">
            {m.files.map((f, i) => (
              <a key={i} className="chip" href={f.url} target="_blank" rel="noopener" onClick={stop}>📎 {f.name || "file"}</a>
            ))}
          </div>
        )}
        <div className="msg-actions">
          {m.run && <Link className="chip trace" to={runHref(m.run)} onClick={stop}>◆ Orchestrator trace →</Link>}
          {!m.run && m.mentions_bot && (
            <span className="chip notrace" title="No orchestrator trace was saved for this message (sent before tracing, or the bot was offline)">no trace recorded</span>
          )}
          {m.produced_by && <Link className="chip" to={runHref(m.produced_by)} onClick={stop}>reply from orchestrator run</Link>}
          {!inThread && m.reply_count > 0 && (
            <Link className="chip replies" to={threadHref(channel, m.ts)} onClick={stop}>
              {m.reply_count} {m.reply_count === 1 ? "reply" : "replies"}
              {m.last_reply_at && <span className="muted"> · last {fmtTime(isoDate(m.last_reply_at))}</span>}
            </Link>
          )}
          {showChannel && (
            <Link className="chip" to={threadHref(m.channel_id, m.thread_ts || m.ts, m.ts)} onClick={stop}>
              in # {channelName(m.channel_id)}{m.thread_ts && m.thread_ts !== m.ts ? " (thread)" : ""}
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

export function WithDayDividers({ messages, render }) {
  const out = [];
  let last = "";
  for (const m of messages) {
    const day = fmtDay(tsDate(m.ts));
    if (day !== last) {
      out.push(<div key={`day-${day}`} className="day-divider">{day}</div>);
      last = day;
    }
    out.push(render(m));
  }
  return out;
}
