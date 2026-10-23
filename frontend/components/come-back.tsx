import { ArrowUUpLeft } from "@phosphor-icons/react";

const TITLE: Record<string, string> = { en: "Come back by {date}", kn: "{date} ರೊಳಗೆ ಮತ್ತೆ ಬನ್ನಿ", hi: "{date} तक फिर आइए" };
const SUB: Record<string, string> = {
  en: "Your code for one more visit, same offer. It works from tomorrow.",
  kn: "ಇನ್ನೊಂದು ಭೇಟಿಗೆ ನಿಮ್ಮ ಕೋಡ್, ಇದೇ ಆಫರ್. ನಾಳೆಯಿಂದ ಬಳಸಬಹುದು.",
  hi: "अगली बार के लिए आपका कोड, यही ऑफ़र। कल से इस्तेमाल करें।",
};
const OPEN: Record<string, string> = { en: "Open my code", kn: "ನನ್ನ ಕೋಡ್ ತೆರೆಯಿರಿ", hi: "मेरा कोड खोलें" };

/** After a code is used: the customer's come-back code for one more visit, when the owner turned them on. */
export function ComeBackCard({ code, until, language }: { code: string; until: string; language: string }) {
  const t = (m: Record<string, string>) => m[language] ?? m.en;
  const date = new Date(until + "T00:00:00").toLocaleDateString(language === "en" ? "en-IN" : `${language}-IN`, { day: "numeric", month: "long" });
  return (
    <section className="mt-5 rounded-[var(--radius-lg)] bg-marker p-5 ring-1 ring-ink" lang={language} aria-label={t(TITLE).replace("{date}", date)}>
      <p className="flex items-center gap-2 text-[19px] font-bold">
        <ArrowUUpLeft size={20} weight="bold" aria-hidden /> {t(TITLE).replace("{date}", date)}
      </p>
      <p className="mt-1 text-[15px] text-ink-2">{t(SUB)}</p>
      <p className="mt-3 font-receipt text-[30px] tracking-[0.16em]">{code}</p>
      <a href={`/c/${code}`} className="press mt-3 inline-flex h-10 items-center rounded-[var(--radius-sm)] bg-ink px-4 text-[14px] font-semibold text-white">
        {t(OPEN)}
      </a>
    </section>
  );
}
