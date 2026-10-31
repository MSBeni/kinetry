#!/usr/bin/env bash
# Install the Kinetry service on Ubuntu 22.04/24.04 or Debian 12 without Docker, under systemd.
#
#   sudo deploy/install.sh [SOURCE]
#
# SOURCE is what pip installs: this repository (default: the directory above this script), a wheel file,
# or a pip requirement such as "git+https://github.com/<you>/Kinetry.git@main". Re-running upgrades in place.
# Layout:
#   /opt/kinetry/venv        Python environment
#   /opt/kinetry/home        renderer, Chrome headless shell, fonts (KINETRY_HOME)
#   /var/lib/kinetry/data    jobs, videos, brand packs (KINETRY_DATA_DIR)
#   /etc/kinetry/env         settings and keys (root:kinetry, 0640)
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
SOURCE="${1:-$(dirname "$HERE")}"
PY_SPEC="kinetry[all]"
if [ -d "$SOURCE" ]; then PY_SPEC="$SOURCE[all]"; elif [ -f "$SOURCE" ]; then PY_SPEC="$SOURCE[all]"; else PY_SPEC="$SOURCE"; fi

say() { printf '\n== %s\n' "$*"; }
apt_any() {  # install the first package name that exists (Ubuntu 24.04 renamed many libraries to *t64)
  for p in "$@"; do
    if apt-cache show "$p" >/dev/null 2>&1; then apt-get install -y --no-install-recommends "$p" >/dev/null; return 0; fi
  done
  echo "none of: $* (continuing)"
}

say "system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends python3 python3-venv python3-pip ffmpeg espeak-ng ca-certificates curl \
  fontconfig fonts-liberation fonts-noto-core fonts-noto-cjk >/dev/null
# libraries Chrome's headless shell needs
for set in "libnss3" "libnspr4" "libatk1.0-0t64 libatk1.0-0" "libatk-bridge2.0-0t64 libatk-bridge2.0-0" \
           "libcups2t64 libcups2" "libdrm2" "libxkbcommon0" "libxcomposite1" "libxdamage1" "libxfixes3" "libxrandr2" \
           "libgbm1" "libasound2t64 libasound2" "libpango-1.0-0" "libcairo2" "libxshmfence1"; do
  apt_any $set
done

say "Node.js 22"
if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 22 ]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null
  apt-get install -y nodejs >/dev/null
fi
node --version

say "user and directories"
id kinetry >/dev/null 2>&1 || useradd --system --home-dir /var/lib/kinetry --create-home --shell /usr/sbin/nologin kinetry
mkdir -p /opt/kinetry/home /var/lib/kinetry/data /etc/kinetry
chown -R kinetry:kinetry /opt/kinetry/home /var/lib/kinetry

say "Python environment ($PY_SPEC)"
[ -x /opt/kinetry/venv/bin/python ] || python3 -m venv /opt/kinetry/venv
/opt/kinetry/venv/bin/pip install -q --upgrade pip
/opt/kinetry/venv/bin/pip install -q "$PY_SPEC"

say "settings (/etc/kinetry/env)"
if [ ! -f /etc/kinetry/env ]; then
  KEY="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 40)"
  cat > /etc/kinetry/env <<ENV
# Kinetry service settings. Restart after editing: systemctl restart kinetry
KINETRY_BIND=127.0.0.1
KINETRY_PORT=8080
KINETRY_API_KEY=$KEY
KINETRY_HOME=/opt/kinetry/home
KINETRY_DATA_DIR=/var/lib/kinetry/data
KINETRY_WORKERS=1
KINETRY_QUALITY=standard
HYPERFRAMES_NO_TELEMETRY=1
HYPERFRAMES_NO_UPDATE_CHECK=1
# Model: callers bring their own (BYOK) by default. To give the server its own:
# KINETRY_LLM=bedrock:<model id or inference profile>
# AWS_REGION=us-east-1
# Optional: S3 uploads, callbacks, public base URL for links
# KINETRY_S3_BUCKET=
# KINETRY_CALLBACK_SECRET=
# KINETRY_PUBLIC_URL=https://kinetry.example.com
ENV
  echo "created with a new API key (see the file)"
fi
# the local voice runs through a Python that has kokoro-onnx: the service's, not the system one
grep -q '^HYPERFRAMES_PYTHON=' /etc/kinetry/env || echo 'HYPERFRAMES_PYTHON=/opt/kinetry/venv/bin/python' >> /etc/kinetry/env
chown root:kinetry /etc/kinetry/env
chmod 0640 /etc/kinetry/env

say "renderer, Chrome and the voice model (as the kinetry user)"
run_as() { runuser -u kinetry -- env HOME=/var/lib/kinetry KINETRY_HOME=/opt/kinetry/home \
  HYPERFRAMES_NO_TELEMETRY=1 HYPERFRAMES_NO_UPDATE_CHECK=1 HYPERFRAMES_PYTHON=/opt/kinetry/venv/bin/python \
  PATH="/opt/kinetry/venv/bin:$PATH" "$@"; }
run_as kinetry setup
run_as bash -c 'cd /tmp && /opt/kinetry/home/tooling/node_modules/.bin/hyperframes tts "Ready." -o /tmp/tf-warm.wav >/dev/null && rm -f /tmp/tf-warm.wav'
run_as kinetry doctor

say "systemd service"
install -m 0644 "$HERE/kinetry.service" /etc/systemd/system/kinetry.service
systemctl daemon-reload
systemctl enable kinetry >/dev/null 2>&1
systemctl restart kinetry
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$(. /etc/kinetry/env; echo "$KINETRY_PORT")/health" >/dev/null 2>&1; then
    echo "running: $(curl -fsS http://127.0.0.1:"$(. /etc/kinetry/env; echo "$KINETRY_PORT")"/health)"
    exit 0
  fi
  sleep 2
done
echo "the service didn't answer /health; see: journalctl -u kinetry -n 100"
exit 1
