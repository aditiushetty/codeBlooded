-- Every model call made for a business, so a campaign's AI cost can be shown next to what it brought in
-- (the router also keeps the last few hundred in memory for the AI team page). Tokens are measured; cost is
-- estimated from them at the list price in settings, since free tiers report no price.
create table model_calls (
  id             bigint generated always as identity primary key,
  business_id    uuid not null references businesses on delete cascade,
  campaign_id    uuid references campaigns on delete set null,
  agent          text,
  task           text,
  role           text not null,
  provider       text not null,
  model          text not null,
  ok             boolean not null,
  replayed       boolean not null default false,
  input_tokens   int not null default 0,
  output_tokens  int not null default 0,
  latency_ms     int not null default 0,
  created_at     timestamptz not null default now()
);
create index model_calls_campaign on model_calls (campaign_id);
create index model_calls_business on model_calls (business_id, created_at desc);
alter table model_calls enable row level security;
