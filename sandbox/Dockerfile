FROM python:3.11-slim

RUN pip install --no-cache-dir "pytest>=8.0" "pytest-randomly>=3.15" \
    && useradd --create-home --uid 1000 runner

COPY probe.py /opt/inherit/probe.py

USER runner
WORKDIR /work
