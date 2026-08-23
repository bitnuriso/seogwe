from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import yaml
from markdown_it import MarkdownIt

from .models import BookProject, Chapter, Section, Volume

VOLUME_RE = re.compile(r"^(?:제\s*)?(\d+)\s*권(?:\s*[-_:]?\s*(.*))?$", re.I)
PART_RE = re.compile(r"^(?:제\s*)?(\d+)\s*(?:부|편)(?:\s*[-_:]?\s*(.*))?$", re.I)
CHAPTER_RE = re.compile(r"^(?:제\s*)?(\d+)\s*장(?:\s*[-_:]?\s*(.*))?$", re.I)
EN_CHAPTER_RE = re.compile(r"^(?:chapter|chap\.?)\s*(\d+)(?:\s*[-_:]?\s*(.*))?$", re.I)
PREFIX_RE = re.compile(r"^\s*\d+[._\-\s]+")
FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)


def _clean_name(value: str) -> str:
    value = Path(value).stem
    value = PREFIX_RE.sub("", value)
    return value.replace("_", " ").strip() or "제목 없음"


def _front_matter(text: str) -> tuple[dict, str]:
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        data = yaml.safe_load(match.group(1)) or {}
        return data if isinstance(data, dict) else {}, text[match.end():]
    except yaml.YAMLError:
        return {}, text


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return None


def _title_for_file(path: Path, text: str) -> tuple[str, dict, str]:
    meta, body = _front_matter(text)
    title = str(meta.get("title") or _first_heading(body) or _clean_name(path.name))
    return title, meta, body


def _classify_label(label: str) -> tuple[str, int | None, str]:
    clean = label.strip()
    for kind, regex in (("volume", VOLUME_RE), ("section", PART_RE), ("chapter", CHAPTER_RE), ("chapter", EN_CHAPTER_RE)):
        match = regex.match(clean)
        if match:
            number = int(match.group(1))
            suffix = (match.group(2) or "").strip()
            display = clean if not suffix else clean
            return kind, number, display
    return "plain", None, clean


def _default_volume() -> Volume:
    return Volume(title="본문", sections=[Section(title="본문")])


def parse_folder(root: Path, *, title: str, author: str, language: str = "ko", description: str = "") -> BookProject:
    root = root.resolve()
    md_files = [p for p in root.rglob("*.md") if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts)]
    def natural_key(path: Path):
        text = str(path.relative_to(root)).lower()
        return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]
    md_files = sorted(md_files, key=natural_key)
    if not md_files:
        raise ValueError("Markdown 파일을 찾지 못했습니다.")

    project = BookProject(title=title or root.name, author=author, language=language, description=description, assets_root=root)
    volume_map: dict[str, Volume] = {}

    for idx, path in enumerate(md_files, start=1):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        chapter_title, meta, body = _title_for_file(path, text)
        rel = path.relative_to(root)
        dirs = list(rel.parts[:-1])

        volume_title = "본문"
        section_title = "본문"
        for directory in dirs:
            kind, _, label = _classify_label(_clean_name(directory))
            if kind == "volume":
                volume_title = label
            elif kind == "section":
                section_title = label
            elif volume_title == "본문":
                section_title = _clean_name(directory)

        file_kind, _, file_label = _classify_label(chapter_title)
        if file_kind == "volume":
            volume_title = file_label
            section_title = "본문"
        elif file_kind == "section":
            section_title = file_label

        volume = volume_map.setdefault(volume_title, Volume(title=volume_title, order=len(volume_map)))
        section = next((s for s in volume.sections if s.title == section_title), None)
        if section is None:
            section = Section(title=section_title, order=len(volume.sections))
            volume.sections.append(section)

        order = int(meta.get("order", idx)) if str(meta.get("order", idx)).isdigit() else idx
        section.chapters.append(Chapter(title=chapter_title, markdown=body, source_path=path, order=order))

    for volume in project.volumes:
        volume.sections.sort(key=lambda s: s.order)
        for section in volume.sections:
            section.chapters.sort(key=lambda c: c.order)

    project.volumes = list(volume_map.values())
    return project


