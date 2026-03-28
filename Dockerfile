FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WA_BASE_DIR=/app/data \
    WA_DB_PATH=/app/data/wa_agent.db \
    WA_HOST=0.0.0.0 \
    WA_PORT=9100

WORKDIR /app

COPY . /app
RUN chmod +x /app/docker-entrypoint.sh \
    && mkdir -p /app/data

EXPOSE 9000 9100

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["agent"]
