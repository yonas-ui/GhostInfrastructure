import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, clearToken, getToken } from "./api";
import AlertsPanel from "./components/AlertsPanel";
import GhostPanel from "./components/GhostPanel";
import GraphView, { type Overlay } from "./components/GraphView";
import IncidentPanel from "./components/IncidentPanel";
import InspectPanel from "./components/InspectPanel";
import Login from "./components/Login";
import ManagePanel from "./components/ManagePanel";
import SimulatePanel from "./components/SimulatePanel";
import { useLiveEvents } from "./hooks/useLiveEvents";
import type { BlastRadius, Ghost, GraphDTO, LiveEvent, Project, Simulation, Summary, User } from "./types";

type Tab = "inspect" | "simulate" | "ghosts" | "incidents" | "alerts" | "manage";
const TABS: { id: Tab; label: string }[] = [
  { id: "inspect", label: "Inspect" },
  { id: "simulate", label: "Simulate" },
  { id: "ghosts", label: "Ghosts" },
  { id: "incidents", label: "Incidents" },
  { id: "alerts", label: "Alerts" },
  { id: "manage", label: "Manage" },
];

const EMPTY_GRAPH: GraphDTO = { nodes: [], edges: [] };

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [booting, setBooting] = useState(!!getToken());

  useEffect(() => {
    if (!getToken()) return;
    api.me().then(setUser).catch(() => clearToken()).finally(() => setBooting(false));
  }, []);
  useEffect(() => {
    const onUnauthorized = () => {
      clearToken();
      setUser(null);
    };
    window.addEventListener("ghost:unauthorized", onUnauthorized);
    return () => window.removeEventListener("ghost:unauthorized", onUnauthorized);
  }, []);

  if (booting) return <div className="flex h-full items-center justify-center text-slate-500">Loading…</div>;
  if (!user) return <Login onLogin={setUser} />;
  return <Workspace user={user} onLogout={() => { clearToken(); setUser(null); }} />;
}

