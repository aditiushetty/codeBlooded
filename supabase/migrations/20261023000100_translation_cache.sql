-- Sarvam translations are paid per character (free plan: 100 credits). The same offer wording is translated and
-- back-translated many times (drafts, checks, re-checks), so each distinct text is paid for once.
create table translation_cache (
  key         text primary key,            -- sha256 of model | source language | target language | text
  model       text not null,
  source_lang text not null,
  target_lang text not null,
  source      text not null,
  translated  text not null,
  created_at  timestamptz not null default now()
);
alter table translation_cache enable row level security;
