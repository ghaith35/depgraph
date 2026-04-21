import * as d3 from "d3";
import { nodeRadius } from "./colors";
import { Edge, Node } from "./types";

export function createSimulation(
  width: number,
  height: number,
): d3.Simulation<Node, Edge> {
  return d3
    .forceSimulation<Node>()
    .force(
      "link",
      d3
        .forceLink<Node, Edge>()
        .id((d) => d.id)
        .distance(60)
        .strength(0.7),
    )
    .force("charge", d3.forceManyBody<Node>().strength(-300))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force(
      "collide",
      d3
        .forceCollide<Node>()
        .radius((d) => nodeRadius(d) + 4)
        .strength(0.9),
    )
    .force("x", d3.forceX(width / 2).strength(0.05))
    .force("y", d3.forceY(height / 2).strength(0.05))
    .alphaDecay(0.04);
}

export function updateChargeStrength(
  sim: d3.Simulation<Node, Edge>,
  nodeCount: number,
): void {
  (sim.force("charge") as d3.ForceManyBody<Node>).strength(
    -300 * (1 + Math.log10(Math.max(1, nodeCount) / 50)),
  );
}
