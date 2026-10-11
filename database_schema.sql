create table public.share_links (
  link_id text not null,
  owner text not null,
  repo text not null,
  encrypted_token text not null,
  user_id text not null,
  created_at timestamp with time zone not null default now(),
  expires_at timestamp with time zone not null,
  access_count integer null default 0,
  last_accessed_at timestamp with time zone null,
  last_ip text null,
  constraint share_links_pkey primary key (link_id)
) TABLESPACE pg_default;

create index IF not exists idx_share_links_user_id on public.share_links using btree (user_id) TABLESPACE pg_default;

create index IF not exists idx_share_links_expires_at on public.share_links using btree (expires_at) TABLESPACE pg_default;