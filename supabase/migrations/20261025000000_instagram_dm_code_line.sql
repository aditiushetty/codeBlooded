-- How a published Instagram post tells people to comment CODE: in its caption (posts published from 2026-10-24
-- 22:50), or in a comment from the business added later (the API cannot edit a caption). Null = it does not say.
alter table instagram_media add column if not exists code_line text check (code_line in ('caption', 'comment'));
update instagram_media set code_line = 'caption'
 where code_line is null and caption like '%Comment CODE and we''ll send you your own one-time code.%';

