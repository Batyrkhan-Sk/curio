# The Playwright image ships the browsers but not the Python package, so the
# pin here and the image tag have to move together — a mismatch between the
# client and the bundled Chromium is the usual cause of "Executable doesn't
# exist" at launch.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /worker

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 8090

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8090}"]
