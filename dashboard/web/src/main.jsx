import React, { useEffect } from "react";
import ReactDOM from "react-dom/client";
import { HashRouter, Route, Routes, useLocation } from "react-router-dom";
import { Layout } from "./components/Layout.jsx";
import { CrumbsProvider, DirectoryProvider, LiveProvider } from "./live.jsx";
import Channel from "./pages/Channel.jsx";
import { Job, Jobs } from "./pages/Jobs.jsx";
import Overview from "./pages/Overview.jsx";
import { Run, Runs } from "./pages/Runs.jsx";
import User from "./pages/User.jsx";
import "./styles.css";

try {
  const theme = localStorage.getItem("theme");
  if (theme) document.documentElement.dataset.theme = theme;
} catch { /* storage unavailable */ }

function Pages() {
  const location = useLocation();
  const isChannel = location.pathname.startsWith("/c/");
  useEffect(() => {
    if (!isChannel) document.querySelector(".main")?.scrollTo(0, 0);
  }, [location.pathname, isChannel]);
  return (
    <Layout flush={isChannel}>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/c/:ch" element={<Channel />} />
        <Route path="/c/:ch/t/:ts" element={<Channel />} />
        <Route path="/c/:ch/t/:ts/:msg" element={<Channel />} />
        <Route path="/u/:id" element={<User />} />
        <Route path="/runs" element={<Runs />} />
        <Route path="/runs/:agent" element={<Runs />} />
        <Route path="/run/:agent/:dir/:file" element={<Run />} />
        <Route path="/run/:agent/:dir/:file/:call" element={<Run />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route path="/job/:id" element={<Job />} />
        <Route path="/job/:id/:tab" element={<Job />} />
        <Route path="*" element={<div className="empty">Page not found</div>} />
      </Routes>
    </Layout>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <HashRouter>
      <LiveProvider>
        <DirectoryProvider>
          <CrumbsProvider>
            <Pages />
          </CrumbsProvider>
        </DirectoryProvider>
      </LiveProvider>
    </HashRouter>
  </React.StrictMode>,
);
