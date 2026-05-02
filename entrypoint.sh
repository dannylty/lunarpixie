#!/bin/sh
# Workspace = $HOME by default; agent state lives at $HOME/.nanobot.
dir="$HOME"
if [ -d "$dir" ] && [ ! -w "$dir" ]; then
    owner_uid=$(stat -c %u "$dir" 2>/dev/null || stat -f %u "$dir" 2>/dev/null)
    cat >&2 <<EOF
Error: $dir is not writable (owned by UID $owner_uid, running as UID $(id -u)).

Fix (pick one):
  Host:   sudo chown -R 1000:1000 ~/nanobot
  Docker: docker run --user \$(id -u):\$(id -g) ...
  Podman: podman run --userns=keep-id ...
EOF
    exit 1
fi

# Start internal services if the services directory exists
if [ -d "$HOME/services" ] && [ -f "$HOME/services/start.sh" ]; then
    echo "Starting internal services..."
    bash "$HOME/services/start.sh"
    sleep 2
fi

exec nanobot "$@"