function Workspace({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [graph, setGraph] = useState<GraphDTO>(EMPTY_GRAPH);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [version, setVersion] = useState(0);
  const [tab, setTab] = useState<Tab>("inspect");
  const [toast, setToast] = useState("");

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<number | null>(null);
  const [impact, setImpact] = useState<BlastRadius | null>(null);
  const [failed, setFailed] = useState<Set<number>>(new Set());
  const [simResult, setSimResult] = useState<BlastRadius | null>(null);
  const [focus, setFocus] = useState<Ghost | null>(null);

  // ------------------------------------------------------------ data loading
  useEffect(() => {
    api.projects().then((ps) => {
      setProjects(ps);
      setProjectId((cur) => cur ?? ps[0]?.id ?? null);
    });
  }, []);

  const refresh = useCallback(async () => {
    if (projectId == null) return;
    const [g, s] = await Promise.all([api.graph(projectId), api.summary(projectId)]);
    setGraph(g);
    setSummary(s);
    setVersion((v) => v + 1);
  }, [projectId]);

  useEffect(() => {
    setSelectedId(null);
    setSelectedEdgeId(null);
    setImpact(null);
    setFailed(new Set());
    setSimResult(null);
    setFocus(null);
    if (projectId != null) refresh().catch(() => undefined);
  }, [projectId, refresh]);

  // live updates (debounced so a burst of events causes one refresh)
  const timer = useRef<number>();
  const onLive = useCallback(
    (e: LiveEvent) => {
      if (e.type === "incident_opened") setToast(`Incident opened: ${String(e.data.title ?? "")}`);
      if (e.type === "incident_resolved") setToast("An incident was auto-resolved");
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => refresh().catch(() => undefined), 250);
    },
    [refresh],
  );
  const live = useLiveEvents(projectId, onLive);
  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(""), 6000);
    return () => window.clearTimeout(t);
  }, [toast]);

  // blast radius of the selected service (outside of simulate mode)
  useEffect(() => {
    if (projectId == null || selectedId == null || tab === "simulate") {
      setImpact(null);
      return;
    }
    let ok = true;
    api.impact(projectId, selectedId).then((r) => ok && setImpact(r)).catch(() => ok && setImpact(null));
    return () => {
      ok = false;
    };
  }, [projectId, selectedId, tab, version]);

  // ---------------------------------------------------------------- handlers
  const names = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n.name])), [graph]);

  const selectService = useCallback((id: number) => {
    setTab("inspect");
    setSelectedId(id);
    setSelectedEdgeId(null);
    setFocus(null);
  }, []);

  const onNodeClick = (id: number) => {
    if (tab === "simulate") {
      setFailed((prev) => {
        const next = new Set(prev);
        next.has(id) ? next.delete(id) : next.add(id);
        return next;
      });
      setSimResult(null);
      return;
    }
    selectService(id);
  };
  const onEdgeClick = (id: number) => {
    if (tab === "simulate") return;
    setTab("inspect");
    setSelectedEdgeId(id);
    setFocus(null);
  };
  const onPaneClick = () => {
    if (tab !== "simulate") {
      setSelectedId(null);
      setSelectedEdgeId(null);
    }
  };
  const changeTab = (t: Tab) => {
    setTab(t);
    if (t !== "ghosts") setFocus(null);
  };
  const loadSimulation = (s: Simulation) => {
    setFailed(new Set(s.failed_service_ids));
    setSimResult(s.result);
  };

  const overlay: Overlay = useMemo(() => {
    if (tab === "simulate") {
      return {
        selected: null,
        failed,
        affected: new Map((simResult?.affected ?? []).map((a) => [a.id, a.depth])),
        focusNodes: new Set(),
        focusEdges: new Set(),
      };
    }
    return {
      selected: selectedId,
      failed: new Set(),
      affected: new Map((impact?.affected ?? []).map((a) => [a.id, a.depth])),
      focusNodes: new Set(tab === "ghosts" && focus ? focus.service_ids : []),
      focusEdges: new Set(tab === "ghosts" && focus ? focus.edge_ids : []),
    };
  }, [tab, failed, simResult, selectedId, impact, focus]);

  const selectedEdge = graph.edges.find((e) => e.id === selectedEdgeId) ?? null;

  const createProject = async () => {
    const name = window.prompt("Project name");
    if (!name?.trim()) return;
    const p = await api.createProject(name.trim());
    setProjects((ps) => [...ps, p]);
    setProjectId(p.id);
    setTab("manage");
  };

  // ------------------------------------------------------------------ render
  const badge = (t: Tab) => {
    if (t === "incidents" && summary?.open_incidents) return summary.open_incidents;
    if (t === "alerts" && summary?.unacknowledged_alerts) return summary.unacknowledged_alerts;
    if (t === "ghosts" && summary?.ghost_findings) return summary.ghost_findings;
    return 0;
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-ink-600 bg-ink-900 px-4 py-2">
        <div className="text-sm font-semibold tracking-wide text-white">
          <span className="text-violet-300">◌</span> Ghost Infrastructure
        </div>
        <select className="input !w-auto max-w-[260px]" value={projectId ?? ""} onChange={(e) => setProjectId(Number(e.target.value))}>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <button className="btn" onClick={createProject}>+ Project</button>

        {summary && (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Pill label="services" value={summary.services} />
            <Pill label="dependencies" value={summary.dependencies} />
            <Pill label="undocumented" value={summary.undocumented_dependencies} tone={summary.undocumented_dependencies ? "amber" : undefined} />
            <Pill label="down" value={summary.by_status.down ?? 0} tone={summary.by_status.down ? "red" : undefined} />
            <Pill label="open incidents" value={summary.open_incidents} tone={summary.open_incidents ? "red" : undefined} />
          </div>
        )}

        <div className="ml-auto flex items-center gap-3 text-xs text-slate-400">
          <span className="flex items-center gap-1.5" title={live ? "Receiving live updates" : "Reconnecting…"}>
            <span className={`h-2 w-2 rounded-full ${live ? "bg-emerald-400" : "bg-slate-600"}`} /> {live ? "live" : "offline"}
          </span>
          <span>{user.name}</span>
          <button className="btn" onClick={onLogout}>Sign out</button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <main className="relative min-w-0 flex-1">
          {graph.nodes.length === 0 ? (
            <div className="flex h-full items-center justify-center p-8 text-center text-slate-400">
              <div>
                <div className="text-lg text-slate-200">This project has no services yet.</div>
                <div className="mt-1 text-sm">Open the <b>Manage</b> tab to add services, or import a docker-compose file to discover them.</div>
              </div>
            </div>
          ) : (
            <GraphView graph={graph} overlay={overlay} onNodeClick={onNodeClick} onEdgeClick={onEdgeClick} onPaneClick={onPaneClick} />
          )}

          <Legend simulate={tab === "simulate"} />
          {toast && (
            <div className="absolute left-1/2 top-4 -translate-x-1/2 rounded-lg border border-red-500/50 bg-red-950/90 px-4 py-2 text-sm text-red-200 shadow-xl">{toast}</div>
          )}
        </main>

        <aside className="flex w-[420px] shrink-0 flex-col border-l border-ink-600 bg-ink-900">
          <nav className="flex border-b border-ink-600">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => changeTab(t.id)}
                className={`relative flex-1 px-1 py-2.5 text-xs font-medium transition ${tab === t.id ? "border-b-2 border-sky-400 text-white" : "text-slate-400 hover:text-slate-200"}`}
              >
                {t.label}
                {badge(t.id) > 0 && (
                  <span className={`ml-1 rounded-full px-1.5 text-[10px] ${t.id === "incidents" ? "bg-red-500/25 text-red-300" : "bg-ink-600 text-slate-300"}`}>{badge(t.id)}</span>
                )}
              </button>
            ))}
          </nav>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {projectId != null && tab === "inspect" && (
              <InspectPanel
                serviceId={selectedId}
                edge={selectedEdge}
                names={names}
                impact={impact}
                version={version}
                onSelect={selectService}
                onChanged={() => { refresh().catch(() => undefined); }}
                onClearEdge={() => { setSelectedEdgeId(null); refresh().catch(() => undefined); }}
              />
            )}
            {projectId != null && tab === "simulate" && (
              <SimulatePanel
                projectId={projectId}
                failed={failed}
                names={names}
                result={simResult}
                version={version}
                onToggle={(id) => { setFailed((p) => { const n = new Set(p); n.delete(id); return n; }); setSimResult(null); }}
                onClear={() => { setFailed(new Set()); setSimResult(null); }}
                onResult={setSimResult}
                onLoad={loadSimulation}
              />
            )}
            {projectId != null && tab === "ghosts" && <GhostPanel projectId={projectId} version={version} focused={focus} onFocus={setFocus} />}
            {projectId != null && tab === "incidents" && (
              <IncidentPanel projectId={projectId} version={version} onSelectService={selectService} onChanged={() => { refresh().catch(() => undefined); }} />
            )}
            {projectId != null && tab === "alerts" && (
              <AlertsPanel projectId={projectId} version={version} onSelectService={selectService} onChanged={() => { refresh().catch(() => undefined); }} />
            )}
            {projectId != null && tab === "manage" && <ManagePanel projectId={projectId} nodes={graph.nodes} onChanged={() => { refresh().catch(() => undefined); }} />}
          </div>
        </aside>
      </div>
    </div>
  );
}

