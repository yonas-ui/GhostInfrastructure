import type { EffStatus, Severity } from "./types";

export const STATUS_DOT: Record<EffStatus, string> = {
  healthy: "bg-emerald-400",
  degraded: "bg-amber-400",
  down: "bg-red-500",
  impacted: "bg-orange-400",
  unknown: "bg-slate-500",
};

export const STATUS_TEXT: Record<EffStatus, string> = {
  healthy: "text-emerald-300",
  degraded: "text-amber-300",
  down: "text-red-400",
  impacted: "text-orange-300",
  unknown: "text-slate-400",
};

export const SEVERITY_BADGE: Record<Severity, string> = {
  critical: "bg-red-500/15 text-red-300 border-red-500/40",
  high: "bg-orange-500/15 text-orange-300 border-orange-500/40",
  medium: "bg-amber-500/15 text-amber-200 border-amber-500/40",
  low: "bg-slate-500/15 text-slate-300 border-slate-500/40",
};

export const TYPE_LABEL: Record<string, string> = {
  application: "APP",
  api: "API",
  database: "DB",
  cache: "CACHE",
  queue: "QUEUE",
  storage: "STORE",
  worker: "WORKER",
  external: "3RD PARTY",
  other: "OTHER",
};

export const SERVICE_TYPES = ["application", "api", "database", "cache", "queue", "storage", "worker", "external", "other"];

export const GHOST_LABEL: Record<string, string> = {
  undocumented_dependency: "Undocumented dependency",
  shared_resource: "Shared resource",
  single_point_of_failure: "Single point of failure",
  circular_dependency: "Circular dependency",
  forgotten_worker: "Forgotten worker",
  isolated_service: "Isolated service",
  unowned_service: "No owner",
  third_party_risk: "Third-party risk",
};

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
