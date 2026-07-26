"use client";

import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type Viewport,
} from "@xyflow/react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import "@xyflow/react/dist/style.css";

import { api, type Envelope } from "@/lib/api";
import { DataState } from "@/components/data-state";

type GraphPayload = {
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
};

export function GraphCanvas({
  minimumConfidence,
  predicate,
  onData,
  onEdge,
  initialPositions,
  onLayoutChange,
}: {
  minimumConfidence: number;
  predicate: string;
  onData(value: GraphPayload): void;
  onEdge(value: Record<string, unknown>): void;
  initialPositions?: Record<string, { x: number; y: number }>;
  onLayoutChange(value: { positions: Record<string, { x: number; y: number }>; viewport: Viewport }): void;
}) {
  const params = new URLSearchParams({
    limit: "500",
    minimum_confidence: String(minimumConfidence),
  });
  if (predicate) params.set("predicate", predicate);
  const query = useQuery({
    queryKey: ["relation-graph", minimumConfidence, predicate],
    queryFn: async () => {
      const result = await api<Envelope<GraphPayload>>(`/graph?${params}`);
      onData(result.data);
      return result;
    },
  });
  const rawEdges = useMemo(() => query.data?.data.edges ?? [], [query.data]);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  useEffect(() => {
    setNodes((query.data?.data.nodes ?? []).map((item, index) => ({
      id: String(item.id),
      position: initialPositions?.[String(item.id)] ?? {
        x: (index % 5) * 230,
        y: Math.floor(index / 5) * 150,
      },
      data: { label: String(item.label) },
    })));
    setEdges(rawEdges.map(item => ({
      id: String(item.id),
      source: String(item.source),
      target: String(item.target),
      label: `${String(item.predicate)} · ${Math.round(Number(item.confidence) * 100)}%`,
      animated: String(item.relation_status) === "COMPUTED",
    })));
  }, [initialPositions, query.data, rawEdges, setEdges, setNodes]);
  return (
    <DataState loading={query.isLoading} error={query.error} empty={nodes.length === 0}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
        onMoveEnd={(_event, viewport) => {
          onLayoutChange({
            positions: Object.fromEntries(nodes.map(node => [node.id, node.position])),
            viewport,
          });
        }}
        onEdgeClick={(_event, edge) => {
          const raw = rawEdges.find(item => String(item.id) === edge.id);
          if (raw) onEdge(raw);
        }}
      >
        <Background color="#20342f"/>
        <Controls/>
        <MiniMap/>
      </ReactFlow>
    </DataState>
  );
}
