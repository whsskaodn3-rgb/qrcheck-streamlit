-- Run once in Supabase > SQL Editor. Server uses the SERVICE ROLE key only.
create table if not exists public.qrcheck_qrs (
 id text primary key,
 label text not null,
 pin text not null check (pin ~ '^[0-9]{1,32}$'),
 enabled boolean not null default true,
 created_at timestamptz not null default now()
);
create table if not exists public.qrcheck_scans (
 id text primary key,
 qr_id text not null references public.qrcheck_qrs(id),
 source text not null,
 status text not null default 'SCANNED',
 attempts integer not null default 0,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);
create table if not exists public.qrcheck_events (
 id bigint generated always as identity primary key,
 scan_id text not null references public.qrcheck_scans(id),
 qr_id text not null references public.qrcheck_qrs(id),
 event text not null,
 entered_pin text,
 created_at timestamptz not null default now()
);
create index if not exists qrcheck_scans_created_idx on public.qrcheck_scans(created_at desc);
create index if not exists qrcheck_events_created_idx on public.qrcheck_events(id desc);

-- Never expose tables to anonymous clients.
alter table public.qrcheck_qrs enable row level security;
alter table public.qrcheck_scans enable row level security;
alter table public.qrcheck_events enable row level security;
revoke all on table public.qrcheck_qrs from anon, authenticated;
revoke all on table public.qrcheck_scans from anon, authenticated;
revoke all on table public.qrcheck_events from anon, authenticated;
grant select, insert, update, delete on public.qrcheck_qrs, public.qrcheck_scans, public.qrcheck_events to service_role;
grant usage, select on sequence public.qrcheck_events_id_seq to service_role;

create or replace function public.qrcheck_register_scan(p_scan_id text, p_raw text, p_source text)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare
 v_qr_id text;
 v_qr public.qrcheck_qrs%rowtype;
 v_time timestamptz := now();
begin
 if p_raw is null or p_raw !~ '^SCAN:[A-Za-z0-9_-]{8,128}$' then
  raise exception 'QRCheck QR 형식이 아닙니다.';
 end if;
 if p_source not in ('metamask-rpc', 'browser-camera', 'manual-test', 'qr-url') then
  raise exception '허용되지 않은 스캔 출처입니다.';
 end if;
 v_qr_id := substring(p_raw from 6);
 select * into v_qr from public.qrcheck_qrs where id = v_qr_id and enabled = true;
 if not found then
  raise exception '등록되지 않았거나 비활성화된 QR코드입니다.';
 end if;
 insert into public.qrcheck_scans(id,qr_id,source,status,attempts,created_at,updated_at)
 values (p_scan_id,v_qr_id,p_source,'SCANNED',0,v_time,v_time);
 insert into public.qrcheck_events(scan_id,qr_id,event,created_at)
 values (p_scan_id,v_qr_id,'SCANNED',v_time);
 return jsonb_build_object('scan_id',p_scan_id,'qr_id',v_qr_id,'status','SCANNED', 'created_at', v_time);
end $$;

create or replace function public.qrcheck_verify_scan(p_scan_id text, p_pin text)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare
 v_scan public.qrcheck_scans%rowtype;
 v_expected text;
 v_status text;
 v_attempts integer;
begin
 if p_pin is null or p_pin !~ '^[0-9]{1,32}$' then
  raise exception '인증번호는 숫자 1~32자리만 가능합니다.';
 end if;
 select * into v_scan from public.qrcheck_scans where id = p_scan_id for update;
 if not found then
  raise exception '유효하지 않은 스캔 기록입니다.';
 end if;
 if v_scan.status in ('VERIFIED','LOCKED') then
  raise exception '이미 완료되었거나 잠긴 스캔입니다.';
 end if;
 select pin into v_expected from public.qrcheck_qrs where id = v_scan.qr_id;
 v_attempts := v_scan.attempts + 1;
 if p_pin = v_expected then
  v_status := 'VERIFIED';
 elsif v_attempts >= 5 then
  v_status := 'LOCKED';
 else
  v_status := 'PIN_FAILED';
 end if;
 update public.qrcheck_scans set attempts=v_attempts,status=v_status,updated_at=now()
 where id=p_scan_id;
 insert into public.qrcheck_events(scan_id,qr_id,event,entered_pin)
 values (p_scan_id,v_scan.qr_id,v_status,p_pin);
 return jsonb_build_object('scan_id',p_scan_id,'status',v_status,'attempts',v_attempts,'success',v_status='VERIFIED');
end $$;

revoke all on function public.qrcheck_register_scan(text,text,text) from public, anon, authenticated;
revoke all on function public.qrcheck_verify_scan(text,text) from public, anon, authenticated;
grant execute on function public.qrcheck_register_scan(text,text,text) to service_role;
grant execute on function public.qrcheck_verify_scan(text,text) to service_role;
