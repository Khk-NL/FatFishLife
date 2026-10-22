from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from fatfish_video.project import Project


@dataclass(frozen=True)
class StoryOptions:
    """Input for one storyboard generation run."""

    topic: str
    duration: float = 30.0
    template: str | None = None
    characters: tuple[str, ...] = ()
    tone: str = "牢大式吐槽"
    panel: Path | None = None
    config_path: Path | None = None
    config_dir: Path | None = None
    output: Path | None = None
    provider: str | None = None
    model: str = "deepseek-chat"
    max_attempts: int = 2


@dataclass(frozen=True)
class GeneratedProject:
    """A validated project config plus provenance for later auditing."""

    project: Project
    config: dict
    config_path: Path
    metadata: dict = field(default_factory=dict)
