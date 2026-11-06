FROM python:3.12-slim

RUN useradd --create-home --uid 1000 --home-dir /home/app --shell /usr/sbin/nologin app \
    && mkdir -p /app/data /app/media /sessions \
    && chown app:app /app/data /app/media /sessions /home/app

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY --chown=app:app delivery_monitor /app/delivery_monitor
COPY --chown=app:app app /app/app
COPY --chown=app:app clients /app/clients
COPY --chown=app:app refresh.py /app/refresh.py
COPY --chown=app:app docker-entrypoint.sh /app/docker-entrypoint.sh

RUN chmod 0755 /app/docker-entrypoint.sh \
    && chmod 0755 /app/clients/uber/uber.py /app/clients/pya/pya.py

ENV HOME=/home/app \
    TZ=America/Santiago \
    PYTHONUNBUFFERED=1 \
    SNAPSHOT_PATH=/app/data/snapshot.json \
    MEDIA_DIR=/app/media \
    SESSIONS_DIR=/sessions \
    UBER_CLI=/app/clients/uber/uber.py \
    UBER_CLI_CWD=/app/clients/uber \
    PYA_CLI=/app/clients/pya/pya.py \
    PYA_CLI_CWD=/app/clients/pya

USER app
EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"]
