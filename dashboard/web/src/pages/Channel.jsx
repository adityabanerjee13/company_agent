import { useEffect, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { Message, WithDayDividers } from "../components/Message.jsx";
import { Badge, Empty, ErrorBox } from "../components/ui.jsx";
import { convLabel, enc, threadHref } from "../lib.js";
import { useCrumbs, useDirectory, useLiveData } from "../live.jsx";

// Messages that arrived after the first load of this view get a brief highlight.
function useNewArrivals(messages, resetKey) {
  const seen = useRef(null);
  const key = useRef(resetKey);
  if (key.current !== resetKey) {
    key.current = resetKey;
    seen.current = null;
  }
  const fresh = new Set();
  if (messages) {
    if (seen.current) messages.forEach((m) => !seen.current.has(m.ts) && fresh.add(m.ts));
    else seen.current = new Set();
    messages.forEach((m) => seen.current.add(m.ts));
  }
  return fresh;
}

export default function Channel() {
  const { ch, ts: threadTs, msg: focusTs } = useParams();
  const { userName } = useDirectory();
  const chan = useLiveData(`/api/channel/${enc(ch)}`);
  const thr = useLiveData(threadTs ? `/api/thread/${enc(ch)}/${enc(threadTs)}` : null);
  const info = chan.data?.channel || { id: ch, type: "channel" };
  const label = convLabel(info, userName);
  useCrumbs([[info.type === "im" || info.type === "mpim" ? "Direct messages" : "Channels"], [label, `/c/${enc(ch)}`], ...(threadTs ? [["Thread"]] : [])]);

  const messages = chan.data?.messages;
  const fresh = useNewArrivals(messages, ch);
  const threadFresh = useNewArrivals(threadTs ? thr.data?.messages : null, `${ch}/${threadTs}`);
  const listEnd = useRef(null);

  useEffect(() => {
    // open at the newest message like Slack does, unless a specific message was asked for
    if (messages && !focusTs && !threadTs) listEnd.current?.scrollIntoView({ block: "end" });
  }, [ch, !!messages]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (focusTs) document.getElementById(`m-${focusTs}`)?.scrollIntoView({ block: "center" });
  }, [focusTs, !!thr.data, !!messages]); // eslint-disable-line react-hooks/exhaustive-deps

  const visible = (messages || []).filter((m) => !m.missing_root);
  const orphans = (messages || []).filter((m) => m.missing_root);
  return (
    <div className={`channel-layout${threadTs ? " with-thread" : ""}`}>
      <div className="pane">
        <div className="channel-title">
          <h1>{info.type === "im" ? "" : info.is_private ? "🔒 " : "# "}{label}</h1>
          <Badge>{info.type || "channel"}</Badge>
          {info.is_member === false && <Badge className="status-failed">not readable by the sync token</Badge>}
          <span className="muted small">{visible.length} conversations</span>
        </div>
        {info.topic && <p className="muted small" style={{ marginTop: -4 }}>{info.topic}</p>}
        {chan.error && <ErrorBox>Could not load: {chan.error.message}</ErrorBox>}
        {!messages && !chan.error && <Empty>Loading…</Empty>}
        {messages && !visible.length && !orphans.length && (
          <Empty>{info.is_member === false
            ? "The sync token can't read this channel. Invite the bot to it, or set SLACK_USER_TOKEN."
            : "No messages yet."}</Empty>
        )}
        <WithDayDividers messages={visible} render={(m) => (
          <Message key={m.ts} m={m} channel={ch} highlight={!threadTs && m.ts === focusTs} isNew={fresh.has(m.ts)} />
        )} />
        {orphans.map((m) => (
          <div key={m.ts} className="msg">
            <div />
            <div className="muted small">
              Thread whose first message isn't stored · <Link to={threadHref(ch, m.ts)}>{m.reply_count} replies</Link>
            </div>
          </div>
        ))}
        <div ref={listEnd} />
      </div>
      {threadTs && (
        <div className="pane thread-pane">
          <div className="thread-head">
            <h3>Thread</h3>
            <Link to={`/c/${enc(ch)}`}>✕ close</Link>
          </div>
          {thr.data?.jobs?.length > 0 && (
            <div className="msg-actions" style={{ marginBottom: 8 }}>
              {thr.data.jobs.map((j) => (
                <Link key={j.id} className="chip" to={`/job/${enc(j.id)}`}><span className="dot dot-job" />job {j.id} · {j.status}</Link>
              ))}
            </div>
          )}
          {thr.error && <ErrorBox>Could not load: {thr.error.message}</ErrorBox>}
          {!thr.data && !thr.error && <Empty>Loading…</Empty>}
          {thr.data && !thr.data.messages.length && <Empty>No messages in this thread</Empty>}
          {thr.data?.messages.map((m) => (
            <Message key={m.ts} m={m} channel={ch} inThread highlight={m.ts === focusTs} isNew={threadFresh.has(m.ts)} />
          ))}
        </div>
      )}
    </div>
  );
}
