# MD Folder to EPUB

WSL에서 로컬 서버로 실행하는 Markdown 전자책 제작기입니다.

## 실행

```bash
cd md2epub_app
./start.sh
```

브라우저에서 `http://localhost:8787`을 엽니다.

## 입력

- WSL에서 접근 가능한 폴더 또는 `.md` 경로
- 폴더를 압축한 `.zip`
- 단일 `.md`

기본 허용 경로는 `/mnt/c`, `/home`입니다. 바꾸려면:

```bash
export MD2EPUB_ALLOWED_ROOTS="/mnt/c/Users/me/Documents:/home/me/books"
./start.sh
```

## 인식 규칙

- 파일과 폴더명에서 `1권`, `제2부`, `3장`, `Chapter 4` 인식
- 파일 내부 첫 제목 또는 Front Matter `title`을 장 제목으로 사용
- 단일 MD는 권·부·장 헤딩을 기준으로 가상 장을 만든 뒤 같은 EPUB 생성 루트를 사용
- 상대경로 이미지 포함

## 주의

현재 MVP는 목차 구조를 자동 분석해 바로 생성합니다. 드래그 재정렬과 표지 업로드는 다음 단계 기능입니다.

## `.venv` 생성 오류가 날 때

WSL Ubuntu/Debian에는 `venv` 모듈이 기본 설치되지 않은 경우가 있습니다.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
./start.sh
```

압축을 Windows에서 풀어 실행 권한이 사라졌다면:

```bash
chmod +x start.sh
./start.sh
```

직접 실행하려면:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```
