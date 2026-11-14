# Base image pinned by digest; Dependabot proposes bumps.
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SIFT_DB=/data/sift.db SIFT_ENV=production
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
 && useradd --system --uid 10001 sift \
 && mkdir /data && chown sift /data
COPY sift ./sift
USER sift
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
# One worker by default; with SIFT_REDIS_URL set the limiter is shared, so --workers can scale up.
# Proxy headers are honoured only from loopback and the Docker networks nginx runs on.
CMD ["uvicorn", "sift.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", \
  "--forwarded-allow-ips", "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12"]
