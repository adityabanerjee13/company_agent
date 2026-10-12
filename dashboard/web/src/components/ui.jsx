import { agentLabel, renderMarkdown } from "../lib.js";
import { useDirectory } from "../live.jsx";

export const Badge = ({ children, className = "", ...rest }) => <span className={`badge ${className}`} {...rest}>{children}</span>;
export const StatusBadge = ({ status }) => <Badge className={`status status-${status || "unknown"}`}>{status || "unknown"}</Badge>;
export const AgentBadge = ({ agent }) => <Badge className={`agent-badge agent-${agent}`}>{agentLabel[agent] || agent}</Badge>;
export const Pre = ({ children }) => <pre>{children ?? ""}</pre>;
export const Json = ({ value }) => <pre>{JSON.stringify(value, null, 2)}</pre>;
export const Empty = ({ children }) => <div className="empty">{children}</div>;
export const ErrorBox = ({ children }) => <div className="error-box">{children}</div>;

export function KV({ k, children }) {
  return (
    <div className="kv">
      <span className="k">{k}</span>
      <span className="v">{children}</span>
    </div>
  );
}

export function Markdown({ text, className = "md" }) {
  const { userName, channelName } = useDirectory();
  // renderMarkdown escapes everything before adding its own tags
  return <div className={className} dangerouslySetInnerHTML={{ __html: renderMarkdown(text, userName, channelName) }} />;
}

export function Avatar({ userId, size = 36 }) {
  const { userName, isBot, user } = useDirectory();
  const u = user(userId);
  const bot = isBot(userId);
  const style = { width: size, height: size };
  if (u?.avatar) return <img className="avatar" src={u.avatar} alt="" style={style} />;
  return <div className={`avatar${bot ? " bot" : ""}`} style={style}>{bot ? "◆" : (userName(userId)[0] || "?").toUpperCase()}</div>;
}

export function Loading({ state, children }) {
  if (state.error) return <ErrorBox>Could not load: {state.error.message}</ErrorBox>;
  if (state.loading) return <Empty>Loading…</Empty>;
  return children(state.data);
}
