from pathlib import Path

from app.epub import build_epub
from app.parser import parse_folder, parse_single_markdown


def test_folder(tmp_path: Path):
    (tmp_path / "1장 시작.md").write_text("# 1장 시작\n\n본문", encoding="utf-8")
    (tmp_path / "2장 끝.md").write_text("# 2장 끝\n\n끝", encoding="utf-8")
    project = parse_folder(tmp_path, title="테스트", author="저자")
    out = tmp_path / "book.epub"
    build_epub(project, out)
    assert project.chapter_count() == 2
    assert out.exists() and out.stat().st_size > 0


def test_single(tmp_path: Path):
    md = tmp_path / "book.md"
    md.write_text("# 책\n\n## 1장 시작\n본문\n\n## 2장 끝\n끝", encoding="utf-8")
    project = parse_single_markdown(md, title="", author="저자")
    assert project.chapter_count() == 2
