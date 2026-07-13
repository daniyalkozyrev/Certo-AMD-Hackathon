"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Loader2, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AuditReport } from "@/components/audit-report";
import { ApiError, getAudit, type AuditDetail } from "@/lib/api";

export default function AuditResultPage() {
  const params = useParams<{ id: string }>();
  const [a, setA] = useState<AuditDetail | null | undefined>(undefined);
  const [error, setError] = useState("");

  // Poll until the audit reaches a terminal state — no hard timeout, so a long
  // run still updates the UI the moment it finishes.
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function tick() {
      try {
        const data = await getAudit(params.id);
        if (!active) return;
        setA(data);
        if (data.status === "pending" || data.status === "running") {
          timer = setTimeout(tick, 2000);
        }
      } catch (e) {
        if (!active) return;
        if (e instanceof ApiError && e.status === 404) setA(null);
        else setError(e instanceof ApiError ? e.message : "Failed to load audit.");
      }
    }
    tick();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [params.id]);

  if (error)
    return <div className="py-20 text-center text-sm text-[hsl(var(--danger))]">{error}</div>;
  if (a === undefined)
    return (
      <div className="flex items-center justify-center gap-2 py-20 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> Loading…
      </div>
    );
  if (a === null)
    return (
      <div className="mx-auto max-w-md py-20 text-center">
        <p className="font-medium">Audit not found</p>
        <Link href="/new" className="mt-4 inline-block"><Button>Run a new audit</Button></Link>
      </div>
    );

  if (a.status === "pending" || a.status === "running")
    return (
      <div className="mx-auto max-w-md py-24 text-center">
        <Loader2 className="mx-auto size-6 animate-spin text-accent" />
        <p className="mt-3 font-medium">Audit {a.status}…</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Running 36 probes and grading each with the Fireworks judge ensemble. This refreshes
          automatically (~30–60s).
        </p>
      </div>
    );

  if (a.status === "failed" || !a.report)
    return (
      <div className="mx-auto max-w-md py-20 text-center">
        <p className="font-medium text-[hsl(var(--danger))]">Audit failed</p>
        <p className="mt-1 break-words text-sm text-muted-foreground">{a.error || "Unknown error."}</p>
        <Link href="/new" className="mt-4 inline-block"><Button>Try again</Button></Link>
      </div>
    );

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex items-center justify-between">
        <Link href="/dashboard" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> Back to dashboard
        </Link>
        <Link href="/new"><Button size="sm" variant="outline"><Play className="size-3.5" /> Audit another agent</Button></Link>
      </div>
      <AuditReport report={a.report} />
    </div>
  );
}
