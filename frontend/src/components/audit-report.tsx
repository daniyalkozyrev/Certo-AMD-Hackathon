"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle, CheckCircle2, Cpu, Loader2, ScanSearch, ShieldCheck,
  Sparkles, TrendingUp, Wrench, XCircle,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TrustRing } from "@/components/trust-ring";
import { type AuditFinding, type AuditFix, type AuditReport as Report, generateFix } from "@/lib/api";

const SEV_COLOR: Record<string, string> = {
  critical: "hsl(var(--danger))",
  high: "hsl(var(--danger))",
  medium: "hsl(var(--warning))",
  low: "hsl(var(--warning))",
  none: "hsl(var(--success))",
};

export function AuditReport({
  report: r,
  agentSystemPrompt,
}: {
  report: Report;
  agentSystemPrompt?: string | null;
}) {
  const findings = useMemo(() => {
    const order = (f: AuditFinding) =>
      (f.passed === false ? 0 : f.scored ? 1 : 2) * 100 -
      ({ critical: 5, high: 4, medium: 3, low: 2, none: 1 }[f.severity] ?? 0);
    return [...r.findings].sort((a, b) => order(a) - order(b));
  }, [r]);

  const modelJudges = r.judges.filter((j) => j.kind === "model");
  const fixer = r.judges.find((j) => j.kind === "remediation");

  return (
    <div className="space-y-6">
      {/* Header + score */}
      <Card className="overflow-hidden">
        <div className="grid gap-px bg-border md:grid-cols-[1fr_auto]">
          <div className="bg-card p-6">
            <div className="flex flex-wrap items-center gap-2">
              <ScanSearch className="size-5 text-accent" />
              <h1 className="text-2xl font-semibold tracking-tight">
                Agent Trust Audit — {r.meta?.agent_name || "Agent"}
              </h1>
            </div>
            {r.disclaimer && <p className="mt-2 text-sm text-muted-foreground">{r.disclaimer}</p>}
            <div className="mt-4 flex flex-wrap gap-4 text-sm">
              <Stat label="Probes" value={`${r.summary.scored}/${r.probe_count} scored`} />
              <Stat label="Failed" value={String(r.summary.failed)} tone="danger" />
              <Stat label="Passed" value={String(r.summary.passed)} tone="success" />
              <Stat label="Confidence" value={`${Math.round(r.confidence * 100)}%`} />
              <Stat label="Evidence" value={`${Math.round(r.evidence_coverage * 100)}%`} />
            </div>
          </div>
          <div className="flex flex-col items-center justify-center gap-2 bg-card p-6">
            <TrustRing score={r.trust_score} size={150} />
            <div className="inline-flex items-center gap-1 text-xs text-muted-foreground">
              <TrendingUp className="size-3.5" /> Potential after fixes:{" "}
              <span className="font-semibold text-[hsl(var(--success))]">{r.potential_score}</span>
            </div>
          </div>
        </div>
      </Card>

      {/* AIs: judges + fixer, all on Fireworks/AMD */}
      <Card className="p-5">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium">
          <Cpu className="size-4 text-accent" /> Evaluation &amp; remediation models
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          {r.judges.map((j) => (
            <div key={j.id} className="flex items-center justify-between rounded-lg border p-3 text-sm">
              <div>
                <div className="font-medium">{j.model.split("/").pop()}</div>
                <div className="text-xs text-muted-foreground">{j.provider} · {j.kind}</div>
              </div>
              <Badge variant="outline" className={j.enabled ? "text-[hsl(var(--success))]" : "text-muted-foreground"}>
                {j.enabled ? "active" : "off"}
              </Badge>
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          {modelJudges.length >= 2
            ? `${modelJudges.length} model judges on Fireworks AI (AMD) form an ensemble — consensus + disagreement`
            : "Model judge on Fireworks AI (AMD)"}
          {fixer?.enabled && ` · ${fixer.model.split("/").pop()} generates the fixes`}.
        </p>
      </Card>

      {/* Category breakdown */}
      <Card className="p-5">
        <div className="mb-3 text-sm font-medium">Trust Score by category</div>
        <div className="space-y-2">
          {Object.entries(r.categories).map(([cat, v]) => (
            <div key={cat} className="flex items-center gap-3 text-sm">
              <div className="w-28 shrink-0 text-muted-foreground">{cat}</div>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-secondary">
                <div className="h-full rounded-full"
                  style={{ width: `${v.score ?? 0}%`,
                    background: (v.score ?? 0) >= 70 ? "hsl(var(--success))" : (v.score ?? 0) >= 40 ? "hsl(var(--warning))" : "hsl(var(--danger))" }} />
              </div>
              <div className="w-20 shrink-0 text-right tabular-nums">
                {v.score == null ? "—" : v.score} <span className="text-xs text-muted-foreground">({v.passed}/{v.probes})</span>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Top fixes */}
      {r.top_fixes?.length > 0 && (
        <Card className="p-5">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium"><TrendingUp className="size-4 text-accent" /> Highest-leverage fixes</div>
          <div className="space-y-1.5">
            {r.top_fixes.map((f, i) => (
              <div key={i} className="flex items-center justify-between text-sm">
                <span>{f.name}</span>
                <span className="text-xs text-muted-foreground">+{f.gain} pts · <span style={{ color: SEV_COLOR[f.severity] }}>{f.severity}</span></span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Findings */}
      <div className="space-y-3">
        <div className="text-sm font-medium">Findings ({findings.length})</div>
        {findings.map((f) => (
          <FindingCard key={f.probe_id} f={f} agentSystemPrompt={agentSystemPrompt} />
        ))}
      </div>

      {/* Compliance */}
      {r.standards && (
        <Card className="p-5">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium"><ShieldCheck className="size-4 text-accent" /> Standards mapping (evidence, not certification)</div>
          <div className="grid gap-2 sm:grid-cols-2">
            {Object.entries(r.standards).map(([code, fw]) => (
              <div key={code} className="rounded-lg border p-3 text-sm">
                <div className="font-medium">{fw.name}</div>
                <div className="text-xs text-muted-foreground">{fw.passed}/{fw.probed} probed controls passed · {fw.total} total</div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "danger" | "success" }) {
  const c = tone === "danger" ? "text-[hsl(var(--danger))]" : tone === "success" ? "text-[hsl(var(--success))]" : "";
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`font-semibold tabular-nums ${c}`}>{value}</div>
    </div>
  );
}

function FindingCard({ f, agentSystemPrompt }: { f: AuditFinding; agentSystemPrompt?: string | null }) {
  const failed = f.passed === false;
  const [open, setOpen] = useState(failed && (f.severity === "critical" || f.severity === "high"));
  const [fix, setFix] = useState<AuditFix | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const Icon = failed ? XCircle : f.passed === true ? CheckCircle2 : AlertTriangle;
  const iconColor = failed ? "hsl(var(--danger))" : f.passed === true ? "hsl(var(--success))" : "hsl(var(--warning))";

  async function onGenerateFix() {
    setLoading(true);
    setErr("");
    try {
      const res = await generateFix({
        name: f.name, category: f.category, severity: f.severity, reason: f.reason,
        evidence: f.evidence, expected_behavior: f.expected_behavior, recommended_fix: f.recommended_fix,
        agent_response: f.agent_response, probe_id: f.probe_id, agent_system_prompt: agentSystemPrompt,
      });
      setFix(res);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="overflow-hidden">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-3 p-4 text-left">
        <Icon className="size-4 shrink-0" style={{ color: iconColor }} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{f.name}</div>
          <div className="text-xs text-muted-foreground">{f.category} · {f.score_category}</div>
        </div>
        <Badge variant="outline" className="shrink-0 text-[10px] uppercase" style={{ color: SEV_COLOR[f.severity] }}>{f.severity}</Badge>
        <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">{f.score ?? "—"}</span>
      </button>
      {open && (
        <div className="space-y-3 border-t p-4 text-xs">
          <p className="text-muted-foreground">{f.reason}</p>
          {f.business_impact && (
            <p className="text-[hsl(var(--danger))]"><span className="font-semibold uppercase tracking-wider">Business impact: </span>{f.business_impact}</p>
          )}
          {f.evidence && (
            <div>
              <div className="mb-1 font-semibold uppercase tracking-wider text-muted-foreground">Evidence (from the agent)</div>
              <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border bg-secondary/40 p-2 font-mono">{f.evidence}</pre>
            </div>
          )}
          {f.recommended_fix && (
            <div>
              <div className="mb-1 font-semibold uppercase tracking-wider text-muted-foreground">Recommended fix (judge)</div>
              <p className="rounded-md border-l-2 border-accent/50 pl-2 text-foreground">{f.recommended_fix}</p>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {f.judge_model && <Badge variant="outline" className="text-[10px]">judge: {f.judge_model}</Badge>}
            {f.disagreement && <Badge variant="outline" className="text-[10px]">disagreement: {f.disagreement}</Badge>}
            {f.standards.map((s) => <Badge key={s} variant="outline" className="text-[10px] text-muted-foreground">{s}</Badge>)}
          </div>
          {f.votes && f.votes.length > 1 && (
            <div className="text-[11px] text-muted-foreground">
              votes: {f.votes.map((v) => `${v.model}=${v.passed ? "pass" : "fail"}(${v.score})`).join(" · ")}
            </div>
          )}

          {/* Generate fix — the third Fireworks AI */}
          {failed && (
            <div className="pt-1">
              {!fix && (
                <button onClick={onGenerateFix} disabled={loading}
                  className="inline-flex items-center gap-1.5 rounded-md border border-accent/50 bg-accent/10 px-3 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-accent/20 disabled:opacity-60">
                  {loading ? <Loader2 className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}
                  {loading ? "Generating fix…" : "Generate fix"}
                </button>
              )}
              {err && <p className="mt-1 text-[hsl(var(--danger))]">Fix failed: {err}</p>}
              {fix && (
                <div className="mt-1 space-y-2 rounded-lg border border-accent/40 bg-accent/5 p-3">
                  <div className="flex items-center gap-1.5 font-semibold uppercase tracking-wider text-accent">
                    <Wrench className="size-3.5" /> Generated fix
                    {fix.effort && <Badge variant="outline" className="ml-1 text-[10px]">{fix.effort} effort</Badge>}
                  </div>
                  {fix.diagnosis && <p><span className="text-muted-foreground">Root cause: </span>{fix.diagnosis}</p>}
                  <p className="text-foreground">{fix.fix}</p>
                  {fix.system_prompt_patch && (
                    <div>
                      <div className="mb-1 text-muted-foreground">Add to the agent&apos;s system prompt:</div>
                      <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border bg-secondary/40 p-2 font-mono">{fix.system_prompt_patch}</pre>
                    </div>
                  )}
                  {fix.prevention && <p className="text-muted-foreground">Prevention: {fix.prevention}</p>}
                  <p className="text-[10px] text-muted-foreground">
                    {fix.generated ? `Generated by ${fix.model?.split("/").pop()} on ${fix.provider}` : "Fallback (fixer model unavailable)"} · a suggestion, review before applying.
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
