-- Run in Supabase SQL Editor BEFORE deploying new Streamlit code.
-- Upgrades the existing registration function to accept URL-open events.
-- Preserves all existing QR IDs, PIN settings and previous events.
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
 select * into v_qr from public.qrcheck_qrs where id=v_qr_id and enabled=true;
 if not found then
  raise exception '등록되지 않았거나 비활성화된 QR코드입니다.';
 end if;
 insert into public.qrcheck_scans(id,qr_id,source,status,attempts,created_at,updated_at)
 values(p_scan_id,v_qr_id,p_source,'SCANNED',0,v_time,v_time);
 insert into public.qrcheck_events(scan_id,qr_id,event,created_at)
 values(p_scan_id,v_qr_id,'SCANNED',v_time);
 return jsonb_build_object('scan_id',p_scan_id,'qr_id',v_qr_id,'status','SCANNED','created_at',v_time);
end $$;
revoke all on function public.qrcheck_register_scan(text,text,text) from public, anon, authenticated;
grant execute on function public.qrcheck_register_scan(text,text,text) to service_role;
