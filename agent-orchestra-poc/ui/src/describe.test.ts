import { describe, expect, it } from "vitest";
import { describeEvent, systemName } from "./Replay";
import type { StreamEvent } from "./types";

const name = (id: string) => ({ qualite: "Quality", coordinateur: "Coordinator", "comite-1": "Committee member 1" } as Record<string, string>)[id] ?? systemName(id);
const ev = (type: StreamEvent["type"], actor: string | null, target: string | null = null, payload: StreamEvent["payload"] = {}): StreamEvent => ({ t: "2026-01-01T00:00:00Z", type, actor, target, payload });

describe("event descriptions (English)", () => {
  it("system actor names", () => {
    expect(systemName("approval:abc")).toBe("Committee decision");
    expect(systemName("routine:rt-qualite-incidents")).toBe("Routine qualite-incidents");
    expect(systemName("gateway")).toBe("Gateway");
    expect(systemName("inbox:comite")).toBe("comite");
  });
  it("a message", () => {
    expect(describeEvent(ev("sent", "qualite", "coordinateur", { performative: "request", kind: "impact-request" }), name)).toBe("Quality → Coordinator: Request · impact-request");
  });
  it("status, vote, wait, error, tool", () => {
    expect(describeEvent(ev("status", "qualite", null, { text: "I'm qualifying" }), name)).toBe("Quality: “I'm qualifying”");
    expect(describeEvent(ev("vote", "comite-1", "ap", { decision: "approve" }), name)).toBe("Committee member 1 approves");
    expect(describeEvent(ev("vote", "comite-1", "ap", { decision: "reject" }), name)).toBe("Committee member 1 rejects");
    expect(describeEvent(ev("waiting", "coordinateur", "launch_modification"), name)).toBe("Coordinator waits (Modification launch)");
    expect(describeEvent(ev("error", "qualite", "chain", { reason: "audit" }), name)).toContain("error (audit)");
    expect(describeEvent(ev("tool.start", "qualite", "query_kg"), name)).toBe("Quality uses KG query");
    expect(describeEvent(ev("tool.end", "qualite", "query_kg"), name)).toBe("Quality finished with KG query");
    expect(describeEvent(ev("learned", "qualite", "mem:qualite", { statement: "The relay failed" }), name)).toBe("Quality learns: The relay failed");
  });
});