function Pill({ label, value, tone }: { label: string; value: number; tone?: "red" | "amber" }) {
  const cls = tone === "red" ? "border-red-500/50 bg-red-500/10 text-red-300" : tone === "amber" ? "border-amber-500/50 bg-amber-500/10 text-amber-300" : "border-ink-600 text-slate-300";
  return (
    <span className={`rounded-full border px-2 py-0.5 ${cls}`}>
      <b className="mr-1 font-semibold">{value}</b>{label}
    </span>
  );
}

function Legend({ simulate }: { simulate: boolean }) {
  return (
    <div className="pointer-events-none absolute left-3 top-3 space-y-1 rounded-lg border border-ink-600 bg-ink-900/90 px-3 py-2 text-[11px] text-slate-300">
      {simulate && <div className="font-semibold text-red-300">Simulation mode: click services to fail them</div>}
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-400" />healthy</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-amber-400" />degraded</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-red-500" />down</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-orange-400" />impacted</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-slate-500" />unknown</span>
      </div>
      <div className="flex gap-3">
        <span><i className="mr-1 inline-block w-5 border-t border-slate-500 align-middle" />documented</span>
        <span><i className="mr-1 inline-block w-5 border-t-2 border-dashed border-amber-500 align-middle" />undocumented</span>
      </div>
    </div>
  );
}
