import { useEffect, useState } from "react";
import { api } from "../api";
import type { BlastRadius, Simulation } from "../types";
import { SEVERITY_BADGE, TYPE_LABEL, timeAgo } from "../ui";

interface Props {
  projectId: number;
  failed: Set<number>;
  names: Map<number, string>;
  result: BlastRadius | null;
  version: number;
  onToggle: (id: number) => void;
  onClear: () => void;
  onResult: (r: BlastRadius | null) => void;
  onLoad: (sim: Simulation) => void;
}

export default function SimulatePanel({ projectId, failed, names, result, version, onToggle, onClear, onResult, onLoad }: Props) {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<Simulation[]>([]);

  useEffect(() => {
    api.simulations(projectId).then(setHistory).catch(() => setHistory([]));
  }, [projectId, version]);

  const run = async () => {
    setRunning(true);
    setError("");
    try {
      const sim = await api.simulate(projectId, [...failed]);
      onResult(sim.result);
      setHistory((h) => [sim, ...h]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Simulation failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-3 p-4">
      <div className="text-sm text-slate-300">
        Click services on the map to mark them as <b className="text-red-400">failed</b>, then run the simulation to see everything that would break.
        Nothing is changed in your real data.
      </div>

      <div className="card space-y-2">
        <div className="label">Failed services ({failed.size})</div>
        <div className="flex flex-wrap gap-1.5">
          {failed.size === 0 && <span className="text-xs text-slate-500">none selected</span>}
          {[...failed].map((id) => (
            <button key={id} onClick={() => onToggle(id)} className="rounded border border-red-500/50 bg-red-500/10 px-1.5 py-0.5 text-xs text-red-300 hover:bg-red-500/20">
              {names.get(id)} ✕
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <button className="btn btn-primary" disabled={failed.size === 0 || running} onClick={run}>{running ? "Running…" : "Run simulation"}</button>
          <button className="btn" onClick={onClear} disabled={failed.size === 0 && !result}>Reset</button>
        </div>
        {error && <div className="text-xs text-red-400">{error}</div>}
      </div>

      {result && (
        <div className="card space-y-3">
          <div className="flex items-center justify-between">
            <span className="label !mb-0">Result</span>
            <span className={`chip ${SEVERITY_BADGE[result.severity]}`}>{result.severity} impact</span>
          </div>
          <div>
            <div className="mb-1 flex justify-between text-xs text-slate-400"><span>Business impact score</span><span className="font-mono text-slate-200">{result.impact_score}/100</span></div>
            <div className="h-2 overflow-hidden rounded bg-ink-600"><div className="h-full rounded bg-gradient-to-r from-amber-400 to-red-500" style={{ width: `${result.impact_score}%` }} /></div>
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            <Stat label="affected" value={result.affected_count} />
            <Stat label="% of estate" value={`${result.percent_affected}%`} />
            <Stat label="max hops" value={result.max_depth} />
          </div>
          {Object.keys(result.by_type).length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(result.by_type).map(([t, n]) => (
                <span key={t} className="chip border-ink-600 text-slate-300">{n} {TYPE_LABEL[t] ?? t}</span>
              ))}
            </div>
          )}
          {result.user_facing.length > 0 && (
            <div className="text-xs text-slate-400">User-facing apps down: <span className="text-slate-200">{result.user_facing.join(", ")}</span></div>
          )}
          {result.affected.length > 0 && (
            <div>
              <div className="label">Longest chain</div>
              <div className="text-xs text-orange-300">
                {[...result.affected].sort((a, b) => b.depth - a.depth)[0].path_names.join(" → ")}
              </div>
            </div>
          )}
        </div>
      )}

      {history.length > 0 && (
        <div className="card">
          <div className="label">Previous simulations</div>
          <ul className="space-y-1">
            {history.slice(0, 8).map((s) => (
              <li key={s.id}>
                <button onClick={() => onLoad(s)} className="flex w-full items-center justify-between gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-ink-600">
                  <span className="truncate text-slate-200">{s.name}</span>
                  <span className="shrink-0 text-slate-500">{s.result.affected_count} hit · {timeAgo(s.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md bg-ink-900 py-1.5">
      <div className="text-lg font-semibold text-white">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
    </div>
  );
}
