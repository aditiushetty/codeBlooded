import { Contact, LegalPage } from "@/components/legal";

export const metadata = { title: "Privacy · Counterpart" };

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy policy" updated="24 October 2026">
      <p>
        Counterpart helps small businesses (cafés, shops, salons) run offers: it writes posts, publishes them on the business&apos;s own Instagram and
        WhatsApp, gives customers personal one-time codes and counts who came to the counter. This page says what we keep, why, and how to have it deleted.
      </p>

      <h2>Business owners</h2>
      <ul>
        <li>Your account: email address and sign-in, handled by Supabase Auth.</li>
        <li>Your business: name, place, menu and prices, languages, brand words, photos you upload or import from your website or Google Maps.</li>
        <li>Connected channels: the Instagram account id and username and the access token you paste, or your WhatsApp Business number id and token. Tokens stay on our server and are never shown in a browser.</li>
        <li>Campaigns, offers, posts, results and a log of what the AI team and you did.</li>
      </ul>

      <h2>Customers of a business</h2>
      <ul>
        <li>Instagram comments on the business&apos;s posts (username, text, time), read so the business can see reviews and answer questions.</li>
        <li>If you comment or send a DM asking for the offer: your Instagram user id or username, used only to send you a personal code and to give you the same code if you ask again.</li>
        <li>If you message the business on WhatsApp: your phone number and messages, used to reply with your code, and STOP or START to opt out or in.</li>
        <li>Personal codes you claim, when they were used at the counter, and an optional bill amount the staff enter.</li>
        <li>A review or star rating you choose to leave after a visit.</li>
        <li>A random id stored in your browser when you open an offer link, so one phone gets one code. No advertising cookies or trackers.</li>
      </ul>

      <h2>Who processes it for us</h2>
      <ul>
        <li>Supabase (database, file storage, sign-in), Vercel and Render (hosting).</li>
        <li>Meta (Instagram and WhatsApp), only for the business&apos;s own connected accounts.</li>
        <li>AI providers that write and check text: Google Gemini, Groq, Cerebras, Agnes, and Sarvam for Kannada and Hindi speech and translation. They receive the text needed for one task, such as a draft post or a batch of comments to sort, not your account.</li>
        <li>Google Maps Places (business photos and details the owner asks for) and Open-Meteo (weather; no personal data).</li>
      </ul>
      <p>We do not sell personal data or use it for advertising.</p>

      <h2>How long we keep it</h2>
      <p>
        For as long as the business uses Counterpart. Disconnecting Instagram, or removing Counterpart from your Instagram account in Settings, Apps and websites,
        deletes the token, the stored posts and the comments read through it.
      </p>

      <h2>Your rights</h2>
      <p>
        You can ask to see, correct or delete your data, under India&apos;s Digital Personal Data Protection Act, 2023. See <a href="/data-deletion" className="text-pen hover:underline">Delete your data</a>,
        or write to <Contact />.
      </p>
    </LegalPage>
  );
}
