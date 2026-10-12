import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { Message } from "../components/Message.jsx";
import { JobsTable, RunsTable } from "../components/Tables.jsx";
import { Avatar, Badge, Empty, Loading } from "../components/ui.jsx";
import { convLabel, enc } from "../lib.js";
import { useCrumbs, useDirectory, useLiveData } from "../live.jsx";

export default function User() {
  const { id } = useParams();
  const { selectedUser, setSelectedUser, userName, allConvs } = useDirectory();
  const state = useLiveData(`/api/user/${enc(id)}`);
  const user = state.data?.user;
  useCrumbs([["People"], [user?.name || userName(id)]]);

  useEffect(() => {
    // visiting a person's page filters the sidebar to their conversations
    if (user && !user.alias_of && selectedUser !== user.id) setSelectedUser(user.id);
  }, [user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="page">
      <Loading state={state}>{(d) => {
        const groups = {};
        for (const m of d.messages) (groups[m.channel_id] ||= []).push(m);
        const tile = (label, value) => (
          <div className="tile"><div className="label">{label}</div><div className="value">{value}</div></div>
        );
        return (
          <>
            <div className="channel-title">
              <Avatar userId={d.user.id} size={44} />
              <div>
                <h1>{d.user.name}</h1>
                <div className="muted small mono">{d.user.handle ? `@${d.user.handle} · ` : ""}{d.user.slack_id || d.user.id}</div>
              </div>
              {d.user.is_bot && <Badge>bot</Badge>}
              {d.user.provider && <Badge>coding provider: {d.user.provider}</Badge>}
              {d.user.subscribed && <Badge>subscribed</Badge>}
            </div>
            <div className="tiles">
              {tile("Messages", d.messages.length)}
              {tile("Channels", d.conversations.filter((c) => !c.is_dm).length)}
              {tile("DMs", d.conversations.filter((c) => c.is_dm).length)}
              {tile("Bot mentions", d.messages.filter((m) => m.mentions_bot).length)}
              {tile("Orchestrator runs", d.runs.length)}
              {tile("Coding jobs", d.jobs.length)}
            </div>
            <h2>Messages</h2>
            {Object.keys(groups).length ? Object.entries(groups).map(([ch, ms]) => {
              const conv = allConvs.find((c) => c.id === ch) || { id: ch, members: [] };
              return (
                <div key={ch} className="card">
                  <div className="channel-title">
                    <Link to={`/c/${enc(ch)}`}><h3>{conv.is_dm ? "DM · " : "# "}{convLabel(conv, userName)}</h3></Link>
                    <span className="muted small">{ms.length} messages</span>
                  </div>
                  {ms.map((m) => <Message key={m.ts} m={m} channel={ch} inThread showChannel />)}
                </div>
              );
            }) : <Empty>No messages from this person</Empty>}
            {d.runs.length > 0 && <><h2>Agent runs started by this person</h2><div className="card"><RunsTable runs={d.runs} /></div></>}
            {d.jobs.length > 0 && <><h2>Coding jobs</h2><div className="card"><JobsTable jobs={d.jobs} /></div></>}
          </>
        );
      }}</Loading>
    </div>
  );
}
