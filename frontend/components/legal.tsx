import Link from "next/link";
import type { ReactNode } from "react";

/** Where people write about their data. Set NEXT_PUBLIC_CONTACT_EMAIL before taking the Meta app live. */
export const CONTACT = process.env.NEXT_PUBLIC_CONTACT_EMAIL ?? null;

const PAGES = [
  ["/privacy", "Privacy"],
  ["/terms", "Terms"],
  ["/data-deletion", "Delete your data"],
] as const;

/** The public policy pages Meta asks for (privacy, terms, data deletion), in the counter-book style. */
export function LegalPage({ title, updated, children }: { title: string; updated: string; children: ReactNode }) {
  return (
    <main className="mx-auto min-h-dvh max-w-2xl px-5 py-10">
      <nav className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-ink pb-3 text-[14px]">
        <span className="font-semibold">Counterpart</span>
        <span className="flex-1" />
        {PAGES.map(([href, label]) => (
          <Link key={href} href={href} className="text-pen hover:underline">
            {label}
          </Link>
        ))}
      </nav>
      <h1 className="mt-8 text-[34px] font-semibold leading-tight [font-stretch:90%]">{title}</h1>
      <p className="mt-1 text-[13px] text-muted">Last updated {updated}</p>
      <div className="legal mt-6 space-y-4 text-[15px] leading-relaxed text-ink-2 [&_h2]:mt-8 [&_h2]:text-[19px] [&_h2]:font-semibold [&_h2]:text-ink [&_li]:ml-5 [&_li]:list-disc [&_ul]:space-y-1.5">
        {children}
      </div>
    </main>
  );
}

export function Contact() {
  return CONTACT ? (
    <a href={`mailto:${CONTACT}`} className="text-pen hover:underline">
      {CONTACT}
    </a>
  ) : (
    <span>the business you dealt with, who passes it on to us</span>
  );
}
