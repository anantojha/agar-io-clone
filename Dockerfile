FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Not root. UID 1000 is also what Hugging Face Spaces expects.
RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app:app game ./game
COPY --chown=app:app server ./server
COPY --chown=app:app client ./client

USER app

# The host sets PORT (Render uses 10000); 8000 is the fallback. Hugging Face wants app_port to match.
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=4)"

# One worker: the whole game lives in this process's memory. --forwarded-allow-ips='*' is needed
# because the host's proxy is not on localhost; the app's own limits still read X-Forwarded-For
# only when AGAR_TRUST_PROXY=1.
CMD ["sh", "-c", "exec uvicorn server.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
