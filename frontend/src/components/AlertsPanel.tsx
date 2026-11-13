import { useEffect, useState } from "react";
import { api } from "../api";
import type { Alert } from "../types";
import { timeAgo } from "../ui";

const LEVEL: Record<Alert["level"], string> = {
  critical: "border-red-500/50 bg-red-500/10 text-red-300",
  warning: "border-amber-500/50 bg-amber-500/10 text-amber-200",
  info: "border-sky-500/40 bg-sky-500/10 text-sky-200",
};

interface Props {
  projectId: number;
  version: number;
  onSelectService: (id: number) => void;
  onChanged: () => void;
}

export default function AlertsPanel({ projectId, version, onSelectService, onChanged }: Props) {
  const [alerts, setAlerts] = useState<Alert[]>([]);

  useEffect(() => {
    api.alerts(projectId).then(setAlerts).catch(() => setAlerts([]));
  }, [projectId, version]);

  const unacked = alerts.filter((a) => !a.acknowledged).length;

  return (
    <div className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-slate-300">{unacked} unacknowledged</span>
        <button className="btn" disabled={unacked === 0} onClick={async () => { await api.ackAll(projectId); onChanged(); }}>Acknowledge all</button>
      </div>
      {alerts.length === 0 && <div className="text-sm text-slate-500">No alerts.</div>}
      <ul className="space-y-2">
        {alerts.map((a) => (
          <li key={a.id} className={`rounded-lg border p-2.5 text-xs ${LEVEL[a.level]} ${a.acknowledged ? "opacity-40" : ""}`}>
            <div className="mb-0.5 flex items-center justify-between text-[10px] uppercase tracking-wide opacity-70">
              <span>{a.level} · {a.kind}</span>
              <span>{timeAgo(a.created_at)}</span>
            </div>
            <div className="text-slate-100">{a.message}</div>
            <div className="mt-1.5 flex gap-2">
              {a.service_id && <button className="underline opacity-80 hover:opacity-100" onClick={() => onSelectService(a.service_id!)}>show on map</button>}
              {!a.acknowledged && <button className="underline opacity-80 hover:opacity-100" onClick={async () => { await api.ackAlert(a.id); onChanged(); }}>acknowledge</button>}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
