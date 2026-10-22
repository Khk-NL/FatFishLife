"""Independent rendering API; importing this package starts no processes."""

from .project import ProjectError, load_project
from .renderer import RenderError, RenderResult, render_project

__all__ = ["ProjectError", "RenderError", "RenderResult", "load_project", "render_project"]

