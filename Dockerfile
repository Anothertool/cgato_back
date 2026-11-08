FROM python:3.13-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

ADD --chmod=0644 https://www.postgresql.org/media/keys/ACCC4CF8.asc /usr/share/keyrings/postgresql-pgdg.asc
RUN echo 'deb [signed-by=/usr/share/keyrings/postgresql-pgdg.asc] https://apt.postgresql.org/pub/repos/apt trixie-pgdg main' \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]
