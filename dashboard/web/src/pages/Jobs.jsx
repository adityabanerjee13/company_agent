import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { JobsTable } from "../components/Tables.jsx";
import { ToolCall } from "../components/Trace.jsx";
import { AgentBadge, Badge, ErrorBox, KV, Loading, Markdown, Pre, StatusBadge } from "../components/ui.jsx";
import { durBetween, enc, fmtDateTime, fmtDur, fmtNum, fmtTime, isoDate, runHref, threadHref } from "../lib.js";
import { useCrumbs, useDirectory, useLiveData } from "../live.jsx";

export function Jobs() {
  useCrumbs([["Agent traces"], ["Coding jobs"]]);
  const state = useLiveData("/api/jobs");
  return (
    <div className="page">
      <h1>Coding jobs</h1>
      <p className="muted">Each job clones the repo into a Docker sandbox, runs Claude Code on the task, then commits, pushes and opens a PR.</p>
      <Loading state={state}>{(jobs) => <div className="card"><JobsTable jobs={jobs} /></div>}</Loading>
    </div>
  );
}

const TABS = ["overview", "workflow", "session", "files"];

export function Job() {
  const { id, tab = "overview" } = useParams();
  const navigate = useNavigate();
  const { userName, channelName } = useDirectory();
  const state = useLiveData(`/api/job/${enc(id)}`);
  const d = state.data;
  const j = d?.job || {};
  useCrumbs([
    ...(j.channel_id ? [[`# ${channelName(j.channel_id)}`, `/c/${enc(j.channel_id)}`]] : []),
    ...(j.thread_ts ? [["Thread", threadHref(j.channel_id, j.thread_ts)]] : []),
    ...(d?.parent ? [["Orchestrator run", runHref(d.parent.ref, d.parent.tool_call_id)]] : []),
    [`Coding job ${id}`],
  ]);
  const active = TABS.includes(tab) ? tab : "overview";

  return (
    <div className="page">
      <Loading state={state}>{(d) => {
        const j = d.job;
        const toolCalls = d.session ? d.session.steps.filter((s) => s.kind === "tool_call").length : 0;
        const labels = {
          overview: "Task & prompt",
          workflow: `Sandbox workflow (${d.steps.length})`,
          session: `Claude session${d.session ? ` (${toolCalls} tool calls)` : ""}`,
          files: "Raw files",
        };
        return (
          <>
            <div className="channel-title">
              <AgentBadge agent="sandbox" />
              <h1>Coding job {id}</h1>
              <StatusBadge status={j.status} />
            </div>
            {d.parent && (
              <p className="small">Started by <Link to={runHref(d.parent.ref, d.parent.tool_call_id)}>an orchestrator start_coding_job tool call</Link>.</p>
            )}
            <div className="card run-header">
              <KV k="Repository">{j.repo ? <a href={`https://github.com/${j.repo}`} target="_blank" rel="noopener">{j.repo}</a> : "—"}</KV>
              <KV k="Base branch">{j.base_branch || "—"}</KV>
              <KV k="Work branch">agent/{id}</KV>
              <KV k="User">{j.user_id ? <Link to={`/u/${enc(j.user_id)}`}>{userName(j.user_id)}</Link> : "—"}</KV>
              <KV k="Created">{fmtDateTime(isoDate(j.created_at))}</KV>
              <KV k="Duration">{fmtDur(durBetween(j.created_at, j.finished_at))}</KV>
              <KV k="Pull request">{j.pr_url ? <a href={j.pr_url} target="_blank" rel="noopener">{j.pr_url.replace("https://github.com/", "")}</a> : "—"}</KV>
              {d.session?.init?.model && <KV k="Sandbox model">{d.session.init.model}</KV>}
            </div>
            {j.error && <ErrorBox>{j.error}</ErrorBox>}
            <div className="tabs">
              {TABS.map((t) => (
                <button key={t} className={`tab${active === t ? " active" : ""}`} onClick={() => navigate(`/job/${enc(id)}/${t}`, { replace: true })}>
                  {labels[t]}
                </button>
              ))}
            </div>
            {active === "overview" && <JobOverview d={d} />}
            {active === "workflow" && <JobWorkflow d={d} onSession={() => navigate(`/job/${enc(id)}/session`, { replace: true })} />}
            {active === "session" && <JobSession d={d} />}
            {active === "files" && <JobFiles d={d} />}
          </>
        );
      }}</Loading>
    </div>
  );
}

function JobOverview({ d }) {
  return (
    <div>
      <h2>Task (from the orchestrator)</h2>
      <div className="card">{d.job.task ? <Markdown text={d.job.task} className="narration" /> : <span className="muted">—</span>}</div>
      {d.job.issue_url && <p>Issue: <a href={d.job.issue_url} target="_blank" rel="noopener">{d.job.issue_url}</a></p>}
      <h2>Prompt given to Claude in the sandbox</h2>
      {d.prompt
        ? <div className="card"><Pre>{d.prompt}</Pre></div>
        : <div className="card muted">No prompt.txt was written for this job (it stopped before the agent step).</div>}
      {d.summary && <><h2>Agent summary</h2><div className="card"><Markdown text={d.summary} className="narration" /></div></>}
    </div>
  );
}

