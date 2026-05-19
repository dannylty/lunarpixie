FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install system deps + Node.js 20 in one layer
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates git bubblewrap openssh-client && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get purge -y gnupg && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user early (cached unless this line changes)
RUN useradd -m -u 1000 -s /bin/bash nanobot && \
    mkdir -p /home/nanobot/.nanobot

# Git config (cached unless this line changes)
RUN git config --global --add url."https://github.com/".insteadOf ssh://git@github.com/ && \
    git config --global --add url."https://github.com/".insteadOf git@github.com:

WORKDIR /app

# --- Python deps (cached unless pyproject.toml changes) ---
COPY pyproject.toml README.md LICENSE ./
RUN mkdir -p nanobot && touch nanobot/__init__.py && \
    uv pip install --system --no-cache . && \
    rm -rf nanobot

# --- WhatsApp bridge deps (cached unless package.json changes) ---
COPY bridge/package.json ./bridge/
RUN cd /app/bridge && npm install --production

# --- Source (invalidates only from here down) ---
COPY nanobot/ nanobot/
COPY bridge/ bridge/

# Final Python install with real source
RUN uv pip install --system --no-cache .

# Build WhatsApp bridge
WORKDIR /app/bridge
RUN npm run build
WORKDIR /app

# Set ownership
RUN chown -R nanobot:nanobot /home/nanobot /app

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh

USER nanobot
ENV HOME=/home/nanobot

# Gateway default port
EXPOSE 18790

ENTRYPOINT ["entrypoint.sh"]
CMD ["status"]
