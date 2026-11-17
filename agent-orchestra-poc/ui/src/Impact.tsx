import type { ChangeImpact, ImpactPart } from "./types";

// Synthetic demo data: costs are shown in euros, weights in kilograms
const eur = (x: number) => x.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " €";
const kg = (x: number) => x.toLocaleString("en-GB", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " kg";
const signed = (x: number, f: (x: number) => string) => (x > 0 ? "+" : x < 0 ? "−" : "") + f(Math.abs(x));

function Part({ p }: { p: ImpactPart }) {
  return <span><code>{p.id}</code> {p.name}{p.cost != null && <span className="muted"> · {eur(p.cost)} · {kg(p.weight ?? 0)}</span>}</span>;
}

/** Impact of a replacement, as computed by Neo4j on the configurable BOM (baseline vs what-if). */
export function Impact({ impact, onOpen }: { impact: ChangeImpact; onOpen?: () => void }) {
  if (!impact.available) return <div className="impact muted" data-testid="impact">BOM impact unavailable: {impact.reason}</div>;
  const unsat = impact.unsatisfied ?? [];
  const pos = impact.positions ?? [];
  const units = pos.reduce((a, p) => a + p.perProduct, 0);
  return (
    <div className="impact" data-testid="impact">
      <div className="impact-head">BOM impact <span className="muted">computed in Neo4j on the configurable BOM</span></div>
      {impact.parts && <div className="impact-parts"><Part p={impact.parts.old} /> <span className="arrow">→</span> <Part p={impact.parts.new} /></div>}
      {pos.length > 0 && (
        <div className="muted">Mounted at {pos.length} position(s), {units} per product: {pos.map((p) => `${p.parentName ?? p.parent} ×${p.qty}`).join(", ")}</div>
      )}
      <div className="impact-figures">
        <span>Product cost <b data-testid="impact-cost">{signed(impact.costDelta ?? 0, eur)}</b>
          <span className="muted"> ({eur(impact.baseline?.cost ?? 0)} → {eur(impact.whatIf?.cost ?? 0)})</span></span>
        <span>Weight <b data-testid="impact-weight">{signed(impact.weightDelta ?? 0, kg)}</b>
          <span className="muted"> ({kg(impact.baseline?.weight ?? 0)} → {kg(impact.whatIf?.weight ?? 0)})</span></span>
      </div>
      {unsat.length > 0 && (
        <div className="error" data-testid="impact-unsatisfied">
          {unsat.length} unsatisfied requirement(s), the BOM would be incomplete: {unsat.map((u) => `${u.source} → ${u.group}`).join(", ")}
        </div>
      )}
      {onOpen && <button className="ghost small" onClick={onOpen} data-testid="open-cbom">View in the configurable BOM</button>}
    </div>
  );
}
