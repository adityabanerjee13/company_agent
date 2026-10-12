import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Empty, Loading, Markdown, StatusBadge } from "../components/ui.jsx";
import { enc, fmtDateTime, fmtDur, fmtNum, isoDate, runHref, threadHref } from "../lib.js";
import { useCrumbs, useDirectory, useLiveData } from "../live.jsx";

const stop = (e) => e.stopPropagation();

// A health tile: neutral when the count is zero, flagged (icon + label, never color alone) when not.
function Health({ label, value, sub, bad, to }) {
  const flagged = bad && value > 0;
  const body = (
    <>
      <div className="label">{label}</div>
      <div className="value">
        {flagged && <span className="health-icon" aria-hidden>✖</span>}
        {fmtNum(value)}
      </div>
      <div className="sub">{bad ? (flagged ? sub : "✔ none") : sub}</div>
    </>
  );
  const cls = `tile${flagged ? " tile-bad" : ""}${to ? " tile-link" : ""}`;
  return to ? <Link className={cls} to={to}>{body}</Link> : <div className={cls}>{body}</div>;
}

function issueTarget(issue) {
  if (issue.ref) return runHref(issue.ref);
  if (issue.job_id) return `/job/${enc(issue.job_id)}/workflow`;
  if (issue.ts) return threadHref(issue.channel_id, issue.thread_ts, issue.ts);
  return null;
}

const ISSUE_ACTION = { interaction: "Open trace →", job: "Open job →", unanswered: "Open in Slack →" };

function NeedsAttention({ issues }) {
  const navigate = useNavigate();
  const { userName } = useDirectory();
  const [all, setAll] = useState(false);
  if (!issues.length) return <div className="card all-clear">✔ Nothing needs attention. Every interaction completed and every coding job succeeded.</div>;
  const shown = all ? issues : issues.slice(0, 6);
  return (
    <div className="card issues">
      {shown.map((issue, i) => {
        const to = issueTarget(issue);
        return (
          <div key={i} className={`issue issue-${issue.kind}`} onClick={() => to && navigate(to)}>
            <span className="issue-icon" aria-hidden>{issue.kind === "unanswered" ? "⚠" : "✖"}</span>
            <div className="issue-body">
              <div className="issue-head">
                <strong>{issue.title}</strong>
                <span className="muted small">{fmtDateTime(isoDate(issue.at))}</span>
              </div>
              {issue.message && (
                <div className="issue-msg">
                  <span className="muted">{userName(issue.user_id)}: </span>
                  <Markdown text={issue.message} className="inline-md" />
                </div>
              )}
              {issue.detail && <div className="issue-detail">{issue.detail}</div>}
            </div>
            {to && <Link className="chip" to={to} onClick={stop}>{ISSUE_ACTION[issue.kind]}</Link>}
          </div>
        );
      })}
      {issues.length > 6 && (
        <button className="link-btn" onClick={() => setAll((a) => !a)}>{all ? "Show fewer" : `Show all ${issues.length}`}</button>
      )}
    </div>
  );
}

function Actions({ tools }) {
  if (!tools.length) return <span className="muted small">answered directly</span>;
  return (
    <div className="actions">
      {tools.map((t, i) => {
        const failed = t.status !== "success";
        if (t.link?.type === "github") {
          return <Link key={i} className={`chip act act-gh${failed ? " act-bad" : ""}`} to={runHref(t.link.ref)} onClick={stop}>GitHub agent →</Link>;
        }
        if (t.link?.type === "job") {
          return (
            <Link key={i} className={`chip act act-job${t.link.status === "failed" ? " act-bad" : ""}`} to={`/job/${enc(t.link.id)}`} onClick={stop}>
              job {t.link.id} · <span className={`status status-${t.link.status || "unknown"}`}>{t.link.status || "?"}</span>
            </Link>
          );
        }
        return <span key={i} className={`chip act mono${failed ? " act-bad" : ""}`}>{t.name}{failed ? ` · ${t.status}` : ""}</span>;
      })}
    </div>
  );
}

function Interactions({ interactions }) {
  const navigate = useNavigate();
  const { userName } = useDirectory();
  const [failedOnly, setFailedOnly] = useState(false);
  const rows = failedOnly ? interactions.filter((i) => i.outcome === "failed") : interactions;
  return (
    <>
      <div className="section-head">
        <h2>Recent agent–user interactions</h2>
        <div className="seg">
          <button className={!failedOnly ? "on" : ""} onClick={() => setFailedOnly(false)}>All ({interactions.length})</button>
          <button className={failedOnly ? "on" : ""} onClick={() => setFailedOnly(true)}>
            Failed ({interactions.filter((i) => i.outcome === "failed").length})
          </button>
        </div>
      </div>
      <div className="card">
        {!rows.length ? <Empty>{failedOnly ? "No failed interactions" : "No interactions traced yet"}</Empty> : (
          <div className="table-wrap">
            <table className="interactions">
              <thead>
                <tr>{["When", "User", "Request", "What the agent did", "Outcome", "Duration", "Tokens"].map((t) => <th key={t}>{t}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((i) => (
                  <tr key={`${i.ref.dir}/${i.ref.file}`} className={`clickable${i.outcome === "failed" ? " row-bad" : ""}`} onClick={() => navigate(runHref(i.ref))}>
                    <td className="nowrap">{fmtDateTime(isoDate(i.started_at))}</td>
                    <td className="nowrap">
                      <Link to={`/u/${enc(i.ctx.user_id)}`} onClick={stop}>{userName(i.ctx.user_id)}</Link>
                    </td>
                    <td className="request"><Markdown text={i.message} className="clamp" /></td>
                    <td><Actions tools={i.tool_list} /></td>
                    <td>
                      <StatusBadge status={i.outcome} />
                      {i.problems.length > 0 && <div className="problem">{i.problems.join("; ")}</div>}
                    </td>
                    <td className="nowrap">{fmtDur(i.duration_s)}</td>
                    <td className="nowrap">{fmtNum((i.usage.input || 0) + (i.usage.output || 0))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

export default function Overview() {
  useCrumbs([["Overview"]]);
  const state = useLiveData("/api/overview");
  return (
    <div className="page">
      <h1>Overview</h1>
      <p className="muted">Every request users made to the AI coworker, traced end to end, and what went wrong. Updates live.</p>
      <Loading state={state}>{(o) => {
        const c = o.counts;
        return (
          <>
            <div className="tiles">
              <Health label="Interactions" value={c.interactions}
                sub={o.median_duration_s != null ? `median ${fmtDur(o.median_duration_s)} per turn` : "none yet"} to="/runs/orchestrator" />
              <Health label="Failed interactions" value={c.failed} sub={`of ${c.interactions} interactions`} bad />
              <Health label="Failed coding jobs" value={c.jobs_failed} sub={`of ${c.jobs} jobs`} bad to="/jobs" />
              <Health label="Jobs running" value={c.jobs_running} sub={c.jobs_running ? "in the sandbox now" : "none"} to="/jobs" />
              <Health label="Unanswered mentions" value={c.unanswered} sub="@mentions with no bot reply" bad />
              <Health label="Tool errors" value={c.tool_errors} sub={`of ${c.tool_calls} tool calls`} bad />
            </div>
            <h2>Needs attention</h2>
            <NeedsAttention issues={o.issues} />
            <Interactions interactions={o.interactions} />
          </>
        );
      }}</Loading>
    </div>
  );
}
