-- The Brief agent, Analyst and Customer listener, and the features small businesses get elsewhere:
-- come-back codes, bill matching, WhatsApp template approval and Google Business Profile offer posts.

-- The Customer listener drafts replies; the owner reads, edits and sends them (nothing is sent by the agent).
alter table customer_interactions
  add column reply_draft      text,
  add column reply_drafted_at timestamptz;

-- Come-back codes: when a customer's code is used, they get one more code for the same offer, valid from the next
-- day for `return_days` days. The owner turns it on per campaign (null = off).
alter table campaigns add column return_days int check (return_days between 1 and 60);
alter table claims
  add column kind        text not null default 'first' check (kind in ('first', 'return')),
  add column parent_code text references claims on delete cascade,
  add column valid_from  date,
  add column valid_until date;
create unique index claims_one_return on claims (parent_code) where parent_code is not null;

-- WhatsApp message templates (needed to message a customer outside the free 24-hour window). Drafted from a live
-- post, checked against Meta's rules here, then submitted; Meta's verdict comes back by webhook or a refresh.
create table wa_templates (
  id            uuid primary key default gen_random_uuid(),
  business_id   uuid not null references businesses on delete cascade,
  asset_id      uuid references assets on delete set null,
  name          text not null check (name ~ '^[a-z0-9_]+$' and length(name) <= 512),
  language      text not null,
  category      text not null default 'MARKETING' check (category in ('MARKETING', 'UTILITY')),
  body          text not null,
  footer        text,
  example       jsonb not null default '[]',
  status        text not null default 'draft'
                check (status in ('draft', 'pending', 'approved', 'rejected', 'paused', 'disabled')),
  reason        text,
  meta_id       text,
  submitted_at  timestamptz,
  updated_at    timestamptz not null default now(),
  created_at    timestamptz not null default now(),
  unique (business_id, name, language)
);
create index wa_templates_asset on wa_templates (asset_id);
alter table wa_templates enable row level security;

-- Google Business Profile: the business's own Google listing, connected with Google sign-in (OAuth).
alter table channel_accounts drop constraint channel_accounts_channel_check;
alter table channel_accounts add constraint channel_accounts_channel_check
  check (channel in ('whatsapp', 'instagram', 'google_business'));

-- Offer posts published on the Google listing.
create table google_posts (
  name          text primary key,  -- accounts/{a}/locations/{l}/localPosts/{p}
  business_id   uuid not null references businesses on delete cascade,
  asset_id      uuid references assets on delete set null,
  search_url    text,
  state         text,
  created_at    timestamptz not null default now()
);
alter table google_posts enable row level security;
