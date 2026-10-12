import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { argsPreview, enc, fmtNum, runHref } from "../lib.js";
import { Badge, Json, Markdown, Pre, StatusBadge } from "./ui.jsx";

const stop = (e) => e.stopPropagation();

export function SubLink({ link }) {
  if (!link) return null;
  if (link.type === "github") {
    return <Link className="sublink" to={runHref(link.ref)} onClick={stop}>GitHub agent run →</Link>;
  }
  if (link.type === "job") {
    return (
      <Link className="sublink job" to={`/job/${enc(link.id)}`} onClick={stop}>
        Coding job {link.id}{link.status ? ` · ${link.status}` : ""} →
      </Link>
    );
  }
  return null;
}

// One tool call: collapsed shows the tool name and an args summary; expanded shows name, args and result.
export function ToolCall({ call, focus }) {
  const ref = useRef(null);
  useEffect(() => {
    if (focus && ref.current) {
      ref.current.open = true;
      ref.current.scrollIntoView({ block: "center" });
    }
  }, [focus]);
  const kind = call.link?.type;
  return (
    <details ref={ref} className={`tool${kind ? " subagent" : ""}${kind === "job" ? " job" : ""}${focus ? " focus" : ""}`} id={call.id ? `call-${call.id}` : undefined}>
      <summary>
        <span className="tool-name">{call.name}</span>
        <span className="tool-args-preview">{argsPreview(call.args)}</span>
        {call.status && call.status !== "success" && <StatusBadge status={call.status} />}
        <SubLink link={call.link} />
      </summary>
      <div className="tool-body">
        <div className="label">Tool</div>
        <div className="tool-name">{call.name}</div>
        <div className="label">Arguments</div>
        <Json value={call.args} />
        <div className="label">Result{call.status ? ` · ${call.status}` : ""}</div>
        {call.result === null || call.result === undefined
          ? <div className="muted small">No result recorded (the run ended before the tool returned).</div>
          : <Pre>{call.result}</Pre>}
        {call.link && <div style={{ marginTop: 8 }}><SubLink link={call.link} /></div>}
      </div>
    </details>
  );
}

export function UsageBadges({ usage: u }) {
  if (!u) return null;
  return (
    <span className="usage">
      {u.input != null && <Badge>{fmtNum(u.input)} in</Badge>}
      {u.output != null && <Badge>{fmtNum(u.output)} out</Badge>}
      {u.reasoning ? <Badge>{fmtNum(u.reasoning)} reasoning tokens</Badge> : null}
      {u.cache_read ? <Badge>{fmtNum(u.cache_read)} cached</Badge> : null}
    </span>
  );
}

const HISTORY_MARKER = "[Earlier messages in this conversation]";

export function Prompt({ text, agent }) {
  if (agent === "orchestrator" && text.startsWith(HISTORY_MARKER)) {
    const cut = text.lastIndexOf("\n\n");
    const history = cut > 0 ? text.slice(HISTORY_MARKER.length, cut).trim() : "";
    const current = cut > 0 ? text.slice(cut + 2) : text;
    return (
      <div>
        <div className="label muted small">New message</div>
        <Markdown text={current} className="narration" />
        {history && (
          <details className="tool" style={{ marginTop: 8 }}>
            <summary>
              <span className="tool-name">Conversation history</span>
              <span className="tool-args-preview">{history.split("\n").length} lines given to the agent as context</span>
            </summary>
            <div className="tool-body"><Pre>{history}</Pre></div>
          </details>
        )}
      </div>
    );
  }
  return <Markdown text={text} className="narration" />;
}
