from __future__ import annotations

import html
import mimetypes
import re
import shutil
import uuid
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

from .models import BookProject

CSS = """
html { -webkit-text-size-adjust: 100%; }
body { font-family: serif; line-height: 1.75; margin: 5%; word-break: keep-all; }
h1, h2, h3 { line-height: 1.3; page-break-after: avoid; }
h1 { font-size: 1.7em; margin-top: 1.8em; }
h2 { font-size: 1.35em; margin-top: 1.5em; }
p { margin: 0.6em 0; }
blockquote { margin: 1em 0; padding-left: 1em; border-left: 0.25em solid #999; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; padding: 0.8em; background: #f3f3f3; }
code { font-family: monospace; }
img { max-width: 100%; height: auto; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #999; padding: 0.35em; }
.title-page { text-align: center; margin-top: 25%; }
.title-page h1 { font-size: 2.2em; }
"""


def _safe_id(value: str, fallback: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    return clean[:60] or fallback


def _xhtml(title: str, body: str, language: str) -> str:
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="{html.escape(language)}" xml:lang="{html.escape(language)}">
<head><meta charset="utf-8"/><title>{html.escape(title)}</title><link rel="stylesheet" type="text/css" href="../styles/book.css"/></head>
<body>{body}</body></html>'''


def build_epub(project: BookProject, output_path: Path) -> Path:
    work = output_path.parent / f".epub-{uuid.uuid4().hex}"
    oebps = work / "OEBPS"
    text_dir = oebps / "text"
    styles_dir = oebps / "styles"
    images_dir = oebps / "images"
    meta_inf = work / "META-INF"
    for folder in (text_dir, styles_dir, images_dir, meta_inf):
        folder.mkdir(parents=True, exist_ok=True)

    (work / "mimetype").write_text("application/epub+zip", encoding="ascii")
    (meta_inf / "container.xml").write_text('''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>''', encoding="utf-8")
    (styles_dir / "book.css").write_text(CSS, encoding="utf-8")

    md = MarkdownIt("commonmark", {"html": False, "linkify": True, "typographer": True}).enable("table")
    manifest = [('css', 'styles/book.css', 'text/css', '')]
    spine = []
    nav_items: list[tuple[str, str, list[tuple[str, str]]]] = []
    copied_assets: dict[Path, str] = {}

    title_body = f'<section class="title-page"><h1>{html.escape(project.title)}</h1><p>{html.escape(project.author)}</p></section>'
    (text_dir / "title.xhtml").write_text(_xhtml(project.title, title_body, project.language), encoding="utf-8")
    manifest.append(('title', 'text/title.xhtml', 'application/xhtml+xml', ''))
    spine.append('title')

    index = 0
    for volume in project.volumes:
        volume_children: list[tuple[str, str]] = []
        for section in volume.sections:
            for chapter in section.chapters:
                index += 1
                item_id = f"chapter-{index}"
                filename = f"chapter-{index:04d}.xhtml"
                rendered = md.render(chapter.markdown)
                soup = BeautifulSoup(rendered, "html.parser")
                if not soup.find(["h1", "h2"]):
                    h1 = soup.new_tag("h1")
                    h1.string = chapter.title
                    soup.insert(0, h1)

                for image in soup.find_all("img"):
                    src = image.get("src", "")
                    if not src or src.startswith(("http://", "https://", "data:")):
                        continue
                    base = chapter.source_path.parent if chapter.source_path else project.assets_root
                    if not base:
                        continue
                    source = (base / src).resolve()
                    if not source.is_file():
                        image["alt"] = (image.get("alt") or "") + " [이미지 없음]"
                        image.attrs.pop("src", None)
                        continue
                    if source not in copied_assets:
                        ext = source.suffix.lower() or ".bin"
                        asset_name = f"asset-{len(copied_assets)+1:04d}{ext}"
                        shutil.copy2(source, images_dir / asset_name)
                        copied_assets[source] = asset_name
                    image["src"] = f"../images/{copied_assets[source]}"

                body = str(soup)
                (text_dir / filename).write_text(_xhtml(chapter.title, body, project.language), encoding="utf-8")
                manifest.append((item_id, f"text/{filename}", "application/xhtml+xml", ''))
                spine.append(item_id)
                label = chapter.title if section.title == "본문" else f"{section.title} · {chapter.title}"
                volume_children.append((label, f"text/{filename}"))
        nav_items.append((volume.title, volume_children[0][1] if volume_children else "text/title.xhtml", volume_children))

    for source, asset_name in copied_assets.items():
        media_type = mimetypes.guess_type(asset_name)[0] or "application/octet-stream"
        manifest.append((f"img-{len([m for m in manifest if m[0].startswith('img-')])+1}", f"images/{asset_name}", media_type, ''))

    nav_html = ['<nav xmlns:epub="http://www.idpf.org/2007/ops" epub:type="toc" id="toc"><h1>목차</h1><ol>']
    for volume_title, volume_href, children in nav_items:
        if len(nav_items) == 1 and volume_title == "본문":
            for label, href in children:
                nav_html.append(f'<li><a href="{html.escape(href)}">{html.escape(label)}</a></li>')
        else:
            nav_html.append(f'<li><a href="{html.escape(volume_href)}">{html.escape(volume_title)}</a><ol>')
            for label, href in children:
                nav_html.append(f'<li><a href="{html.escape(href)}">{html.escape(label)}</a></li>')
            nav_html.append('</ol></li>')
    nav_html.append('</ol></nav>')
    (text_dir / "nav.xhtml").write_text(_xhtml("목차", ''.join(nav_html), project.language), encoding="utf-8")
    manifest.append(('nav', 'text/nav.xhtml', 'application/xhtml+xml', 'properties="nav"'))

    uid = f"urn:uuid:{uuid.uuid4()}"
    manifest_xml = "\n".join(f'<item id="{i}" href="{h}" media-type="{m}" {p}/>' for i, h, m, p in manifest)
    spine_xml = "\n".join(f'<itemref idref="{item_id}"/>' for item_id in spine)
    opf = f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="book-id" version="3.0" xml:lang="{html.escape(project.language)}">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="book-id">{uid}</dc:identifier><dc:title>{html.escape(project.title)}</dc:title><dc:creator>{html.escape(project.author)}</dc:creator><dc:language>{html.escape(project.language)}</dc:language><dc:description>{html.escape(project.description)}</dc:description>
<meta property="dcterms:modified">2026-08-02T00:00:00Z</meta>
</metadata><manifest>{manifest_xml}</manifest><spine>{spine_xml}</spine></package>'''
    (oebps / "content.opf").write_text(opf, encoding="utf-8")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w") as zf:
        zf.write(work / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)
        for file in sorted(work.rglob("*")):
            if file.is_file() and file.name != "mimetype":
                zf.write(file, file.relative_to(work).as_posix(), compress_type=zipfile.ZIP_DEFLATED)
    shutil.rmtree(work, ignore_errors=True)
    return output_path
