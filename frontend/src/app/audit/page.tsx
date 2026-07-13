"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Loader2, Play } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AuditReport } from "@/components/audit-report";
import { type AuditReport as Report, getAuditSample } from "@/lib/api";

export default function AuditPage() {
  const [r, setR] = useState<Report | null | undefined>(undefined);
  const [err, setErr] = useState("");

  useEffect(() => {
    getAuditSample().then(setR).catch((e) => setErr(String(e?.message || e)));
  }, []);

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <div className="flex items-center justify-between">
        <Link href="/" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> Certo
        </Link>
        <div className="flex items-center gap-2">
          {r?.sample && <Badge variant="outline" className="text-[hsl(var(--warning))]">Sample Audit</Badge>}
          <Link href="/new"><Button size="sm" className="shine"><Play className="size-3.5" /> Audit your own agent</Button></Link>
        </div>
      </div>

      {err && <div className="py-24 text-center text-sm text-[hsl(var(--danger))]">Failed to load audit: {err}</div>}
      {!err && r === undefined && (
        <div className="flex items-center justify-center gap-2 py-24 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Loading sample audit…
        </div>
      )}
      {r && <AuditReport report={r} />}
    </div>
  );
}
