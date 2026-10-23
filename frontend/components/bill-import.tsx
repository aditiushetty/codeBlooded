"use client";

import { Check, FileCsv, Receipt } from "@phosphor-icons/react";
import { useState } from "react";
import { api } from "@/lib/api";
import type { BillImport as Result } from "@/lib/types";
import { Button } from "./ui";

const rupees = (n: number) => `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

/** The owner's payment statement (UPI app, card machine or bank, as CSV) matched to redeemed codes, so each post's
 *  sales are real numbers without staff typing every bill. Shows the matches first; saves only on "Save". */
export function BillImport({ slug, onSaved }: { slug: string; onSaved: () => void }) {
  const [text, setText] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [res, setRes] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(csv: string, apply: boolean) {
    setBusy(true);
    setError(null);
    try {
      const out = await api<Result>(`/businesses/${slug}/bills/import`, { method: "POST", json: { text: csv, apply } });
      setRes(out);
      if (apply) onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-[var(--radius-lg)] bg-surface p-5 ring-1 ring-ink md:p-6">
      <p className="flex items-center gap-2 text-[17px] font-bold">
        <Receipt size={19} weight="bold" className="text-pen" aria-hidden /> Match your sales
      </p>
      <p className="mt-1 max-w-[66ch] text-[14px] text-ink-2">
        Download your payment statement as CSV (from your UPI business app, card machine or bank) and add it here. Each payment is matched to the code redeemed at the same time, or to a code written in the payment note. Payments that could belong to more than one code are left out rather than guessed.
      </p>
      <label className="press mt-4 inline-flex cursor-pointer items-center gap-2 rounded-[var(--radius-sm)] bg-sunken px-3 py-2 text-[14px] font-semibold hover:bg-line">
        <FileCsv size={16} aria-hidden /> {name || "Choose a CSV file"}
        <input
          type="file"
          accept=".csv,text/csv,text/plain"
          className="sr-only"
          onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            const csv = await f.text();
            setName(f.name);
            setText(csv);
            setRes(null);
            run(csv, false);
          }}
        />
      </label>
      {busy && <p className="mt-3 text-[14px] text-muted">Reading the statement…</p>}
      {error && <p className="mt-3 text-[14px] text-kumkum">{error}</p>}
      {res && (
        <div className="mt-4">
          <p className="text-[15px]">
            <span className="font-semibold">{res.totals.matched}</span> of {res.totals.payments} payments match a redeemed code:{" "}
            <span className="font-semibold">{rupees(res.totals.matched_sales)}</span> of {rupees(res.totals.sales)} in the statement
            {res.totals.share != null && <> ({Math.round(res.totals.share * 100)}%)</>}.
          </p>
          {res.problems.map((p) => (
            <p key={p} className="mt-1 text-[13px] text-turmeric">{p}</p>
          ))}
          {res.unmatched_codes.length > 0 && (
            <p className="mt-1 text-[13px] text-muted">{res.unmatched_codes.length} redeemed code(s) in this period had no clear payment.</p>
          )}
          {res.matches.length > 0 && (
            <ul className="mt-3 divide-y divide-line border-y border-line text-[14px]">
              {res.matches.slice(0, 12).map((m) => (
                <li key={m.code} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 py-2">
                  <span className="font-mono text-[13px] font-semibold">{m.code}</span>
                  <span className="font-semibold">{rupees(m.amount)}</span>
                  <span className="text-muted">{new Date(m.at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</span>
                  <span className="text-pen">{m.how === "code" ? "code in the note" : `paid ${m.gap_min} min from the redemption`}</span>
                  {m.campaign && <span className="ml-auto truncate text-muted">{m.campaign}</span>}
                </li>
              ))}
            </ul>
          )}
          {res.applied ? (
            <p className="mt-3 flex items-center gap-1.5 text-[14px] font-semibold text-pen">
              <Check size={14} weight="bold" aria-hidden /> Saved. Each post's sales now include these bills.
            </p>
          ) : (
            res.matches.length > 0 && text && (
              <Button className="mt-3" variant="primary" disabled={busy} onClick={() => run(text, true)}>
                Save {res.matches.length} matched bill{res.matches.length === 1 ? "" : "s"}
              </Button>
            )
          )}
        </div>
      )}
    </div>
  );
}
