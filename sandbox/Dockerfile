# Image for coding jobs: one container per job, commands run via `docker exec`.
FROM node:22-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends git python3 python3-pip python3-venv build-essential \
    && rm -rf /var/lib/apt/lists/*

# pin these for reproducible runs, e.g. @anthropic-ai/claude-code@<version>
RUN npm install -g @anthropic-ai/claude-code @openai/codex

# uv for Python projects; allow plain pip installs too (Debian blocks them by default, PEP 668).
# Generous timeouts because package downloads can be slow through Docker Desktop.
RUN pip3 install --break-system-packages uv
ENV PIP_BREAK_SYSTEM_PACKAGES=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    UV_HTTP_TIMEOUT=120

# Claude Code refuses --dangerously-skip-permissions as root
RUN useradd --create-home --uid 1001 agent \
    && mkdir /work && chown agent:agent /work

USER agent
RUN git config --global user.name "ai-coworker[bot]" \
    && git config --global user.email "ai-coworker-bot@users.noreply.github.com"

WORKDIR /work
CMD ["sleep", "infinity"]
