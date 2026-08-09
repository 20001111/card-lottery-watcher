-- Run this once in Supabase SQL Editor.
-- Management records are private; the public Website remains a separate read-only view.

create table if not exists public.admin_allowlist (
  email text primary key,
  created_at timestamptz not null default now()
);

create table if not exists public.lottery_listings (
  application_url text primary key,
  listing jsonb not null,
  status text not null default 'pending'
    check (status in ('pending', 'published', 'suppressed')),
  -- Officer corrections survive later AI collection updates.
  overrides jsonb not null default '{}'::jsonb,
  note text not null default '',
  submitted_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Safe to run again after the initial table was created.
alter table public.lottery_listings
  add column if not exists overrides jsonb not null default '{}'::jsonb;

create or replace function public.is_lottery_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.admin_allowlist
    where lower(email) = lower(coalesce(auth.jwt() ->> 'email', ''))
  );
$$;

alter table public.admin_allowlist enable row level security;
alter table public.lottery_listings enable row level security;

create policy "admins can view their own allowlist record"
on public.admin_allowlist for select
using (lower(email) = lower(coalesce(auth.jwt() ->> 'email', '')));

create policy "admins can read lottery listings"
on public.lottery_listings for select
using (public.is_lottery_admin());

create policy "admins can add lottery listings"
on public.lottery_listings for insert
with check (public.is_lottery_admin());

create policy "admins can edit lottery listings"
on public.lottery_listings for update
using (public.is_lottery_admin())
with check (public.is_lottery_admin());

-- Initial administrator. Add other officer email addresses with the same form later.
insert into public.admin_allowlist (email)
values ('takato2000111136@gmail.com')
on conflict (email) do nothing;
