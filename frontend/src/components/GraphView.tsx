import dagre from "@dagrejs/dagre";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { useMemo } from "react";
import type { GraphDTO } from "../types";
import { STATUS_DOT, TYPE_LABEL } from "../ui";

export interface Overlay {
  selected: number | null;
  failed: Set<number>;
  affected: Map<number, number>; // id -> depth
  focusNodes: Set<number>;
  focusEdges: Set<number>;
}

type NodeState = "none" | "selected" | "failed" | "affected" | "focus" | "dim";
type GNodeData = {
  label: string;
  type: string;
  status: keyof typeof STATUS_DOT;
  criticality: number;
  ghost: boolean;
  state: NodeState;
  depth?: number;
};
type GNode = Node<GNodeData, "service">;

const W = 196;
const H = 58;

const RING: Record<NodeState, string> = {
  none: "border-ink-600",
  selected: "border-sky-400 ring-2 ring-sky-400/60",
  failed: "border-red-500 ring-2 ring-red-500/70 bg-red-950/60",
  affected: "border-orange-400 ring-2 ring-orange-400/50",
  focus: "border-violet-400 ring-2 ring-violet-400/60",
  dim: "border-ink-700 opacity-25",
};

function ServiceNode({ data }: NodeProps<GNode>) {
  return (
    <div className={`w-[196px] rounded-lg border bg-ink-800 px-2.5 py-1.5 shadow-lg transition ${RING[data.state]}`}>
      <Handle type="target" position={Position.Top} className="!h-1.5 !w-1.5 !border-0 !bg-slate-500" />
      <div className="flex items-center gap-2">
        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${STATUS_DOT[data.status]} ${data.status === "down" ? "animate-pulse" : ""}`} />
        <span className="truncate text-[13px] font-semibold text-slate-100">{data.label}</span>
      </div>
      <div className="mt-1 flex items-center gap-1.5 text-[10px] text-slate-400">
        <span className="rounded bg-ink-600 px-1 py-px font-semibold tracking-wide">{TYPE_LABEL[data.type] ?? data.type}</span>
        <span>C{data.criticality}</span>
        {data.ghost && <span className="rounded bg-violet-500/20 px-1 py-px font-semibold text-violet-300">GHOST</span>}
        {data.depth !== undefined && data.state === "affected" && (
          <span className="ml-auto rounded bg-orange-500/20 px-1 py-px font-semibold text-orange-300">hop {data.depth}</span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!h-1.5 !w-1.5 !border-0 !bg-slate-500" />
    </div>
  );
}

const nodeTypes = { service: ServiceNode };

const GAP_X = 26;
const GAP_Y = 22;
const RANK_GAP = 110;
const MAX_PER_ROW = 9;

/**
 * Top-to-bottom layered layout: dependents above, what they depend on below.
 * dagre decides the layers and the left-to-right order (crossing minimisation); wide layers
 * are then wrapped into several rows so a 30-node layer doesn't become a 6,000px-wide strip.
 */
function layout(graph: GraphDTO): Map<number, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "TB", nodesep: GAP_X, ranksep: RANK_GAP, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));
  graph.nodes.forEach((n) => g.setNode(String(n.id), { width: W, height: H }));
  graph.edges.forEach((e) => g.setEdge(String(e.source), String(e.target)));
  dagre.layout(g);

  const layers = new Map<number, { id: number; x: number }[]>();
  graph.nodes.forEach((n) => {
    const p = g.node(String(n.id));
    const rank = Math.round(p.y);
    layers.set(rank, [...(layers.get(rank) ?? []), { id: n.id, x: p.x }]);
  });

  const out = new Map<number, { x: number; y: number }>();
  let y = 0;
  for (const rank of [...layers.keys()].sort((a, b) => a - b)) {
    const row = layers.get(rank)!.sort((a, b) => a.x - b.x);
    const rows = Math.ceil(row.length / MAX_PER_ROW);
    const perRow = Math.ceil(row.length / rows); // balance rows instead of leaving a stub row
    for (let r = 0; r < rows; r++) {
      const chunk = row.slice(r * perRow, (r + 1) * perRow);
      const width = chunk.length * W + (chunk.length - 1) * GAP_X;
      chunk.forEach((item, i) => out.set(item.id, { x: -width / 2 + i * (W + GAP_X), y: y + r * (H + GAP_Y) }));
    }
    y += rows * (H + GAP_Y) - GAP_Y + RANK_GAP;
  }
  return out;
}

interface Props {
  graph: GraphDTO;
  overlay: Overlay;
  onNodeClick: (id: number) => void;
  onEdgeClick: (id: number) => void;
  onPaneClick: () => void;
}

export default function GraphView({ graph, overlay, onNodeClick, onEdgeClick, onPaneClick }: Props) {
  // Re-layout only when the structure changes, not on every highlight/status change.
  const structureKey = useMemo(
    () => graph.nodes.map((n) => n.id).sort().join(",") + "|" + graph.edges.map((e) => `${e.source}>${e.target}`).sort().join(","),
    [graph],
  );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const positions = useMemo(() => layout(graph), [structureKey]);

  const active = overlay.failed.size > 0 || overlay.affected.size > 0 || overlay.focusNodes.size > 0;

  const nodes: GNode[] = useMemo(
    () =>
      graph.nodes.map((n) => {
        let state: NodeState = "none";
        if (overlay.failed.has(n.id)) state = "failed";
        else if (overlay.affected.has(n.id)) state = "affected";
        else if (overlay.focusNodes.has(n.id)) state = "focus";
        else if (overlay.selected === n.id) state = "selected";
        else if (active) state = "dim";
        if (overlay.selected === n.id && state !== "failed") state = "selected";
        return {
          id: String(n.id),
          type: "service" as const,
          position: positions.get(n.id) ?? { x: 0, y: 0 },
          initialWidth: W,
          initialHeight: H,
          data: {
            label: n.name,
            type: n.type,
            status: n.effective_status,
            criticality: n.criticality,
            ghost: n.ghost,
            state,
            depth: overlay.affected.get(n.id),
          },
        };
      }),
    [graph, positions, overlay, active],
  );

  const edges: Edge[] = useMemo(() => {
    const hot = (id: number) => overlay.failed.has(id) || overlay.affected.has(id) || overlay.selected === id;
    return graph.edges.map((e) => {
      const onBlastPath = overlay.affected.has(e.source) && hot(e.target);
      const focused = overlay.focusEdges.has(e.id);
      const ghost = !e.documented;
      const color = onBlastPath ? "#fb923c" : focused ? "#a78bfa" : ghost ? "#f59e0b" : "#475569";
      const dim = active && !onBlastPath && !focused;
      return {
        id: String(e.id),
        source: String(e.source),
        target: String(e.target),
        animated: onBlastPath || focused,
        style: {
          stroke: color,
          strokeWidth: onBlastPath || focused ? 2.5 : ghost ? 1.8 : 1.2,
          strokeDasharray: ghost ? "6 4" : undefined,
          opacity: dim ? 0.12 : 1,
        },
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
      };
    });
  }, [graph, overlay, active]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, n) => onNodeClick(Number(n.id))}
      onEdgeClick={(_, e) => onEdgeClick(Number(e.id))}
      onPaneClick={onPaneClick}
      nodesConnectable={false}
      nodesDraggable={false}
      fitView
      fitViewOptions={{ padding: 0.15 }}
      minZoom={0.1}
      maxZoom={1.8}
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#1b2335" />
      <Controls showInteractive={false} />
      <MiniMap
        pannable
        zoomable
        nodeColor={(n) => {
          const d = n.data as GNodeData;
          return d.state === "failed" ? "#ef4444" : d.state === "affected" ? "#fb923c" : d.status === "down" ? "#ef4444" : d.status === "impacted" ? "#fb923c" : "#334155";
        }}
        maskColor="rgba(7,9,15,0.7)"
      />
    </ReactFlow>
  );
}
