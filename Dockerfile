FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN useradd --system --uid 10001 --create-home --home-dir /app --shell /usr/sbin/nologin relay

WORKDIR /app

COPY src/ /app/src/
COPY config/relay_config.example.json /app/config/relay_config.example.json
COPY requirements.txt /app/requirements.txt

RUN chown -R relay:relay /app

USER relay

ENTRYPOINT ["python3", "/app/src/main.py"]
CMD ["--config", "/config/relay_config.json"]
