"use client";

import { CheckCircle } from "@phosphor-icons/react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Contact, LegalPage } from "@/components/legal";

type Status = { code: string; status: string; deleted_at?: string; note?: string };

/** Meta sends people here with ?code= after the data deletion callback; it also tells anyone how to ask. */
function RequestStatus() {
  const code = useSearchParams().get("code");
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!code) return;
    fetch(`/api/public/meta/data-deletion/${encodeURIComponent(code)}`)
      .then(async (r) => (r.ok ? setStatus(await r.json()) : setError("No deletion request has this code.")))
      .catch(() => setError("Could not check right now. Try again in a minute."));
  }, [code]);
  if (!code) return null;
  return (
    <div className="rounded-[var(--radius-md)] bg-surface p-4 ring-1 ring-line">
      <p className="font-receipt text-[13px] text-muted">Request {code}</p>
      {status ? (
        <p className="mt-1 flex items-center gap-2 font-semibold text-ink">
          <CheckCircle size={18} weight="fill" className="text-pen" aria-hidden />
          {status.note ?? `Deleted${status.deleted_at ? ` on ${new Date(status.deleted_at).toLocaleString()}` : ""}.`}
        </p>
      ) : (
        <p className="mt-1 text-ink">{error ?? "Checking…"}</p>
      )}
    </div>
  );
}

export default function DataDeletionPage() {
  return (
    <LegalPage title="Delete your data" updated="24 October 2026">
      <Suspense>
        <RequestStatus />
      </Suspense>

      <h2>If you connected your business&apos;s Instagram</h2>
      <ul>
        <li>In Counterpart: Channels, Instagram, Disconnect. Or in Instagram: Settings, Apps and websites, remove Counterpart.</li>
        <li>Either way we delete the access token, the posts we stored and the comments read through that account at once. Meta shows you a confirmation code; this page shows its status.</li>
        <li>To delete your whole Counterpart account and business, write to <Contact />.</li>
      </ul>

      <h2>If you are a customer</h2>
      <ul>
        <li>WhatsApp: send STOP to the business&apos;s number and we stop messaging you.</li>
        <li>To delete your comments, codes or reviews kept by a business, write to <Contact /> with your Instagram username or phone number. We delete them within 30 days and confirm.</li>
      </ul>
    </LegalPage>
  );
}
