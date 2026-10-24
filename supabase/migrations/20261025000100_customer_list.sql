-- The business's own customer list, for reaching people who already came in without the WhatsApp API: the owner
-- pastes customers who agreed to hear from them, or a customer adds their number on their code page. Each one gets a
-- personal code per campaign, sent from the owner's own WhatsApp (a wa.me link the owner taps), and after the code is
-- redeemed, a link to review the visit.
create table customers (
  id            uuid primary key default gen_random_uuid(),
  business_id   uuid not null references businesses on delete cascade,
  phone         text not null,  -- digits with country code, as wa.me takes it
  name          text,
  language      text check (language in ('en', 'kn', 'hi')),
  source        text not null check (source in ('owner_import', 'code_page')),
  consent       text not null,  -- how they agreed, in words, kept with the number
  opted_out_at  timestamptz,
  created_at    timestamptz not null default now(),
  unique (business_id, phone)
);
alter table customers enable row level security;

alter table claims
  add column customer_id uuid references customers on delete set null,
  add column invited_at  timestamptz;  -- the owner sent the code (opened the prepared WhatsApp message)
create index claims_customer on claims (customer_id) where customer_id is not null;

alter table claims drop constraint if exists claims_via_check;
alter table claims add constraint claims_via_check check (via in ('web', 'whatsapp', 'instagram', 'invite'));
