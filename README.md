# 📚 Sŏgwe (서궤, 書櫃)

**내 폰 안의 작은 개인 출판사 겸 서재**

> Make it. Fix it. Shelve it. Read it.

PDF를 다듬고, 텍스트를 EPUB으로 만들고, 완성된 책을 개인 서재에 보관해 여러 기기에서 읽기 위한 Android 중심의 로컬 도서 작업 환경입니다.

`repo: seogwe`
`CLI: seogwe`
`package/app id: seogwe`

---

## ✨ Overview

Sŏgwe는 책을 다듬고, 만들고, 보관해 읽는 전 과정을 하나의 커다란 앱으로 합치지 않습니다.

대신 각 역할을 독립된 도구로 나누고, 필요할 때만 서로 이어지는 구조를 택했습니다.

* 📚 **PDF 다다다닥** — PDF 정리·크롭·병합
* 📖 **md2epub** — TXT / Markdown 기반 EPUB 제작·편집
* 🏠 **Pocket Library** — 완성된 도서 보관·탐색·배포

현재는 Android + Termux에서 각 도구를 독립적으로 실행합니다.

향후에는 기존 기능을 다시 만드는 대신 실행 환경만 **NIDARY**로 이전하여 가상환경, 의존성, 포트, 프로세스, 로그, 재시작 및 복구를 통합 관리할 계획입니다.

---

## 🚧 Status

현재 주요 기능은 구현을 완료했으며, 실제 개인 도서 제작·열람 환경에서 사용하고 있습니다.

TXT / Markdown 원고를 EPUB으로 변환하고 표지를 적용한 뒤, Pocket Library를 통해 여러 기기에서 내려받아 읽는 전체 흐름이 정상 동작합니다.

현재 버전은 핵심 사용 흐름과 대부분의 편의 기능을 지원하지만, 코드 구조와 UI/UX에는 아직 정리할 부분이 남아 있습니다.

따라서 다음 단계에서는 새로운 기능을 무리하게 추가하기보다 리팩터링과 사용성 개선을 우선하고, 이후 설치·실행 방법과 환경 설정 가이드를 정리할 예정입니다.

---

## 🧭 Architecture

```text
Sŏgwe
                       │
          ┌────────────┼────────────┐
          │            │            │
          ▼            ▼            ▼
   📚 PDF 다다다닥   📖 md2epub   🏠 Pocket Library
    PDF 정리·병합     EPUB 제작      개인 서재·배포
          │            │            │
          └────────────┴──────┬─────┘
                              │
                              ▼
                     📱 Android + Termux
                              │
                              ▼
                      🪺 NIDARY Runtime
                         (향후 이전)
```

세 구성요소는 실행 방식과 의존성이 다르기 때문에 독립된 branch에서 개발합니다.

`main` branch는 각 프로젝트를 디렉터리 단위로 모아둔 통합본입니다.

```text
seogwe/
├── pocket_library/
├── md2epub/
└── pdf_dadadak/
```

각 도구는 독립된 runtime과 dependency를 사용하며, 하나의 실행 환경으로 억지로 통합하지 않습니다.

---

## 📚 1. PDF 다다다닥

> Crop it. Merge it. 다닥다닥 끝.

**무거운 PC 툴 없이 폰에서 바로 끝내는 PDF 정리 도구**

PDF 다다다닥은 원서, 스캔본, 여러 조각으로 분리된 PDF를 스마트폰에서 바로 정리하기 위한 로컬 도구입니다.

### 주요 기능

* 자연 정렬

  * `1, 2, 10` 순서 유지

* 스마트 크롭

  * 직접 영역 지정
  * 흰 여백 자동 감지
  * 권별·폴더 단위 일괄 크롭

* 병합 및 정리

  * 여러 PDF 병합
  * 작업 완료 후 원본 정리

* **기준본 대조 복원 — 예정**

  * 두 버전의 문서를 비교해 워터마크나 출력 흔적 등 차이 영역 식별

---

## 📖 2. md2epub

> Turn messy text into a tidy little bookshelf.

**흩어진 글 조각들을 읽기 좋은 전자책으로 엮습니다.**

md2epub은 TXT와 Markdown을 읽기 좋은 EPUB으로 구성하는 브라우저 기반 편집 서버입니다.

### 주요 기능

* 폴더 구조 기반 권·장 자동 인식

  * 예: `1권/1장.md`, `1권/2장.md`

* 긴 장 자동 분할

  * 내부 소제목 단위 분리

* 일괄 편집

  * 정규표현식 기반 헤더 교체
  * 반복 문구 제거
  * 표지 일괄 적용

