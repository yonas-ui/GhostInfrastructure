import type {
  Alert, BlastRadius, Ghost, GraphDTO, Incident, IncidentDetail, Project, RootCause,
  ServiceDetail, Simulation, Summary, User,
} from "./types";

const TOKEN_KEY = "ghost_token";
export const getToken = () => localStorage.getItem(TOKEN_KEY) ?? "";
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function req<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const token = getToken();
  const res = await fetch(`/api${path}`, {
    method,
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && token) window.dispatchEvent(new Event("ghost:unauthorized"));
    const detail = data?.detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : res.statusText;
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

interface TokenResponse { access_token: string; user: User }

export const api = {
  login: (email: string, password: string) => req<TokenResponse>("/auth/login", "POST", { email, password }),
  register: (email: string, name: string, password: string) => req<TokenResponse>("/auth/register", "POST", { email, name, password }),
  me: () => req<User>("/auth/me"),

  projects: () => req<Project[]>("/projects"),
  createProject: (name: string, description = "") => req<Project>("/projects", "POST", { name, description }),
  summary: (pid: number) => req<Summary>(`/projects/${pid}/summary`),
  graph: (pid: number) => req<GraphDTO>(`/projects/${pid}/graph`),
  ghosts: (pid: number) => req<Ghost[]>(`/projects/${pid}/ghosts`),
  rootCause: (pid: number) => req<{ unhealthy_count: number; candidates: RootCause[] }>(`/projects/${pid}/root-cause`),
  impact: (pid: number, sid: number) => req<BlastRadius>(`/projects/${pid}/impact/${sid}`),

  service: (sid: number) => req<ServiceDetail>(`/services/${sid}`),
  createService: (pid: number, body: Record<string, unknown>) => req(`/projects/${pid}/services`, "POST", body),
  deleteService: (sid: number) => req<void>(`/services/${sid}`, "DELETE"),
  reportHealth: (sid: number, status: "healthy" | "degraded" | "down") =>
    req(`/services/${sid}/health`, "POST", { status, error: status === "healthy" ? null : "Marked manually from the UI" }),
  checkNow: (sid: number) => req(`/services/${sid}/check`, "POST"),

  createDependency: (pid: number, body: Record<string, unknown>) => req(`/projects/${pid}/dependencies`, "POST", body),
  updateDependency: (id: number, body: Record<string, unknown>) => req(`/dependencies/${id}`, "PATCH", body),
  deleteDependency: (id: number) => req<void>(`/dependencies/${id}`, "DELETE"),

  simulate: (pid: number, ids: number[]) => req<Simulation>(`/projects/${pid}/simulations`, "POST", { failed_service_ids: ids }),
  simulations: (pid: number) => req<Simulation[]>(`/projects/${pid}/simulations`),

  incidents: (pid: number) => req<Incident[]>(`/projects/${pid}/incidents`),
  incident: (id: number) => req<IncidentDetail>(`/incidents/${id}`),
  updateIncident: (id: number, body: Record<string, unknown>) => req(`/incidents/${id}`, "PATCH", body),
  addIncidentNote: (id: number, message: string) => req(`/incidents/${id}/events`, "POST", { message }),

  alerts: (pid: number) => req<Alert[]>(`/projects/${pid}/alerts`),
  ackAlert: (id: number) => req(`/alerts/${id}/ack`, "POST"),
  ackAll: (pid: number) => req(`/projects/${pid}/alerts/ack-all`, "POST"),

  discoverCompose: (pid: number, content: string) =>
    req<{ new_services: string[]; new_dependencies: string[] }>(`/projects/${pid}/discover/compose`, "POST", { content }),
  discoverObservations: (pid: number, observations: { source: string; target: string }[]) =>
    req<{ observations: number; new_dependencies: string[] }>(`/projects/${pid}/discover/observations`, "POST", { observations }),
};
