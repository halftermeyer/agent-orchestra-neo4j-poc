import { describe, expect, it } from "vitest";
import { describeEvent, systemName } from "./Replay";
import type { StreamEvent } from "./types";

const name = (id: string) => ({ qualite: "Qualité", coordinateur: "Coordinateur", "comite-1": "Membre du comité 1" } as Record<string, string>)[id] ?? systemName(id);
const ev = (type: StreamEvent["type"], actor: string | null, target: string | null = null, payload: StreamEvent["payload"] = {}): StreamEvent => ({ t: "2026-01-01T00:00:00Z", type, actor, target, payload });

describe("description des événements (français)", () => {
  it("noms des acteurs système", () => {
    expect(systemName("approval:abc")).toBe("Décision du comité");
    expect(systemName("routine:rt-qualite-incidents")).toBe("Routine qualite-incidents");
    expect(systemName("gateway")).toBe("Passerelle");
    expect(systemName("inbox:comite")).toBe("comite");
  });
  it("un message", () => {
    expect(describeEvent(ev("sent", "qualite", "coordinateur", { performative: "request", kind: "impact-request" }), name)).toBe("Qualité → Coordinateur : Demande · impact-request");
  });
  it("statut, vote, attente, erreur", () => {
    expect(describeEvent(ev("status", "qualite", null, { text: "Je qualifie" }), name)).toBe("Qualité : « Je qualifie »");
    expect(describeEvent(ev("vote", "comite-1", "ap", { decision: "approve" }), name)).toBe("Membre du comité 1 approuve");
    expect(describeEvent(ev("vote", "comite-1", "ap", { decision: "reject" }), name)).toBe("Membre du comité 1 refuse");
    expect(describeEvent(ev("waiting", "coordinateur", "launch_modification"), name)).toBe("Coordinateur attend (Lancement de la modification)");
    expect(describeEvent(ev("error", "qualite", "chain", { reason: "audit" }), name)).toContain("erreur (audit)");
  });
});
