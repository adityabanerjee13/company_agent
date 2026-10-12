import { Link, useParams } from "react-router-dom";
import { RunsTable } from "../components/Tables.jsx";
import { AgentBadge, ErrorBox, Loading, Markdown, StatusBadge, KV } from "../components/ui.jsx";
import { Prompt, ToolCall, UsageBadges } from "../components/Trace.jsx";
import { Message } from "../components/Message.jsx";
import { agentLabel, enc, fmtDateTime, fmtDur, fmtNum, isoDate, runHref, threadHref } from "../lib.js";
import { useCrumbs, useDirectory, useLiveData } from "../live.jsx";

export function Runs() {
  const { agent } = useParams();
  const title = agentLabel[agent] ? `${agentLabel[agent]} runs` : "All runs";
  useCrumbs([["Agent traces"], [title]]);
  const state = useLiveData(`/api/runs${agent ? `?agent=${enc(agent)}` : ""}`);
  return (
    <div className="page">
      <h1>{title}</h1>
      <p className="muted">
        {agent === "github_agent"
          ? "Each run is one ask_github call from the orchestrator: the question it was asked and the GitHub tools it used to answer."
          : "Each run is one Slack turn: the prompt the orchestrator received, its model calls, and the tools and subagents it invoked."}
      </p>
      <Loading state={state}>{(runs) => (
        <div className="card">
          <RunsTable runs={[...runs].sort((a, b) => (b.started_at || "").localeCompare(a.started_at || ""))} />
        </div>
      )}</Loading>
    </div>
  );
}

export function Run() {
  const { agent, dir, file, call: focusCall } = useParams();
  const { userName, channelName } = useDirectory();
  const state = useLiveData(`/api/run/${enc(agent)}/${enc(dir)}/${enc(file)}`);
  const r = state.data;
  const ctx = r?.ctx || {};
  useCrumbs([
    ...(ctx.channel_id ? [[`# ${channelName(ctx.channel_id)}`, `/c/${enc(ctx.channel_id)}`]] : []),
    ...(ctx.thread_ts ? [["Thread", threadHref(ctx.channel_id, ctx.thread_ts, ctx.ts)]] : []),
    ...(r?.parent ? [["Orchestrator run", runHref(r.parent.ref, r.parent.tool_call_id)]] : []),
    [agentLabel[agent] || agent],
  ]);

  return (
    <div className="page">
      <Loading state={state}>{(r) => {
        let n = 0;
        const tm = r.trigger_message;
        return (
          <>
            <div className="channel-title">
              <AgentBadge agent={agent} />
              <h1>{agent === "github_agent" ? "GitHub agent run" : "Orchestrator run"}</h1>
              <StatusBadge status={r.error ? "error" : "success"} />
            </div>
            {r.parent && (
              <p className="small">
                Called by <Link to={runHref(r.parent.ref, r.parent.tool_call_id)}>an orchestrator ask_github tool call</Link> in the same Slack thread.
              </p>
            )}
            <div className="card run-header">
              <KV k="User">{ctx.user_id ? <Link to={`/u/${enc(ctx.user_id)}`}>{userName(ctx.user_id)}</Link> : "—"}</KV>
              <KV k="Channel">{ctx.channel_id ? <Link to={`/c/${enc(ctx.channel_id)}`}># {channelName(ctx.channel_id)}</Link> : "—"}</KV>
              <KV k="Started">{fmtDateTime(isoDate(r.started_at))}</KV>
              <KV k="Duration">{fmtDur(r.duration_s)}</KV>
              <KV k="Model">{r.model || "—"}</KV>
              <KV k="Tool calls">{r.tool_calls}</KV>
              <KV k="Tokens">{fmtNum(r.usage.input)} in · {fmtNum(r.usage.output)} out</KV>
              {r.usage.reasoning ? <KV k="Reasoning">{fmtNum(r.usage.reasoning)} tokens</KV> : null}
            </div>
            {r.error && <ErrorBox>{r.error}</ErrorBox>}
            {tm && (
              <>
                <h2>{agent === "github_agent" ? "Slack message that started this interaction" : "Triggering Slack message"}</h2>
                <div className="card"><Message m={{ ...tm, run: null }} channel={tm.channel_id} inThread showChannel /></div>
              </>
            )}
            <h2>Trace</h2>
            <div className="timeline">
              {r.steps.map((s, i) => {
                if (s.kind === "prompt") {
                  return (
                    <div key={i} className={`step step-${agent}`}>
                      <div className="card">
                        <div className="step-head">
                          <span className="step-title">{agent === "github_agent" ? "Question from the orchestrator" : "Prompt to the agent"}</span>
                        </div>
                        <Prompt text={s.text} agent={agent} />
                      </div>
                    </div>
                  );
                }
                n += 1;
                const isFinal = s.kind === "final";
                return (
                  <div key={i} className={`step step-${agent}${isFinal ? " final" : ""}`}>
                    <div className="card">
                      <div className="step-head">
                        <span className="step-title">{isFinal ? "Final reply" : `Model call ${n}`}</span>
                        {s.tool_calls.length > 0 && <span className="badge">{s.tool_calls.length} tool call{s.tool_calls.length > 1 ? "s" : ""}</span>}
                        <UsageBadges usage={s.usage} />
                      </div>
                      {s.usage?.reasoning ? (
                        <div className="thinking">Reasoned for {fmtNum(s.usage.reasoning)} tokens (the model provider does not return reasoning text).</div>
                      ) : null}
                      {s.text ? <Markdown text={s.text} className="narration" /> : !s.tool_calls.length && <div className="muted small">(no text)</div>}
                      {s.tool_calls.map((c) => <ToolCall key={c.id} call={c} focus={c.id === focusCall} />)}
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        );
      }}</Loading>
    </div>
  );
}
