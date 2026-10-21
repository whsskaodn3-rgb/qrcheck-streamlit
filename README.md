# QRCheck – GitHub + Streamlit Community Cloud 배포판

**고정 QR 이미지 → MetaMask 앱 내 브라우저에서 QR 스캔 → 서버에 `SCANNED` 기록 → 가변 길이 숫자 입력 → `VERIFIED` / `PIN_FAILED` / `LOCKED` 이벤트 기록**을 위한 Streamlit 버전입니다.

- 기존 MetaMask 앱을 *수정하지 않습니다.* MetaMask 앱의 **내부 브라우저에서 Streamlit 주소를 여는 방식**입니다.
- 웹페이지가 `wallet_scanQRCode` 레거시 RPC를 호출하려고 시도합니다. **현행 MetaMask 버전과 Streamlit iframe에서 실제 작동하는지는 검증되지 않았습니다.** 호출에 실패하면 **휴대폰 카메라로 스캔**을 사용하세요. 앱 홈 화면의 기본 QR 버튼을 가로채는 방식이 아닙니다.
- 송금·서명·지갑 연결이 없습니다. 정답 번호는 QR별로 설정하며, **기존 고정 QR 그림을 변경할 필요 없이 번호만 변경**할 수 있습니다.
- 관리자 화면에 스캔 시간, 입력한 번호의 원문, 성공/실패가 기록됩니다. 반복 스캔 시 각각 별도 기록을 만듭니다.

## 1. 파일 구조

```text
qrcheck-streamlit/
├─ streamlit_app.py                # Streamlit 사용자/관리자 화면
├─ storage.py                      # SQLite 또는 Supabase 저장소
├─ schema.sql                      # Supabase DB용 SQL
├─ requirements.txt               # Python 종속성
├─ import_v4_qrs.py                # 기존 v4 QR ID 유지 마이그레이션(선택)
├─ components/scanner/index.html   # MetaMask RPC / 웹 카메라 QR 스캐너
├─ .streamlit/config.toml
├─ .streamlit/secrets.toml.example
├─ .gitignore
├─ tests/test_storage.py
└─ README.md
```

## 2. 로컬 실행

Python 3.10 이상이 필요합니다.

```bash
python -m pip install -r requirements.txt
```

`.streamlit/secrets.toml.example`을 `.streamlit/secrets.toml`로 복사하고 다음 값을 변경합니다.

```toml
ADMIN_KEY = "여기에_긴_임의의_관리자_비밀번호"
ENABLE_TEST_MODE = "1"
```

실행:

```bash
streamlit run streamlit_app.py
```

- **스캐너:** `http://localhost:8501/`
- **관리자:** `http://localhost:8501/?mode=admin`
- 관리자에서 QR 이름과 숫자 인증번호(1~32자리)를 입력하고 QR 생성 → PNG 다운로드.
- 로컬에서는 `ENABLE_TEST_MODE = "1"`일 때 `SCAN:...` 텍스트를 복사해 수동 스캔 테스트할 수 있습니다.
- 테스트 종료 후 `ENABLE_TEST_MODE = "0"`으로 변경하세요.

로컬 저장소는 기본 `data/qrcheck.sqlite3`입니다. **이 파일은 GitHub에 올리지 않습니다.**

## 3. GitHub에 업로드

1. GitHub에 `qrcheck-streamlit`이라는 새 **Private** 저장소를 만듭니다(처음에는 비공개 권장).
2. 이 ZIP에서 압축을 해제하고 **폴더 안 파일 전체**를 GitHub 저장소의 루트에 업로드합니다. `.streamlit/config.toml`을 포함하세요.
3. **`.streamlit/secrets.toml`, `data/`, `.env`, 실제 인증값이 들어있는 DB는 업로드하지 마세요.** `.gitignore`가 이를 막도록 구성했습니다.
4. Git 명령으로 올릴 경우:

```bash
git init
git add .
git commit -m "QRCheck Streamlit version"
git branch -M main
git remote add origin https://github.com/내계정/qrcheck-streamlit.git
git push -u origin main
```

## 4. Streamlit Community Cloud 배포

1. <https://share.streamlit.io/> → **Create app** → **GitHub** 저장소 선택.
2. Repository: `내계정/qrcheck-streamlit`, Branch: `main`.
3. Main file path: **`streamlit_app.py`**.
4. **Advanced settings → Secrets**에 아래 내용을 입력합니다.

```toml
ADMIN_KEY = "길고_예측하기_어려운_비밀번호"
ENABLE_TEST_MODE = "0"
```

5. Deploy를 누르면 HTTPS `https://...streamlit.app` URL이 생성됩니다.
6. PC에서 `https://...streamlit.app/?mode=admin`을 열고 관리자 키 입력 → QR 생성.
7. 발급한 QR 이미지를 **다른 화면 또는 종이**에 띄웁니다. MetaMask 모바일 앱 내 브라우저에서 `https://...streamlit.app/`를 열고 QR 스캔을 시도합니다.

