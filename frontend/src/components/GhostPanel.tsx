import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Ghost } from "../types";
import { GHOST_LABEL, SEVERITY_BADGE } from "../ui";

interface Props {
  projectId: number;
  version: number;
  focused: Ghost | null;
  onFocus: (g: Ghost | null) => void;
}

export default function GhostPanel({ projectId, version, focused, onFocus }: Props) {
  const [ghosts, setGhosts] = useState<Ghost[]>([]);
  const [filter, setFilter] = useState("all");

  useEffect(() => {
    api.ghosts(projectId).then(setGhosts).catch(() => setGhosts([]));
  }, [projectId, version]);

  const kinds = useMemo(() => [...new Set(ghosts.map((g) => g.kind))], [ghosts]);
  const shown = filter === "all" ? ghosts : ghosts.filter((g) => g.kind === filter);

  return (
    <div className="space-y-3 p-4">
      <div className="text-sm text-slate-300">
        Hidden or risky structure found in your dependency graph. Click a finding to highlight it on the map.
      </div>
      <div className="flex flex-wrap gap-1.5">
        {["all", ...kinds].map((k) => (
          <button
            key={k}
            onClick={() => setFilter(k)}
            className={`rounded-full border px-2 py-0.5 text-[11px] ${filter === k ? "border-violet-400 bg-violet-500/20 text-violet-200" : "border-ink-600 text-slate-400 hover:text-slate-200"}`}
          >
            {k === "all" ? `All (${ghosts.length})` : `${GHOST_LABEL[k] ?? k} (${ghosts.filter((g) => g.kind === k).length})`}
          </button>
        ))}
      </div>
      {shown.length === 0 && <div className="text-sm text-slate-500">No findings.</div>}
      <ul className="space-y-2">
        {shown.map((g, i) => {
          const isFocused = focused === g || (focused && focused.title === g.title && focused.kind === g.kind);
          return (
            <li key={`${g.kind}-${g.title}-${i}`}>
              <button
                onClick={() => onFocus(isFocused ? null : g)}
                className={`card w-full text-left transition hover:border-violet-400/60 ${isFocused ? "!border-violet-400 bg-violet-500/10" : ""}`}
              >
                <div className="mb-1 flex items-center gap-2">
                  <span className={`chip ${SEVERITY_BADGE[g.severity]}`}>{g.severity}</span>
                  <span className="text-[10px] uppercase tracking-wide text-slate-500">{GHOST_LABEL[g.kind] ?? g.kind}</span>
                </div>
                <div className="text-sm font-medium text-slate-100">{g.title}</div>
                <div className="mt-0.5 text-xs text-slate-400">{g.detail}</div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
