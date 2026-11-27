# MIMIC honeypot — headless image (no visual configurator).
#
# Runs as a non-root user. To listen on ports below 1024 (21, 22, 23, 80)
# start it with:  --sysctl net.ipv4.ip_unprivileged_port_start=0
# (docker-compose.yml already does this).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# pygame is only for the desktop configurator; the container runs headless.
COPY requirements.txt .
RUN grep -v '^pygame' requirements.txt > /tmp/requirements.txt \
 && pip install --no-cache-dir -r /tmp/requirements.txt

RUN useradd --create-home --uid 10001 mimic
COPY --chown=mimic:mimic . .
RUN mkdir -p logs ftp_storage && chown -R mimic:mimic logs ftp_storage config

USER mimic

EXPOSE 21 22 23 80 3306
VOLUME ["/app/logs", "/app/ftp_storage"]

CMD ["python", "main.py", "--config", "config/honeypot.yaml"]
