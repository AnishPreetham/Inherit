# Inherit web app.
#
# Public demo mode (default here, e.g. Hugging Face Spaces): no Docker on the host, so the
# bundled demo repo (our own trusted code) runs with the local backend and uploads are off.
# Full mode (docker-compose.yml): the app drives the host's Docker to isolate every run.
FROM python:3.11-slim

COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker

RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=app:app inherit/ inherit/
COPY --chown=app:app sandbox/ sandbox/
COPY --chown=app:app demo_repo/ demo_repo/
COPY --chown=app:app demos/ demos/
COPY --chown=app:app samples/ samples/
COPY --chown=app:app README.md LICENSE ./

ENV PYTHONUNBUFFERED=1 \
    INHERIT_PUBLIC_MODE=1 \
    SANDBOX_BACKEND=local \
    INHERIT_RUNS_DIR=/tmp/inherit-runs \
    PORT=7860

USER app
EXPOSE 7860
CMD ["sh", "-c", "uvicorn inherit.server:app --host 0.0.0.0 --port ${PORT}"]