function JobWorkflow({ d, onSession }) {
  if (!d.steps.length) return <div className="card muted">No workflow steps were recorded (the job failed before the sandbox started).</div>;
  return (
    <ol className="stepper">
      {d.steps.map((s, i) => (
        <li key={i}>
          <div className="row">
            <span className="n">{i + 1}</span>
            <strong>{s.step}</strong>
            <StatusBadge status={s.error ? "failed" : s.finished_at ? "succeeded" : "running"} />
            <span className="muted small">{fmtDateTime(isoDate(s.started_at))} · {fmtDur(s.duration_s)}</span>
            {(s.env_keys || []).map((k) => <Badge key={k} className="mono">${k}</Badge>)}
          </div>
          <div className="label muted small" style={{ marginTop: 6 }}>Command</div>
          <Pre>{s.cmd}</Pre>
          {s.error && <><div className="label muted small">Error</div><ErrorBox>{s.error}</ErrorBox></>}
          {s.step === "agent" ? (
            <div className="small">
              Output: {fmtNum(s.output_length)} characters of Claude stream-json —{" "}
              <a href="#" onClick={(e) => { e.preventDefault(); onSession(); }}>view it parsed as the Claude session</a>.
            </div>
          ) : s.output ? (
            <details className="tool">
              <summary><span className="tool-name">Output</span><span className="tool-args-preview">{s.output.split("\n")[0]}</span></summary>
              <div className="tool-body"><Pre>{s.output}</Pre></div>
            </details>
          ) : <div className="muted small">(no output)</div>}
        </li>
      ))}
    </ol>
  );
}

function JobSession({ d }) {
  const [showEvents, setShowEvents] = useState(false);
  const s = d.session;
  if (!s) return <div className="card muted">No Claude session was recorded for this job.</div>;
  const init = s.init || {};
  const u = s.usage || {};
  const noise = Object.entries(s.noise || {}).map(([k, v]) => `${k} ×${v}`).join(", ");
  return (
    <div>
      <div className="card run-header">
        <KV k="Model">{init.model || "—"}</KV>
        <KV k="Working dir">{init.cwd || "—"}</KV>
        <KV k="Claude Code">{init.claude_code_version || "—"}</KV>
        <KV k="Permissions">{init.permissionMode || "—"}</KV>
        <KV k="Tokens">{fmtNum(u.input)} in · {fmtNum(u.output)} out</KV>
        <KV k="Cache">{fmtNum(u.cache_read)} read · {fmtNum(u.cache_creation)} written</KV>
        <KV k="Source">{s.source}</KV>
      </div>
      {init.tools && (
        <details className="tool">
          <summary><span className="tool-name">Tools available in the sandbox</span><span className="tool-args-preview">{init.tools.length} tools</span></summary>
          <div className="tool-body">{init.tools.map((t) => <Badge key={t} className="mono">{t}</Badge>)}</div>
        </details>
      )}
      <div className="toggle-row">
        <label><input type="checkbox" checked={showEvents} onChange={(e) => setShowEvents(e.target.checked)} /> Show background task events</label>
        {noise && <span className="muted small">Hidden stream events: {noise}</span>}
      </div>
      <div className="timeline">
        {s.steps.filter((st) => showEvents || st.kind !== "event").map((st, i) => {
          if (st.kind === "tool_call") return <div key={i} className="step step-sandbox"><ToolCall call={st} /></div>;
          if (st.kind === "text") {
            return (
              <div key={i} className="step step-sandbox">
                <div className="card">
                  <div className="step-head"><span className="step-title">Claude</span><span className="muted small">{fmtTime(isoDate(st.ts))}</span></div>
                  <Markdown text={st.text} className="narration" />
                </div>
              </div>
            );
          }
          if (st.kind === "thinking") {
            return (
              <div key={i} className="step step-sandbox">
                <div className="thinking">
                  {st.redacted ? `Thinking${st.duration_ms ? ` for ${(st.duration_ms / 1000).toFixed(1)}s` : ""} (content redacted in the stream)` : st.text}
                </div>
              </div>
            );
          }
          if (st.kind === "event") {
            return <div key={i} className="step"><div className="event">⟡ {st.subtype.replace("_", " ")}: {st.text}</div></div>;
          }
          if (st.kind === "result") {
            return (
              <div key={i} className="step step-sandbox final">
                <div className="card">
                  <div className="step-head">
                    <span className="step-title">Session result</span>
                    <StatusBadge status={st.is_error ? "error" : "success"} />
                    {st.num_turns && <Badge>{st.num_turns} turns</Badge>}
                    {st.duration_ms && <Badge>{fmtDur(st.duration_ms / 1000)}</Badge>}
                    {st.cost_usd && <Badge>${st.cost_usd.toFixed(4)}</Badge>}
                  </div>
                  <Markdown text={st.text} className="narration" />
                </div>
              </div>
            );
          }
          return null;
        })}
      </div>
    </div>
  );
}

function JobFiles({ d }) {
  const id = d.job.id;
  return (
    <div className="card">
      <p className="muted small">Files saved under traces/coding_jobs/{id}/. They open as plain text in a new tab.</p>
      {d.files.length
        ? <ul>{d.files.map((f) => <li key={f}><a href={`/api/job/${enc(id)}/raw/${enc(f)}`} target="_blank" rel="noopener">{f}</a></li>)}</ul>
        : <div className="muted">No files</div>}
    </div>
  );
}