def parse_single_markdown(path: Path, *, title: str, author: str, language: str = "ko", description: str = "") -> BookProject:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    meta, body = _front_matter(text)
    project_title = title or str(meta.get("title") or _first_heading(body) or path.stem)
    project_author = author or str(meta.get("author") or "")

    md = MarkdownIt()
    tokens = md.parse(body)
    headings: list[tuple[int, str, int, int]] = []
    lines = body.splitlines(keepends=True)

    for i, token in enumerate(tokens):
        if token.type == "heading_open" and token.map and i + 1 < len(tokens):
            level = int(token.tag[1])
            label = tokens[i + 1].content.strip()
            headings.append((level, label, token.map[0], token.map[1]))

    project = BookProject(title=project_title, author=project_author, language=language, description=description, assets_root=path.parent)
    if not headings:
        project.volumes = [Volume(title="본문", sections=[Section(title="본문", chapters=[Chapter(title=path.stem, markdown=body, source_path=path)])])]
        return project

    structural = [(level, label, start) for level, label, start, _ in headings if _classify_label(label)[0] in {"volume", "section", "chapter"}]
    chapter_level = None
    chapter_candidates = [level for level, label, _ in structural if _classify_label(label)[0] == "chapter"]
    if chapter_candidates:
        chapter_level = min(chapter_candidates)
    else:
        levels = [level for level, _, _, _ in headings if level > 1]
        chapter_level = min(levels) if levels else headings[0][0]

    current_volume = Volume(title="본문")
    current_section = Section(title="본문")
    current_volume.sections.append(current_section)
    project.volumes.append(current_volume)

    chapter_starts: list[tuple[int, str, int]] = []
    for level, label, start, _ in headings:
        kind, _, clean = _classify_label(label)
        if kind == "volume":
            current_volume = Volume(title=clean, order=len(project.volumes))
            current_section = Section(title="본문")
            current_volume.sections.append(current_section)
            project.volumes.append(current_volume)
        elif kind == "section":
            current_section = Section(title=clean, order=len(current_volume.sections))
            current_volume.sections.append(current_section)
        elif kind == "chapter" or (kind == "plain" and level == chapter_level):
            chapter_starts.append((start, label, len(project.volumes) - 1))

    if not chapter_starts:
        current_section.chapters.append(Chapter(title=project_title, markdown=body, source_path=path))
        return _prune_empty(project)

    # Re-walk headings while slicing to preserve active volume/section at each chapter.
    current_volume = project.volumes[0]
    current_section = current_volume.sections[0]
    chapter_points: list[tuple[int, str, Volume, Section]] = []
    for level, label, start, _ in headings:
        kind, _, clean = _classify_label(label)
        if kind == "volume":
            current_volume = next(v for v in project.volumes if v.title == clean)
            current_section = current_volume.sections[0]
        elif kind == "section":
            current_section = next(s for s in current_volume.sections if s.title == clean)
        elif kind == "chapter" or (kind == "plain" and level == chapter_level):
            chapter_points.append((start, label, current_volume, current_section))

    for i, (start, label, volume, section) in enumerate(chapter_points):
        end = chapter_points[i + 1][0] if i + 1 < len(chapter_points) else len(lines)
        chunk = "".join(lines[start:end]).strip() + "\n"
        section.chapters.append(Chapter(title=label, markdown=chunk, source_path=path, order=i))

    return _prune_empty(project)


def _prune_empty(project: BookProject) -> BookProject:
    volumes: list[Volume] = []
    for volume in project.volumes:
        sections = [s for s in volume.sections if s.chapters]
        if sections:
            volume.sections = sections
            volumes.append(volume)
    project.volumes = volumes or [_default_volume()]
    return project


def project_to_dict(project: BookProject) -> dict:
    return {
        "title": project.title,
        "author": project.author,
        "language": project.language,
        "description": project.description,
        "chapter_count": project.chapter_count(),
        "volumes": [
            {
                "title": volume.title,
                "sections": [
                    {
                        "title": section.title,
                        "chapters": [
                            {"title": chapter.title, "source": str(chapter.source_path or "")}
                            for chapter in section.chapters
                        ],
                    }
                    for section in volume.sections
                ],
            }
            for volume in project.volumes
        ],
    }
