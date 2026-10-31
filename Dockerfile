# Kinetry service image: Python + Node + Chromium + FFmpeg + Kokoro, ready to render.
#   docker build -t kinetry .
#   docker run -p 8080:8080 -e KINETRY_API_KEY=... -e KINETRY_LLM=anthropic:claude-sonnet-5-5 \
#     -e ANTHROPIC_API_KEY=... -v kinetry-data:/data kinetry
FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    KINETRY_HOME=/opt/kinetry KINETRY_DATA_DIR=/data \
    KINETRY_BROWSER_PATH=/usr/bin/chromium \
    HYPERFRAMES_NO_TELEMETRY=1 HYPERFRAMES_NO_UPDATE_CHECK=1

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && apt-get update && apt-get install -y --no-install-recommends \
      chromium ffmpeg fonts-liberation fonts-noto-core fonts-noto-cjk ca-certificates espeak-ng \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY pyproject.toml README.md LICENSE THIRD_PARTY.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[all]" && kinetry setup --no-browser

RUN useradd -m -u 10001 kinetry && mkdir -p /data && chown -R kinetry /data "$KINETRY_HOME"
USER kinetry
# Warm the Kokoro model as the service user: HyperFrames keeps it under $HOME/.cache, so a copy made as root
# would be invisible at runtime and the first job would download it again (or fail without internet).
RUN cd /tmp && "$KINETRY_HOME/tooling/node_modules/.bin/hyperframes" tts "Ready." -o /tmp/warm.wav \
 && rm /tmp/warm.wav && test -s "$HOME/.cache/hyperframes/tts/models/kokoro-v1.0.onnx" \
 && kinetry doctor
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')"
CMD ["kinetry", "serve", "--host", "0.0.0.0", "--port", "8080"]
