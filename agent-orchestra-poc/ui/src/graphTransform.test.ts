import { describe, expect, it } from "vitest";
import { COLORS, flowHeat, kgGraph, rightsGraph, topologyGraph } from "./graphTransform";
import type { Topology } from "./types";

const topo: Topology = {
  agents: [
    { id: "coordinateur", name: "Coordinator", person: false, role: "coordinator", title: null, quarantined: false, kind: "llm", model: "m", inbox: "inbox:coordinateur" },
    { id: "ingenierie", name: "Engineering", person: false, role: "specialist", title: null, quarantined: false, kind: "llm", model: "m", inbox: "inbox:ingenierie" },
    { id: "pont-kg", name: "KG Bridge", person: false, role: "bridge", title: null, quarantined: false, kind: "rule", model: null, inbox: "inbox:pont-kg" },
    { id: "comite-1", name: "Committee 1", person: true, role: null, title: null, quarantined: false, kind: null, model: null, inbox: "inbox:comite" },
    { id: "comite-2", name: "Committee 2", person: true, role: null, title: null, quarantined: false, kind: null, model: null, inbox: "inbox:comite" },
  ],
  inboxes: [{ id: "inbox:coordinateur", topic: false }, { id: "inbox:ingenierie", topic: false }, { id: "inbox:comite", topic: false }, { id: "incidents", topic: true }],
  supervises: [{ from: "coordinateur", to: "ingenierie" }],
  canSendTo: [{ from: "coordinateur", to: "inbox:ingenierie" }, { from: "coordinateur", to: "inbox:comite" }, { from: "comite-1", to: "inbox:coordinateur" }],
  audits: [], canQuery: [{ from: "coordinateur", to: "produit" }], kgs: [{ id: "produit", dbName: "kgproduit" }],
  routines: [{ id: "rt-x", owner: "ingenierie", trigger: "event", cron: null, enabled: true, nextRunAt: null, runAt: null, deliversTo: "inbox:ingenierie", listensTo: "incidents" }],
};
const all = { showSend: true, showAudits: true, showKgAccess: true, showRoutines: true };

describe("topology", () => {
  it("folds agent inboxes onto their owner, keeps topics and the shared inbox", () => {
    const g = topologyGraph(topo, all);
    const ids = g.nodes.map((n) => n.id);
    expect(ids).toEqual(expect.arrayContaining(["coordinateur", "incidents", "inbox:comite", "kg:produit"]));
    expect(ids).not.toContain("inbox:ingenierie");
    const rel = (id: string) => g.rels.find((r) => r.id === id);
    expect(rel("send:coordinateur>ingenierie")).toBeDefined();           // inbox:ingenierie -> ingenierie
    expect(rel("send:coordinateur>inbox:comite")).toBeDefined();         // shared inbox: its own node
    expect(rel("rt:rt-x")).toMatchObject({ from: "incidents", to: "ingenierie" });
    expect(rel("sup:coordinateur>ingenierie")?.caption).toBe("SUPERVISES");
  });
  it("options hide the links", () => {
    const g = topologyGraph(topo, { showSend: false, showAudits: false, showKgAccess: false, showRoutines: false });
    expect(g.rels.map((r) => r.id)).toEqual(["sup:coordinateur>ingenierie"]);
  });
  it("colors: person, rule-based, LLM", () => {
    const g = topologyGraph(topo, all);
    const c = (id: string) => g.nodes.find((n) => n.id === id)?.color;
    expect(c("comite-1")).toBe(COLORS.person);
    expect(c("pont-kg")).toBe(COLORS.rule);
    expect(c("coordinateur")).toBe(COLORS.agent);
  });
  it("no edge to a missing node", () => {
    const g = topologyGraph({ ...topo, inboxes: [] }, all);
    const ids = new Set(g.nodes.map((n) => n.id));
    expect(g.rels.every((r) => ids.has(r.from) && ids.has(r.to))).toBe(true);
  });
});

describe("rights", () => {
  const paths = [
    { memoryId: "mem:ingenierie", ownerId: "ingenierie", kind: "memory" as const, nodes: ["coordinateur", "ingenierie", "mem:ingenierie"], rels: ["SUPERVISES", "HAS_MEMORY"], asOf: "" },
    { memoryId: "mem:qualite", ownerId: "qualite", kind: "message" as const, nodes: ["coordinateur", "inbox:coordinateur", "inbox:coordinateur@2026-01-01", "m1", "mem:qualite"],
      rels: ["HAS_INBOX", "HAS_DAY", "RECEIVED", "CAN_READ"], asOf: "" },
  ];
  const names = new Map([["coordinateur", "Coordinator"], ["ingenierie", "Engineering"], ["qualite", "Quality"]]);
  it("highlights only the chosen path", () => {
    const g = rightsGraph("coordinateur", paths, "mem:qualite", names);
    const hot = g.rels.filter((r) => r.color === COLORS.hot).map((r) => r.caption);
    expect(hot).toEqual(["HAS_INBOX", "HAS_DAY", "RECEIVED", "CAN_READ"]);
    expect(g.rels.find((r) => r.caption === "SUPERVISES")?.color).toBe(COLORS.edge);
    expect(g.nodes.find((n) => n.id === "mem:qualite")?.caption).toBe("Memory · Quality");
    expect(g.nodes.find((n) => n.id === "coordinateur")?.color).toBe(COLORS.hot);
  });
  it("merges common nodes (the root agent appears only once)", () => {
    const g = rightsGraph("coordinateur", paths, null, names);
    expect(g.nodes.filter((n) => n.id === "coordinateur")).toHaveLength(1);
    expect(g.rels.every((r) => r.color === COLORS.edge)).toBe(true);
  });
});

describe("KG and flow", () => {
  it("highlights the searched entity and greys out retired parts", () => {
    const g = kgGraph({ kg: "produit", key: "P1", nodes: [{ id: "P1", name: "a", labels: ["Part"], retired: false }, { id: "P0", name: "b", labels: ["Part"], retired: true }], rels: [{ id: "r", from: "P0", to: "P1", type: "CONTAINS" }] });
    expect(g.nodes.find((n) => n.id === "P1")).toMatchObject({ selected: true, size: 40 });
    expect(g.nodes.find((n) => n.id === "P0")?.color).toBe(COLORS.muted);
  });
  it("edge heat: decays with age and expires", () => {
    const recent = [{ from: "a", to: "b", at: 1000 }, { from: "a", to: "b", at: 5000 }, { from: "c", to: "d", at: 0 }];
    const h = flowHeat(recent, 6000);
    expect(h.get("a>b")).toBeCloseTo(1 - 1000 / 8000);
    expect(h.has("c>d")).toBe(true);
    expect(flowHeat(recent, 20000).size).toBe(0);
  });
});
