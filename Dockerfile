# Playwright's official Python image: Chromium + all system deps preinstalled.
# The image tag MUST match the playwright version pinned in requirements.txt.
FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# All pipeline state (token.json, jobs_*.json, cv_output/, tracker.html ...)
# lives in DATA_DIR — mount a persistent volume here.
ENV DATA_DIR=/data \
    PYTHONUNBUFFERED=1

RUN chmod +x /app/entrypoint.sh

EXPOSE 8000
CMD ["/app/entrypoint.sh"]
