from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Chapter:
    title: str
    markdown: str
    source_path: Path | None = None
    order: int = 0


@dataclass
class Section:
    title: str
    chapters: list[Chapter] = field(default_factory=list)
    order: int = 0


@dataclass
class Volume:
    title: str
    sections: list[Section] = field(default_factory=list)
    order: int = 0


@dataclass
class BookProject:
    title: str
    author: str
    language: str = "ko"
    description: str = ""
    volumes: list[Volume] = field(default_factory=list)
    assets_root: Path | None = None

    def chapter_count(self) -> int:
        return sum(len(section.chapters) for volume in self.volumes for section in volume.sections)
