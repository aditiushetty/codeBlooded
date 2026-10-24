-- Which Instagram post a comment was left on, so each post can show its own comments next to its likes and reach.
alter table customer_interactions add column if not exists media_id text;
create index if not exists customer_interactions_media on customer_interactions (media_id) where media_id is not null;
