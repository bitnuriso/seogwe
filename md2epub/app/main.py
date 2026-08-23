from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .epub import build_epub
from .parser import parse_folder, parse_single_markdown, project_to_dict

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("MD2EPUB_DATA_DIR", Path.home() / ".local/share/md2epub")).resolve()
OUTPUT_DIR = DATA_DIR / "outputs"
WORK_DIR = DATA_DIR / "work"
for folder in (OUTPUT_DIR, WORK_DIR):
    folder.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="MD Folder to EPUB")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _allowed_roots() -> list[Path]:
    configured = os.getenv("MD2EPUB_ALLOWED_ROOTS", "/mnt/c:/home")
    roots = []
    for raw in configured.split(":"):
        if raw.strip():
            roots.append(Path(raw).expanduser().resolve())
    return roots


def _validate_local_path(raw: str) -> Path:
    candidate = Path(raw).expanduser().resolve()
    if not candidate.exists():
        raise HTTPException(400, "경로가 존재하지 않습니다.")
    if not any(candidate == root or root in candidate.parents for root in _allowed_roots()):
        raise HTTPException(403, "허용된 경로 밖에는 접근할 수 없습니다.")
    return candidate


def _safe_extract(zf: zipfile.ZipFile, target: Path) -> None:
    target = target.resolve()
    for member in zf.infolist():
        dest = (target / member.filename).resolve()
        if target != dest and target not in dest.parents:
            raise HTTPException(400, "안전하지 않은 ZIP 경로가 포함되어 있습니다.")
    zf.extractall(target)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={})


@app.post("/api/build/local")
def build_from_local(
    local_path: str = Form(...),
    title: str = Form(""),
    author: str = Form(""),
    language: str = Form("ko"),
    description: str = Form(""),
):
    path = _validate_local_path(local_path)
    try:
        project = parse_single_markdown(path, title=title, author=author, language=language, description=description) if path.is_file() else parse_folder(path, title=title, author=author, language=language, description=description)
        safe_name = "".join(ch for ch in project.title if ch not in '\\/:*?"<>|').strip() or "book"
        output = OUTPUT_DIR / f"{safe_name}.epub"
        build_epub(project, output)
        return {"project": project_to_dict(project), "download_url": f"/download/{output.name}"}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/build/upload")
async def build_from_upload(
    file: UploadFile = File(...),
    title: str = Form(""),
    author: str = Form(""),
    language: str = Form("ko"),
    description: str = Form(""),
):
    suffix = Path(file.filename or "upload").suffix.lower()
    job = Path(tempfile.mkdtemp(prefix="md2epub-", dir=WORK_DIR))
    uploaded = job / (Path(file.filename or "upload").name)
    try:
        with uploaded.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
        if suffix == ".zip":
            extracted = job / "extracted"
            extracted.mkdir()
            with zipfile.ZipFile(uploaded) as zf:
                _safe_extract(zf, extracted)
            candidates = [p for p in extracted.iterdir() if not p.name.startswith("__MACOSX")]
            root = candidates[0] if len(candidates) == 1 and candidates[0].is_dir() else extracted
            project = parse_folder(root, title=title or root.name, author=author, language=language, description=description)
        elif suffix == ".md":
            project = parse_single_markdown(uploaded, title=title, author=author, language=language, description=description)
        else:
            raise HTTPException(400, "ZIP 또는 MD 파일만 지원합니다.")
        safe_name = "".join(ch for ch in project.title if ch not in '\\/:*?"<>|').strip() or "book"
        output = OUTPUT_DIR / f"{safe_name}.epub"
        build_epub(project, output)
        return {"project": project_to_dict(project), "download_url": f"/download/{output.name}"}
    finally:
        shutil.rmtree(job, ignore_errors=True)


@app.get("/download/{filename}")
def download(filename: str):
    path = (OUTPUT_DIR / Path(filename).name).resolve()
    if path.parent != OUTPUT_DIR or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="application/epub+zip", filename=path.name)


@app.get("/api/health")
def health():
    return JSONResponse({"ok": True, "allowed_roots": [str(p) for p in _allowed_roots()]})
