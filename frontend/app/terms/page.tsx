import { Contact, LegalPage } from "@/components/legal";

export const metadata = { title: "Terms · Counterpart" };

export default function TermsPage() {
  return (
    <LegalPage title="Terms of use" updated="24 October 2026">
      <p>These terms cover businesses that use Counterpart and customers who claim an offer through it.</p>

      <h2>For businesses</h2>
      <ul>
        <li>You are responsible for your offers. Counterpart publishes only what you lock and approve, and the counter honours only the locked offer.</li>
        <li>Connect only Instagram accounts and WhatsApp numbers you are allowed to use, and follow Meta&apos;s Platform Terms and WhatsApp Business policies.</li>
        <li>AI writes drafts; rules and a second model check them before you approve. Read what goes out under your name.</li>
        <li>Do not use Counterpart for spam, for messages to people who have not contacted you, or for offers you do not mean to honour.</li>
      </ul>

      <h2>For customers</h2>
      <ul>
        <li>A personal code is for one visit, under the conditions shown with the offer (dates, times, items). The business decides at the counter.</li>
        <li>Asking for a code on Instagram or WhatsApp means we reply to you there with it. Send STOP on WhatsApp to stop messages.</li>
      </ul>

      <h2>The service</h2>
      <p>
        Counterpart is provided as it is, while it is being built. We may change or stop features. Questions: <Contact />.
      </p>
    </LegalPage>
  );
}