* 미리보기

  * 현재: 스크롤 방식
  * 향후: 페이지 넘김 방식 뷰어

---

## 🏠 3. Pocket Library

> Your books stay with you.

**한 곳에 모아두고, 여러 기기로 펼쳐보세요.**

Pocket Library는 완성된 PDF와 EPUB을 보관하고 탐색하기 위한 개인 로컬 서재입니다.

**SD카드를 옮겨 꽂는 대신, 서버를 켜고 필요한 기기에서 바로 꺼내 읽습니다.**

### 설계 원칙

* 원본 파일은 루트 기기인 스마트폰에 보관합니다.
* 구형 이북리더기에서도 사용할 수 있도록 가벼운 웹 인터페이스를 유지합니다.
* MoonReader 등 기존 뷰어가 잘하는 기능은 다시 구현하지 않습니다.

### 주요 기능

* 도서 저장 및 탐색

* 여러 기기로 파일 배포

* **Device Trust**

  * 현재: IP 기반 허용
  * 향후: 6자리 페어링 번호 + 기기 신뢰 토큰
  * 분실 기기 접근 권한 폐기

* **Reading Memory**

  * 책 / 시리즈 / 태그 기반 메모와 하이라이트 관리
  * Markdown 내보내기

---

## 🔄 Workflow

```text
스캔 PDF
   ↓
PDF 다다다닥
   ↓
PDF 정리 완료
   ↓
필요한 경우 텍스트화
   ↓
md2epub
   ↓
EPUB
   ↓
Pocket Library
   ↓
E-reader / Tablet
```

모든 책이 전체 흐름을 거칠 필요는 없습니다.

PDF만 정리하거나, EPUB만 만들거나, Pocket Library만 서재로 사용하는 식으로 각 도구를 독립적으로 사용할 수 있습니다.

---

## 🏗️ Runtime

### 현재 — Android + Termux

현재 Sŏgwe의 각 도구는 Termux 내부에서 독립된 서버 프로젝트로 실행됩니다.

Termux를 선택한 이유는 다음과 같습니다.

* Android에서 직접 실행 가능
* Python 패키지 설치가 간단함
* Android 공유 저장소에 직접 접근 가능
* 기능을 빠르게 실험하고 수정하기 좋음

다만 프로젝트가 늘어나면서 다음 항목을 수동으로 관리해야 하는 문제가 생겼습니다.

`port · process · venv · dependency · log · restart · boot recovery`

---

### 향후 — NIDARY

기존 프로젝트를 다시 작성하는 대신 **실행 환경만 이전**하는 것이 목표입니다.

NIDARY는 각 프로젝트의 다음 영역을 담당합니다.

* Python venv 구성
* dependency 설치
* port 관리
* background 실행
* process monitoring
* restart / boot recovery
* log 관리

> 도구는 책을 관리하고, NIDARY는 도구가 살아 있도록 관리합니다.

---

## 🚧 Roadmap

### Current

**v0.1 — Termux Bookshelf**
세 도구를 Termux 환경에서 독립적으로 실행

### Next

**v0.2 — Shared Workspace**
공통 저장소 구조와 입출력 규칙 정리

**v0.3 — Book Pipeline**
PDF 정리 → EPUB 제작 → Library 저장 흐름 연결

**v0.4 — Device Trust**
Pocket Library 기기 페어링 및 토큰 인증

**v0.5 — Bulk Tools**
대량 메타데이터 수정, 일괄 크롭 등 반복 작업 자동화

### Long-term

**v0.6 — Reading Memory**
메모, 하이라이트, 다운로드 기록 통합

**v0.7 — NIDARY Ready**
각 서버의 실행 선언 및 권한 구조 표준화

**v1.0 — NIDARY Bookshelf**
세 도구를 NIDARY 환경으로 이전해 스마트폰 하나에서 책을 만들고, 정리하고, 보관하는 로컬 작업 환경 완성

---

## 🌟 Philosophy

> 작고, 철저히 로컬에서 동작하며, 오래 곁에 두고 쓸 수 있는 도구를 만듭니다.

* 책과 데이터는 가능한 한 내 기기에 둡니다.
* 자동화는 반복되는 귀찮음이 있는 곳에 적용합니다.
* 만들기, 정리하기, 보관하기의 역할을 명확히 분리합니다.
* 서로 다른 실행 환경을 억지로 하나로 합치지 않습니다.
* 기존 앱이 이미 잘하는 기능은 다시 만들지 않습니다.

지금의 Termux가 이 도구들을 깎고 다듬는 작업실이라면, NIDARY는 훗날 이 작은 도구들이 안정적으로 둥지를 틀 실행 환경이 됩니다.
