import { useState, type FormEvent } from "react";
import { api } from "../api";
import type { GNodeDTO } from "../types";
import { SERVICE_TYPES } from "../ui";

interface Props {
  projectId: number;
  nodes: GNodeDTO[];
  onChanged: () => void;
}

export default function ManagePanel({ projectId, nodes, onChanged }: Props) {
  const sorted = [...nodes].sort((a, b) => a.name.localeCompare(b.name));
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const run = async (fn: () => Promise<string>) => {
    try {
      setMsg({ ok: true, text: await fn() });
      onChanged();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    }
  };

  // ---- add service
  const [svc, setSvc] = useState({ name: "", type: "api", criticality: 3, owner: "", health_url: "" });
  const addService = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      await api.createService(projectId, { ...svc, health_url: svc.health_url || null });
      setSvc({ ...svc, name: "", health_url: "" });
      return `Added ${svc.name}`;
    });
  };

  // ---- add dependency
  const [dep, setDep] = useState({ source_id: 0, target_id: 0, kind: "http", documented: true });
  const addDep = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      await api.createDependency(projectId, dep);
      return "Dependency added";
    });
  };

  // ---- discovery
  const [lines, setLines] = useState("");
  const [compose, setCompose] = useState("");
  const importObservations = () =>
    run(async () => {
      const observations = lines
        .split("\n")
        .map((l) => l.split("->").map((s) => s.trim()))
        .filter((p) => p.length === 2 && p[0] && p[1])
        .map(([source, target]) => ({ source, target }));
      if (observations.length === 0) throw new Error('Use one "source -> target" pair per line');
      const r = await api.discoverObservations(projectId, observations);
      return `${r.new_dependencies.length} new undocumented dependencies found`;
    });
  const importCompose = () =>
    run(async () => {
      const r = await api.discoverCompose(projectId, compose);
      return `Imported ${r.new_services.length} services, ${r.new_dependencies.length} dependencies`;
    });

  return (
    <div className="space-y-4 p-4">
      {msg && <div className={`rounded-md border px-3 py-2 text-xs ${msg.ok ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" : "border-red-500/40 bg-red-500/10 text-red-300"}`}>{msg.text}</div>}

      <form onSubmit={addService} className="card space-y-2">
        <div className="label !mb-0">Add service</div>
        <input className="input" placeholder="name" value={svc.name} onChange={(e) => setSvc({ ...svc, name: e.target.value })} required />
        <div className="grid grid-cols-2 gap-2">
          <select className="input" value={svc.type} onChange={(e) => setSvc({ ...svc, type: e.target.value })}>
            {SERVICE_TYPES.map((t) => <option key={t}>{t}</option>)}
          </select>
          <select className="input" value={svc.criticality} onChange={(e) => setSvc({ ...svc, criticality: Number(e.target.value) })}>
            {[1, 2, 3, 4, 5].map((c) => <option key={c} value={c}>criticality {c}</option>)}
          </select>
        </div>
        <input className="input" placeholder="owner (team)" value={svc.owner} onChange={(e) => setSvc({ ...svc, owner: e.target.value })} />
        <input className="input" placeholder="health URL (https://… or tcp://host:5432) — optional" value={svc.health_url} onChange={(e) => setSvc({ ...svc, health_url: e.target.value })} />
        <button className="btn btn-primary">Add service</button>
      </form>

      <form onSubmit={addDep} className="card space-y-2">
        <div className="label !mb-0">Add dependency</div>
        <select className="input" value={dep.source_id} onChange={(e) => setDep({ ...dep, source_id: Number(e.target.value) })} required>
          <option value={0} disabled>this service…</option>
          {sorted.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
        </select>
        <div className="text-center text-[11px] text-slate-500">depends on</div>
        <select className="input" value={dep.target_id} onChange={(e) => setDep({ ...dep, target_id: Number(e.target.value) })} required>
          <option value={0} disabled>that service…</option>
          {sorted.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
        </select>
        <label className="flex items-center gap-2 text-xs text-slate-300">
          <input type="checkbox" checked={dep.documented} onChange={(e) => setDep({ ...dep, documented: e.target.checked })} /> documented
        </label>
        <button className="btn btn-primary" disabled={!dep.source_id || !dep.target_id}>Add dependency</button>
      </form>

      <div className="card space-y-2">
        <div className="label !mb-0">Discover from runtime observations</div>
        <p className="text-[11px] text-slate-500">Paste caller → callee pairs from traces or access logs. Anything new is flagged as an undocumented ghost.</p>
        <textarea className="input h-20 font-mono text-xs" placeholder={"checkout-ui -> fraud-api\nreports-cron -> pg-core"} value={lines} onChange={(e) => setLines(e.target.value)} />
        <button className="btn" onClick={importObservations} disabled={!lines.trim()}>Import observations</button>
      </div>

      <div className="card space-y-2">
        <div className="label !mb-0">Discover from docker-compose</div>
        <p className="text-[11px] text-slate-500">Reads depends_on, links and hostnames hiding in environment variables (DATABASE_URL, REDIS_URL…).</p>
        <textarea className="input h-28 font-mono text-xs" placeholder={"services:\n  api:\n    environment:\n      DATABASE_URL: postgres://u@db/app\n  db:\n    image: postgres:16"} value={compose} onChange={(e) => setCompose(e.target.value)} />
        <button className="btn" onClick={importCompose} disabled={!compose.trim()}>Import compose file</button>
      </div>
    </div>
  );
}
