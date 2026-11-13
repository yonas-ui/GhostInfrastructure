import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import type { Incident, IncidentDetail, RootCause } from "../types";
import { SEVERITY_BADGE, timeAgo } from "../ui";

interface Props {
  projectId: number;
  version: number;
  onSelectService: (id: number) => void;
  onChanged: () => void;
}

const EVENT_STYLE: Record<string, string> = {
  detected: "bg-red-400",
  impact: "bg-orange-400",
  deployment: "bg-violet-400",
  resolved: "bg-emerald-400",
  status_change: "bg-sky-400",
  note: "bg-slate-400",
};

export default function IncidentPanel({ projectId, version, onSelectService, onChanged }: Props) {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [causes, setCauses] = useState<RootCause[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [detail, setDetail] = useState<IncidentDetail | null>(null);
  const [note, setNote] = useState("");

  useEffect(() => {
    api.incidents(projectId).then(setIncidents).catch(() => setIncidents([]));
    api.rootCause(projectId).then((r) => setCauses(r.candidates)).catch(() => setCauses([]));
  }, [projectId, version]);

  useEffect(() => {
    if (openId == null) return setDetail(null);
    api.incident(openId).then(setDetail).catch(() => setDetail(null));
  }, [openId, version]);

  const addNote = async (e: FormEvent) => {
    e.preventDefault();
    if (!openId || !note.trim()) return;
    await api.addIncidentNote(openId, note.trim());
    setNote("");
    onChanged();
  };

  const setStatus = async (status: string) => {
    if (!openId) return;
    await api.updateIncident(openId, { status });
    onChanged();
  };

  return (
    <div className="space-y-3 p-4">
      {causes.length > 0 && (
        <div className="card space-y-2 !border-red-500/40 bg-red-950/20">
          <div className="label !mb-0 !text-red-300">Likely root cause right now</div>
          {causes.map((c) => (
            <button key={c.service_id} onClick={() => onSelectService(c.service_id)} className="block w-full text-left">
              <span className="text-sm font-semibold text-white">{c.name}</span>
              <span className="ml-2 text-xs text-slate-400">
                {c.status} · explains {c.explains_count} other failing service{c.explains_count === 1 ? "" : "s"}
                {c.in_cycle ? " · part of a dependency cycle" : ""}
              </span>
            </button>
          ))}
        </div>
      )}

      {incidents.length === 0 && <div className="text-sm text-slate-500">No incidents recorded.</div>}
      <ul className="space-y-2">
        {incidents.map((i) => (
          <li key={i.id}>
            <button onClick={() => setOpenId(openId === i.id ? null : i.id)} className={`card w-full text-left hover:border-sky-500/50 ${openId === i.id ? "!border-sky-500/60" : ""}`}>
              <div className="flex items-center gap-2">
                <span className={`chip ${SEVERITY_BADGE[i.severity]}`}>{i.severity}</span>
                <span className={`chip ${i.status === "resolved" ? "border-emerald-500/40 text-emerald-300" : "border-red-500/40 text-red-300"}`}>{i.status}</span>
                {i.auto_detected && <span className="chip border-violet-500/40 text-violet-300">auto</span>}
                <span className="ml-auto text-[11px] text-slate-500">{timeAgo(i.started_at)}</span>
              </div>
              <div className="mt-1 text-sm font-medium text-slate-100">{i.title}</div>
              <div className="text-xs text-slate-400">{i.summary}</div>
            </button>

            {openId === i.id && detail && (
              <div className="mt-2 space-y-3 rounded-lg border border-ink-600 bg-ink-900 p-3">
                <div className="flex flex-wrap gap-2">
                  {i.root_cause_service_id && <button className="btn" onClick={() => onSelectService(i.root_cause_service_id!)}>Show root cause on map</button>}
                  {i.status !== "resolved" ? (
                    <>
                      <button className="btn" onClick={() => setStatus("identified")}>Mark identified</button>
                      <button className="btn" onClick={() => setStatus("monitoring")}>Monitoring</button>
                      <button className="btn btn-primary" onClick={() => setStatus("resolved")}>Resolve</button>
                    </>
                  ) : (
                    <button className="btn" onClick={() => setStatus("investigating")}>Reopen</button>
                  )}
                </div>
                <ol className="relative space-y-3 border-l border-ink-600 pl-4">
                  {detail.events.map((e) => (
                    <li key={e.id} className="relative">
                      <span className={`absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full ${EVENT_STYLE[e.event_type] ?? "bg-slate-400"}`} />
                      <div className="text-[10px] uppercase tracking-wide text-slate-500">{e.event_type.replace("_", " ")} · {timeAgo(e.created_at)}</div>
                      <div className="text-xs text-slate-200">{e.message}</div>
                    </li>
                  ))}
                </ol>
                <form onSubmit={addNote} className="flex gap-2">
                  <input className="input" placeholder="Add a note to the timeline…" value={note} onChange={(e) => setNote(e.target.value)} />
                  <button className="btn btn-primary">Add</button>
                </form>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
