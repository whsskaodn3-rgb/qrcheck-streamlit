"""QRCheck Streamlit Community Cloud edition. Run: streamlit run streamlit_app.py."""
from __future__ import annotations

import csv
import hmac
import io
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import qrcode
import streamlit as st
import streamlit.components.v1 as components

from storage import AppError, SQLiteBackend, SupabaseBackend

st.set_page_config(page_title="QRCheck", page_icon="▣", layout="centered")
COMPONENT_DIR = Path(__file__).parent / "components" / "scanner"
scanner_component = components.declare_component("qrcheck_scanner", path=str(COMPONENT_DIR))


def setting(name: str, default=""):
    env = os.environ.get(name)
    if env is not None:
        return env
    try:
        return st.secrets.get(name, default)
    except (FileNotFoundError, KeyError):
        return default


@st.cache_resource(show_spinner=False)
def get_backend(url: str, key: str, db: str):
    return SupabaseBackend(url, key) if url and key else SQLiteBackend(db)


def qr_png(raw: str) -> bytes:
    code = qrcode.QRCode(version=None, box_size=10, border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
    code.add_data(raw)
    code.make(fit=True)
    buffer = io.BytesIO()
    code.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def display_time(dt):
    if not dt:
        return ""
    try:
        return datetime.fromisoformat(str(dt).replace("Z", "+00:00")).astimezone(
            ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(dt)


def csv_data(rows):
    if not rows:
        return b""
    buf = io.StringIO()
    cols = list(dict.fromkeys(k for r in rows for k in r.keys()))
    writer = csv.DictWriter(buf, fieldnames=cols)
    writer.writeheader()
    writer.writerows(rows)
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def current_backend():
    url = setting("SUPABASE_URL")
    key = setting("SUPABASE_SECRET_KEY") or setting("SUPABASE_SERVICE_ROLE_KEY")
    if bool(url) != bool(key):
        st.error("Supabase 설정이 불완전합니다. URL과 SECRET_KEY를 모두 입력하세요.")
        st.stop()
    return get_backend(url, key, setting("LOCAL_DB", "data/qrcheck.sqlite3")), bool(url)


def scan_view(store, persistent):
    st.title("QRCheck")
    if "scan" not in st.session_state:
        st.session_state.scan = None
    if "scan_round" not in st.session_state:
        st.session_state.scan_round = 0
    if "last_notice" not in st.session_state:
        st.session_state.last_notice = ""
    if not persistent:
        st.caption("테스트 모드 저장소: SQLite (Streamlit Cloud 재시작 시 기록이 삭제될 수 있음)")

    if st.session_state.scan is None:
        st.write("QR코드를 스캔하세요.")
        result = scanner_component(key=f"scanner-{st.session_state.scan_round}", default=None)
        if isinstance(result, dict) and result.get("raw"):
            try:
                source = result.get("source", "browser-camera")
                record = store.register_scan(result["raw"], source)
                st.session_state.scan = record
                st.session_state.last_notice = ""
                st.rerun()
            except AppError as e:
                st.error(str(e))
                if st.button("다시 스캔", type="primary"):
                    st.session_state.scan_round += 1
                    st.rerun()
        if setting("ENABLE_TEST_MODE", "0") == "1":
            with st.expander("개발자용 수동 테스트"):
                raw = st.text_input("QR 문자열", placeholder="SCAN:...")
                if st.button("테스트 스캔", disabled=not raw):
                    try:
                        st.session_state.scan = store.register_scan(raw, "manual-test")
                        st.rerun()
                    except AppError as e:
                        st.error(str(e))
    else:
        st.subheader("인증번호 입력하세요")
        with st.form("pin_form", clear_on_submit=True):
            pin = st.text_input("인증번호", placeholder="인증번호", max_chars=32, type="password")
            submitted = st.form_submit_button("확인", type="primary", use_container_width=True)
        if submitted:
            try:
                data = store.verify_scan(st.session_state.scan["scan_id"], pin)
                if data["status"] == "VERIFIED":
                    st.session_state.last_notice = "VERIFIED"
                elif data["status"] == "LOCKED":
                    st.session_state.last_notice = "LOCKED"
                else:
                    st.session_state.last_notice = f"PIN_FAILED ({data['attempts']}/5)"
            except AppError as e:
                st.error(str(e))
        if st.session_state.last_notice == "VERIFIED":
            st.success("인증 성공")
        elif st.session_state.last_notice == "LOCKED":
            st.error("인증 실패: 5회 오류로 잠겼습니다.")
        elif st.session_state.last_notice.startswith("PIN_FAILED"):
            st.error("인증 실패 — 번호를 다시 확인해주세요.")

        if st.button("다음 QR 스캔", use_container_width=True):
            st.session_state.scan = None
            st.session_state.last_notice = ""
            st.session_state.scan_round += 1
            st.rerun()


def admin_view(store, persistent):
    st.title("QRCheck 관리자")
    admin_key = str(setting("ADMIN_KEY"))
    if not admin_key:
        st.error("ADMIN_KEY가 설정되지 않았습니다. Streamlit Secrets에 ADMIN_KEY를 등록하세요.")
        return
    if not st.session_state.get("admin_authenticated", False):
        with st.form("admin_auth"):
            user_key = st.text_input("관리자 키", type="password")
            submitted = st.form_submit_button("로그인", type="primary")
        if submitted:
            if hmac.compare_digest(user_key, admin_key):
                st.session_state.admin_authenticated = True
                st.rerun()
            st.error("관리자 키가 일치하지 않습니다.")
        return
    if st.button("로그아웃"):
        st.session_state.admin_authenticated = False
        st.rerun()
    if not persistent:
        st.warning("현재 SQLite 테스트 저장소입니다. Streamlit Cloud에서는 기록이 영구 보존되지 않습니다. Supabase를 연결하세요.")

    tab1, tab2, tab3 = st.tabs(["QR 발급 / 설정", "스캔 기록", "이벤트 로그"])
    with tab1:
        with st.form("create_qr"):
            label = st.text_input("QR 이름", placeholder="예: 행사장 입구 A")
            pin = st.text_input("인증번호", placeholder="숫자 1~32자리 (예: 1111)", type="password")
            submit = st.form_submit_button("고정 QR 생성", type="primary")
        if submit:
            try:
                created = store.add_qr(label, pin)
                st.session_state.selected_qr = created["id"]
                st.success("고정 QR을 생성했습니다.")
            except AppError as e:
                st.error(str(e))
        try:
            qrs = store.list_qrs()
        except AppError as e:
            st.error(str(e))
            return
        if not qrs:
            st.info("아직 QR이 없습니다. 위에서 발급하세요.")
        else:
            labels = {q["id"]: f"{q['label']} — {q['id'][:9]}{' (비활성)' if not q['enabled'] else ''}" for q in qrs}
            ids = list(labels)
            selected = st.session_state.get("selected_qr")
            ix = ids.index(selected) if selected in ids else 0
            qr_id = st.selectbox("발급된 QR 선택", ids, index=ix, format_func=lambda k: labels[k])
            st.session_state.selected_qr = qr_id
            raw = f"SCAN:{qr_id}"
            img = qr_png(raw)
            st.image(img, width=240)
            st.code(raw)
            st.download_button("QR 이미지 PNG 다운로드", img, file_name=f"QRCheck-{qr_id}.png", mime="image/png")
            with st.form("update_pin"):
                change_pin = st.text_input("인증번호 변경 (QR 이미지는 유지)", type="password", placeholder="새 숫자 인증번호")
                save = st.form_submit_button("인증번호 변경 저장")
            if save:
                try:
                    store.update_qr(qr_id, pin=change_pin)
                    st.success("변경 완료. 기존 QR 이미지 그대로 사용합니다.")
                except AppError as e:
                    st.error(str(e))
            q = next(x for x in qrs if x["id"] == qr_id)
            if st.button("비활성화" if q["enabled"] else "다시 활성화"):
                try:
                    store.update_qr(qr_id, enabled=not bool(q["enabled"]))
                    st.rerun()
                except AppError as e:
                    st.error(str(e))
            st.caption(f"현재 인증번호 길이: {q['pin_length']}자리 / 생성일: {display_time(q['created_at'])}")
    with tab2:
        try:
            scans = store.list_scans()
            for item in scans:
                item["created_at"] = display_time(item.get("created_at"))
                item["updated_at"] = display_time(item.get("updated_at"))
            st.caption(f"최근 {len(scans)}건")
            if scans:
                st.dataframe(scans, use_container_width=True, hide_index=True)
                st.download_button("스캔 기록 CSV", csv_data(scans), file_name="qrcheck-scans.csv", mime="text/csv")
            else:
                st.info("스캔 기록이 없습니다.")
        except AppError as e:
            st.error(str(e))
    with tab3:
        try:
            events = store.list_events()
            for item in events:
                item["created_at"] = display_time(item.get("created_at"))
            st.caption("SCANNED / VERIFIED / PIN_FAILED / LOCKED 및 실제 입력값")
            if events:
                st.dataframe(events, use_container_width=True, hide_index=True)
                st.download_button("이벤트 CSV", csv_data(events), file_name="qrcheck-events.csv", mime="text/csv")
            else:
                st.info("이벤트가 없습니다.")
        except AppError as e:
            st.error(str(e))
    if st.button("기록 새로고침"):
        st.rerun()


def main():
    try:
        store, persistent = current_backend()
    except AppError as e:
        st.error(str(e))
        return
    mode = st.query_params.get("mode", "scan")
    if mode == "admin":
        admin_view(store, persistent)
    else:
        scan_view(store, persistent)
    st.divider()
    if mode == "admin":
        st.page_link("streamlit_app.py", label="스캐너로 이동", icon="📷")
    else:
        st.markdown("[관리자 페이지](?mode=admin)")


if __name__ == "__main__":
    main()
