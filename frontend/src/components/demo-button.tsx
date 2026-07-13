"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/components/auth-provider";
import { demoLogin } from "@/lib/api";

/** One-click guest entry: logs in as the shared "demo" account and lands in the
 * dashboard — so a reviewer never has to sign up. */
export function DemoButton({
  children,
  ...props
}: React.ComponentProps<typeof Button>) {
  const router = useRouter();
  const { login } = useAuth();
  const [busy, setBusy] = useState(false);

  async function enterDemo() {
    setBusy(true);
    try {
      const r = await demoLogin();
      await login(r.access_token, r.user);
      router.push("/dashboard");
    } catch {
      router.push("/login");
    }
  }

  return (
    <Button {...props} onClick={enterDemo} disabled={busy}>
      {busy ? (
        <>
          <Loader2 className="animate-spin" /> Entering demo…
        </>
      ) : (
        children
      )}
    </Button>
  );
}
