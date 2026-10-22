"""DeepSeek-backed storyboard generation on top of the local video engine.

The engine stays independent: this package only produces a validated project
config and optionally hands it to ``fatfish_video.render_project``.
"""

from .options import GeneratedProject, StoryOptions
from .pipeline import StoryError, generate_project

__all__ = ["GeneratedProject", "StoryOptions", "StoryError", "generate_project"]