**중요:** 위 설정만으로 웹앱은 켜지지만, 데이터는 여전히 Streamlit Cloud 내부 SQLite에 저장되므로 앱 재부팅/재배포 등으로 사라질 수 있습니다. **기록을 실제로 보존하려면 아래 Supabase 연결까지 완료**해야 합니다.

## 5. Supabase 연결 (운영 사용 시 필수)

Streamlit Community Cloud는 로컬 SQLite 파일의 영구 보관을 보장하지 않으므로, 실제 운영에서는 영구 DB를 연결해야 합니다.

1. <https://supabase.com/>에서 프로젝트 생성.
2. Supabase **SQL Editor → New query**에서 제공된 `schema.sql` 전체 실행.
3. Supabase **Project Settings → API Keys**에서 서버 전용 **Secret key (`sb_secret_...`)**를 확인합니다. 오래된 프로젝트의 `service_role` 키도 호환됩니다. **이 키를 GitHub에 업로드하거나 브라우저에 노출하면 안 됩니다.**
4. Streamlit 앱 관리 화면의 **Secrets**에 다음을 추가합니다.

```toml
ADMIN_KEY = "길고_예측하기_어려운_비밀번호"
ENABLE_TEST_MODE = "0"
SUPABASE_URL = "https://프로젝트ID.supabase.co"
SUPABASE_SECRET_KEY = "sb_secret_서버전용키"
```

5. 앱을 재실행하여 고정 QR을 새로 발급합니다. Supabase에 QR 정보와 스캔 기록, 성공/실패 이벤트가 영구 보관됩니다.

**보안 주의:** Supabase의 `anon` 또는 `sb_publishable_...` 키는 사용하지 않습니다. RLS 정책을 활성화했고, 서버 전용 키만 Streamlit 서버에서 사용합니다. 본 서비스는 실제 신원인증이나 출입통제용 보안제품이 아닙니다.

## 6. 기존 v4 QR 이미지 유지하기 (필요한 경우)

기존에 다운로드한 QR 이미지를 살리려면 이전 v4 DB에 저장된 QR ID를 새 DB로 가져와야 합니다. **코드 업로드만으로 과거 DB가 자동 이동하지는 않습니다.**

v4 폴더 안에 `data/scans.sqlite3`가 남아 있으면 다음 명령을 실행하세요.

```bash
# 로컬 SQLite용
python import_v4_qrs.py /경로/v4/data/scans.sqlite3
```

Supabase로 바로 옮기려면 쉘에서 `SUPABASE_URL`과 `SUPABASE_SECRET_KEY` 환경변수를 설정하고 동일한 명령을 실행합니다.

이 작업은 **기존 QR ID와 인증번호, QR 이미지 호환성만 이전**합니다. v4의 과거 스캔/이벤트 기록은 기존 DB에 그대로 남고 새 DB로 복사하지 않습니다. 마이그레이션 전에 원본 DB를 백업하세요.

## 7. 실제 동작 및 한계

| 작업 | 동작 |
|---|---|
| 고정 QR 1개 반복 사용 | 가능 (스캔별 새로운 이벤트 기록) |
| QR별 번호 1~32자리 설정/변경 | 가능, 앞의 0 유지 |
| 스캔 후 별도 페이지 이동 없이 PIN 화면 표시 | Streamlit 페이지 안에서 전환 |
| `1111` 입력 성공·실패 | 해당 QR에 설정된 번호와 서버에서 비교 |
| 실제 입력번호 및 결과 관리자 로그 | 저장 및 CSV 다운로드 |
| 인증 5회 실패 | 해당 스캔 세션 `LOCKED` |
| MetaMask 홈 화면의 기본 QR 버튼 제어 | 불가능 |
| MetaMask `wallet_scanQRCode` | 호출 시도 구현, 최신 앱/iframe 호환성은 실기기 테스트 필요 |
| 일반 휴대폰 웹 카메라 | HTTPS·권한·브라우저 지원 필요; 이 경우 MetaMask 네이티브 스캐너와 다름 |
| Streamlit Cloud 단독으로 영구 기록 저장 | 보장 불가: Supabase 필요 |
| 별도 `/api/scans` 외부 HTTP API | 제공하지 않음. Streamlit은 화면 세션을 통해 Python 백엔드에 기록 |

### 스캔 기록을 과신하면 안 되는 이유

- QR 사진을 복제하거나 앱 이벤트를 위조할 수 있어 **실제 카메라 인식·현장 방문·사용자 신원에 대한 암호학적 증명은 아닙니다.**
- `1111` 같은 번호는 **테스트/확인용**입니다. 실제 계정 암호, 개인 비밀번호, OTP는 이 시스템에 입력받지 마세요.
- 요청에 따라 인증 시도 **원문 PIN을 DB와 관리자 로그에 보관**합니다. 운영에서는 접근권한과 보관기간을 설정하세요.
- MetaMask Provider는 iframe 내에 주입되지 않을 수 있습니다. 그 경우 웹 카메라 방식을 사용해야 합니다.

## 8. 테스트

```bash
python -m unittest discover -s tests -v
```

참고 문서: [Streamlit 배포](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy) · [Community Cloud 파일 저장 한계](https://docs.streamlit.io/develop/concepts/connections/connecting-to-data) · [Streamlit Secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)
