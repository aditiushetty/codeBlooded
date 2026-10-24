-- Personal codes asked for in an Instagram comment: the claim records it came through Instagram.
alter table claims drop constraint if exists claims_via_check;
alter table claims add constraint claims_via_check check (via in ('web', 'whatsapp', 'instagram'));
