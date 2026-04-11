# ── Stage 1: dependency builder ───────────────────────────────────────────────
# The UBI9 Python image activates a virtualenv at /opt/app-root, so we install
# directly into it (no --user flag) and copy the whole venv to stage 2.
FROM registry.access.redhat.com/ubi9/python-311:latest AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM registry.access.redhat.com/ubi9/python-311:latest

LABEL name="jboss-ai-monitor" \
      version="1.0.0" \
      description="Agentic AI monitor for JBoss/WildFly on OpenShift" \
      maintainer="your-team@example.com"

# Copy the fully-populated virtualenv from the builder stage.
# The UBI9 Python image's venv lives at /opt/app-root.
COPY --from=builder /opt/app-root /opt/app-root

WORKDIR /app

# Copy application source
COPY src/ ./src/

# The UBI9 Python base image already sets USER 1001, so we must explicitly
# switch back to root to run chgrp, then drop back to non-root.
USER 0
RUN chgrp -R 0 /app && chmod -R g=u /app

# Non-root user (matches OpenShift default SCC)
USER 1001

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

CMD ["python", "-m", "src.main"]
