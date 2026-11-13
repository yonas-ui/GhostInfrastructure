export type Status = "healthy" | "degraded" | "down" | "unknown";
export type EffStatus = Status | "impacted";
export type Severity = "low" | "medium" | "high" | "critical";

export interface User { id: number; email: string; name: string }
export interface Project { id: number; name: string; description: string }

export interface GNodeDTO {
  id: number;
  name: string;
  type: string;
  status: Status;
  effective_status: EffStatus;
  criticality: number;
  owner: string;
  ghost: boolean;
  ghost_reasons: string[];
  dependents: number;
  dependencies: number;
  transitive_dependents: number;
  transitive_dependencies: number;
}
export interface GEdgeDTO {
  id: number;
  source: number;
  target: number;
  kind: string;
  documented: boolean;
  discovered_by: string;
  observed_count: number;
}
export interface GraphDTO { nodes: GNodeDTO[]; edges: GEdgeDTO[] }

export interface Summary {
  services: number;
  dependencies: number;
  undocumented_dependencies: number;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
  ghost_findings: number;
  ghost_by_severity: Record<string, number>;
  open_incidents: number;
  unacknowledged_alerts: number;
}

export interface Ghost {
  kind: string;
  severity: Severity;
  title: string;
  detail: string;
  service_ids: number[];
  edge_ids: number[];
}

export interface Affected {
  id: number;
  name: string;
  type: string;
  criticality: number;
  depth: number;
  via: number | null;
  path: number[];
  path_names: string[];
}
export interface BlastRadius {
  failed: { id: number; name: string; type: string }[];
  affected: Affected[];
  affected_count: number;
  total_services: number;
  percent_affected: number;
  impact_score: number;
  severity: Severity;
  by_type: Record<string, number>;
  user_facing: string[];
  max_depth: number;
  dependencies?: { id: number; name: string; type: string }[];
}

export interface RootCause {
  service_id: number;
  name: string;
  type: string;
  status: string;
  explains: number[];
  explains_count: number;
  confidence: number;
  in_cycle: boolean;
}

export interface ServiceCore {
  id: number;
  project_id: number;
  name: string;
  type: string;
  description: string;
  owner: string;
  environment: string;
  criticality: number;
  status: Status;
  health_url: string | null;
  last_checked_at: string | null;
}
export interface Relation {
  id: number;
  service_id: number;
  service_name: string;
  kind: string;
  documented: boolean;
  observed_count: number;
}
export interface HealthPoint { id: number; status: string; latency_ms: number | null; error: string | null; checked_at: string }
export interface Deployment { id: number; version: string; deployed_by: string; status: string; deployed_at: string }
export interface ServiceDetail {
  service: ServiceCore;
  depends_on: Relation[];
  depended_on_by: Relation[];
  health: HealthPoint[];
  deployments: Deployment[];
}

export interface Simulation { id: number; name: string; failed_service_ids: number[]; result: BlastRadius; created_at: string }

export interface Incident {
  id: number;
  title: string;
  severity: Severity;
  status: string;
  root_cause_service_id: number | null;
  auto_detected: boolean;
  summary: string;
  started_at: string;
  resolved_at: string | null;
}
export interface IncidentEvent { id: number; event_type: string; message: string; service_id: number | null; created_at: string }
export interface IncidentDetail extends Incident { events: IncidentEvent[] }

export interface Alert {
  id: number;
  service_id: number | null;
  incident_id: number | null;
  kind: string;
  level: "info" | "warning" | "critical";
  message: string;
  acknowledged: boolean;
  created_at: string;
}

export interface LiveEvent { project_id: number; type: string; data: Record<string, unknown>; ts: string }
