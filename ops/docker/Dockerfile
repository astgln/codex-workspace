FROM node:22-bookworm-slim AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS package
WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY web/licenses/ web/licenses/
COPY src/ src/
RUN pip wheel --no-cache-dir --wheel-dir /wheels ".[relay]"

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    WORKSPACE_CONFIG=/run/config/relay.json WORKSPACE_DATA=/var/lib/codex-workspace \
    WORKSPACE_STATIC=/app/static
COPY --from=package /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels 'codex-workspace[relay]' \
    && rm -rf /wheels \
    && groupadd --gid 10001 workspace \
    && useradd --uid 10001 --gid 10001 --no-create-home workspace \
    && mkdir -p /var/lib/codex-workspace \
    && chown workspace:workspace /var/lib/codex-workspace \
    && chmod 700 /var/lib/codex-workspace
COPY --from=web /build/web/dist /app/static
COPY ops/docker/static_manifest.py /app/static_manifest.py
RUN python /app/static_manifest.py /app/static && rm /app/static_manifest.py
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
CMD ["python", "-m", "codex_workspace.relay.container"]
