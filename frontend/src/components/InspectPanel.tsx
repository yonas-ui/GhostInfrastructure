import { useEffect, useState } from "react";
import { api } from "../api";
import type { BlastRadius, GEdgeDTO, ServiceDetail } from "../types";
import { SEVERITY_BADGE, STATUS_TEXT, TYPE_LABEL, timeAgo } from "../ui";

interface Props {
  serviceId: number | null;
  edge: GEdgeDTO | null;
  names: Map<number, string>;
  impact: BlastRadius | null;
  version: number;
  onSelect: (id: number) => void;
  onChanged: () => void;
  onClearEdge: () => void;
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return <div className="text-xs text-slate-500">Not enough probe data yet</div>;
  const max = Math.max(...values, 1);
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 200},${34 - (v / max) * 30}`).join(" ");
  return (
    <svg viewBox="0 0 200 36" className="h-9 w-full">
      <polyline points={pts} fill="none" stroke="#38bdf8" strokeWidth="1.5" />
    </svg>
  );
}

export default function InspectPanel({ serviceId, edge, names, impact, version, onSelect, onChanged, onClearEdge }: Props) {
  const [detail, setDetail] = useState<ServiceDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (serviceId == null) {
      setDetail(null);
      return;
    }
    let live = true;
    api.service(serviceId).then((d) => live && setDetail(d)).catch(() => live && setDetail(null));
    return () => {
      live = false;
    };
  }, [serviceId, version]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  if (edge) {
    return (
      <div className="space-y-3 p-4">
        <div className="card space-y-2">
          <div className="text-xs uppercase tracking-wide text-slate-400">Dependency</div>
          <div className="text-sm font-semibold text-white">
            {names.get(edge.source)} <span className="text-slate-500">depends on</span> {names.get(edge.target)}
          </div>
          <div className="flex flex-wrap gap-1.5">
            <span className={`chip ${edge.documented ? "border-emerald-500/40 text-emerald-300" : "border-amber-500/50 bg-amber-500/10 text-amber-300"}`}>
              {edge.documented ? "documented" : "undocumented"}
            </span>
            <span className="chip border-ink-600 text-slate-300">{edge.kind}</span>
            <span className="chip border-ink-600 text-slate-300">found via {edge.discovered_by}</span>
            {edge.observed_count > 0 && <span className="chip border-ink-600 text-slate-300">seen {edge.observed_count}×</span>}
          </div>
          {error && <div className="text-xs text-red-400">{error}</div>}
          <div className="flex gap-2 pt-1">
            {!edge.documented && (
              <button className="btn btn-primary" disabled={busy} onClick={() => act(async () => { await api.updateDependency(edge.id, { documented: true }); onClearEdge(); })}>
                Mark as documented
              </button>
            )}
            <button className="btn btn-danger" disabled={busy} onClick={() => act(async () => { await api.deleteDependency(edge.id); onClearEdge(); })}>
              Remove
            </button>
            <button className="btn" onClick={onClearEdge}>Close</button>
          </div>
        </div>
      </div>
    );
  }

  if (serviceId == null || !detail) {
    return (
      <div className="space-y-3 p-4 text-sm text-slate-400">
        <p className="text-slate-200">Click any service on the map to see what depends on it and what breaks if it fails.</p>
        <ul className="list-disc space-y-1 pl-5 text-xs">
          <li>Arrows point from a service to the thing it depends on.</li>
          <li><span className="text-amber-300">Dashed amber</span> lines are undocumented ("ghost") dependencies.</li>
          <li>Click a dashed line to review it and mark it documented.</li>
          <li>Use the <b>Simulate</b> tab to fail several services at once.</li>
        </ul>
      </div>
    );
  }

  const svc = detail.service;
  const latencies = detail.health.map((h) => h.latency_ms).filter((v): v is number => v != null);
  const byDepth = new Map<number, BlastRadius["affected"]>();
  impact?.affected.forEach((a) => byDepth.set(a.depth, [...(byDepth.get(a.depth) ?? []), a]));

  return (
    <div className="space-y-3 p-4">
      <div>
        <div className="flex items-center gap-2">
          <h2 className="truncate text-lg font-semibold text-white">{svc.name}</h2>
          <span className="chip border-ink-600 text-slate-300">{TYPE_LABEL[svc.type] ?? svc.type}</span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
          <span className={`font-semibold uppercase ${STATUS_TEXT[svc.status]}`}>{svc.status}</span>
          <span>criticality {svc.criticality}/5</span>
          <span>owner: {svc.owner || <b className="text-amber-300">none</b>}</span>
          <span>checked {timeAgo(svc.last_checked_at)}</span>
        </div>
      </div>

      <div className="card space-y-2">
        <div className="flex items-center justify-between">
          <span className="label !mb-0">Report status</span>
          <span className="text-[10px] text-slate-500">simulates an outage for real</span>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn" disabled={busy} onClick={() => act(() => api.reportHealth(svc.id, "healthy"))}>Healthy</button>
          <button className="btn" disabled={busy} onClick={() => act(() => api.reportHealth(svc.id, "degraded"))}>Degraded</button>
          <button className="btn btn-danger" disabled={busy} onClick={() => act(() => api.reportHealth(svc.id, "down"))}>Down</button>
          {svc.health_url && <button className="btn" disabled={busy} onClick={() => act(() => api.checkNow(svc.id))}>Probe now</button>}
        </div>
        {error && <div className="text-xs text-red-400">{error}</div>}
        <Sparkline values={latencies} />
      </div>

      {impact && (
        <div className="card space-y-2">
          <div className="flex items-center justify-between">
            <span className="label !mb-0">If {svc.name} fails</span>
            <span className={`chip ${SEVERITY_BADGE[impact.severity]}`}>{impact.severity}</span>
          </div>
          {impact.affected_count === 0 ? (
            <div className="text-sm text-emerald-300">Nothing else depends on it.</div>
          ) : (
            <>
              <div className="text-sm text-slate-200">
                <b className="text-orange-300">{impact.affected_count}</b> services break ({impact.percent_affected}% of the estate), up to {impact.max_depth} hops away.
              </div>
              {impact.user_facing.length > 0 && (
                <div className="text-xs text-slate-400">User-facing: <span className="text-slate-200">{impact.user_facing.join(", ")}</span></div>
              )}
              <div className="max-h-40 space-y-1 overflow-y-auto text-xs">
                {[...byDepth.entries()].sort((a, b) => a[0] - b[0]).map(([d, list]) => (
                  <div key={d}>
                    <span className="mr-1 text-slate-500">hop {d}:</span>
                    {list.map((a) => (
                      <button key={a.id} onClick={() => onSelect(a.id)} className="mr-1.5 text-orange-300 hover:underline" title={a.path_names.join(" → ")}>{a.name}</button>
                    ))}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      <RelationList title="Depends on" items={detail.depends_on} onSelect={onSelect} />
      <RelationList title="Depended on by" items={detail.depended_on_by} onSelect={onSelect} />

      {detail.deployments.length > 0 && (
        <div className="card">
          <div className="label">Recent deployments</div>
          <ul className="space-y-1 text-xs text-slate-300">
            {detail.deployments.slice(0, 4).map((d) => (
              <li key={d.id} className="flex justify-between"><span className="font-mono">{d.version}</span><span className="text-slate-500">{d.deployed_by || "?"} · {timeAgo(d.deployed_at)}</span></li>
            ))}
          </ul>
        </div>
      )}

      <button
        className="btn btn-danger"
        disabled={busy}
        onClick={() => window.confirm(`Delete ${svc.name} and all its dependencies?`) && act(() => api.deleteService(svc.id))}
      >
        Delete service
      </button>
    </div>
  );
}

function RelationList({ title, items, onSelect }: { title: string; items: ServiceDetail["depends_on"]; onSelect: (id: number) => void }) {
  return (
    <div className="card">
      <div className="label">{title} ({items.length})</div>
      {items.length === 0 ? (
        <div className="text-xs text-slate-500">none</div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {items.map((r) => (
            <button
              key={r.id}
              onClick={() => onSelect(r.service_id)}
              className={`rounded border px-1.5 py-0.5 text-xs hover:bg-ink-600 ${r.documented ? "border-ink-600 text-slate-200" : "border-dashed border-amber-500/60 text-amber-300"}`}
              title={r.documented ? r.kind : `undocumented · ${r.kind}`}
            >
              {r.service_name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
