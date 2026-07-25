"use client";

import { Background, Controls, MiniMap, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

const nodes: Node[] = [
  {id: "session", position: {x: 280, y: 180}, data: {label: "Session S-81A2"}, style: {background: "#132521", color: "#ddf7e8", border: "1px solid #62e6a0"}},
  {id: "freq", position: {x: 40, y: 40}, data: {label: "4.625 MHz"}},
  {id: "receiver", position: {x: 40, y: 300}, data: {label: "Receiver NL-01"}},
  {id: "call", position: {x: 540, y: 40}, data: {label: "KILO 72"}},
  {id: "number", position: {x: 540, y: 300}, data: {label: "281 · 46 · 992"}},
  {id: "event", position: {x: 780, y: 180}, data: {label: "External event"}},
];
const edges: Edge[] = [
  {id: "e1", source: "session", target: "freq", label: "OBSERVED_ON"},
  {id: "e2", source: "session", target: "receiver", label: "RECEIVED_BY"},
  {id: "e3", source: "session", target: "call", label: "USES_CALLSIGN"},
  {id: "e4", source: "session", target: "number", label: "CONTAINS_NUMBER_GROUP"},
  {id: "e5", source: "session", target: "event", label: "+4h 18m · COMPUTED", animated: true},
];

export function GraphCanvas() {
  return <ReactFlow nodes={nodes} edges={edges} fitView><Background color="#20342f"/><Controls/><MiniMap/></ReactFlow>;
}

