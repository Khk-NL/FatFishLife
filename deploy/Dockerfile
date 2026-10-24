# Official AstrBot v4.29.1, manifest digest checked on 2026-10-23.
FROM soulter/astrbot@sha256:a140a326163ac5f82f62153f033cddeac74e38e4ee1809c6e333e950ff19edc4

# Upstream image already includes FFmpeg, libass and Noto CJK fonts.
COPY pyproject.toml /opt/fatfish/pyproject.toml
COPY fatfish_video /opt/fatfish/fatfish_video
COPY fatfish_story /opt/fatfish/fatfish_story
COPY fatfish_bili /opt/fatfish/fatfish_bili
COPY fatfish_core /opt/fatfish/fatfish_core
RUN python -m venv /opt/bili-venv \
    && /opt/bili-venv/bin/python -m pip install --no-cache-dir "bili-agent==0.6.0" \
    && python -m pip install --no-cache-dir -e /opt/fatfish "chinese-calendar==1.11.0" \
    && python -c "from fatfish_core import MemoryStore, SeenStore, StateStore, build_context; from fatfish_core.growth import record_capability; from fatfish_core.steam import SteamStore; from fatfish_story.review import ReviewQueue"

WORKDIR /AstrBot
