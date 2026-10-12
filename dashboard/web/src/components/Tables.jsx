import { useNavigate } from "react-router-dom";
import { durBetween, enc, fmtDateTime, fmtDur, fmtNum, isoDate, runHref } from "../lib.js";
import { useDirectory } from "../live.jsx";
import { AgentBadge, Badge, Empty, Markdown, StatusBadge } from "./ui.jsx";

export function RunsTable({ runs }) {
  const navigate = useNavigate();
  if (!runs?.length) return <Empty>No runs recorded</Empty>;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{["Agent", "Started", "Input", "Tools", "Tokens", "Duration", ""].map((t) => <th key={t}>{t}</th>)}</tr></thead>
        <tbody>
          {runs.map((r) => (
            <tr key={`${r.ref.agent}/${r.ref.dir}/${r.ref.file}`} className="clickable" onClick={() => navigate(runHref(r.ref))}>
              <td><AgentBadge agent={r.agent} /></td>
              <td>{fmtDateTime(isoDate(r.started_at))}</td>
              <td style={{ maxWidth: 380 }}><Markdown text={r.input_preview} className="small" /></td>
              <td>{Object.entries(r.tools).map(([n, c]) => <Badge key={n} className="mono">{n}{c > 1 ? ` ×${c}` : ""}</Badge>)}</td>
              <td>{fmtNum((r.usage.input || 0) + (r.usage.output || 0))}</td>
              <td>{fmtDur(r.duration_s)}</td>
              <td><StatusBadge status={r.error ? "error" : "success"} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function JobsTable({ jobs, compact }) {
  const navigate = useNavigate();
  const { userName } = useDirectory();
  if (!jobs?.length) return <Empty>No coding jobs</Empty>;
  const cols = compact ? ["Job", "Status", "Created", "PR"] : ["Job", "Status", "Repo", "User", "Created", "Duration", "Trace files", "PR"];
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{cols.map((t) => <th key={t}>{t}</th>)}</tr></thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id} className="clickable" onClick={() => navigate(`/job/${enc(j.id)}`)}>
              <td className="mono">{j.id}</td>
              <td><StatusBadge status={j.status} /></td>
              {!compact && <td>{j.repo || "—"}@{j.base_branch || "?"}</td>}
              {!compact && <td>{userName(j.user_id)}</td>}
              <td>{fmtDateTime(isoDate(j.created_at))}</td>
              {!compact && <td>{fmtDur(durBetween(j.created_at, j.finished_at))}</td>}
              {!compact && (
                <td>
                  {(j.files || []).map((f) => <Badge key={f} className="mono">{f}</Badge>)}
                  {j.has_session && <Badge className="mono">session</Badge>}
                </td>
              )}
              <td>
                {j.pr_url
                  ? <a href={j.pr_url} target="_blank" rel="noopener" onClick={(e) => e.stopPropagation()}>#{j.pr_url.split("/").pop()}</a>
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
