ARG POSTGRES_VERSION=18-3.6--v2025.11.24
ARG POSTGRES_MAJOR=18
FROM kartoza/postgis:${POSTGRES_VERSION}

ARG POSTGRES_MAJOR
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       postgresql-${POSTGRES_MAJOR}-pgvector \
       postgresql-${POSTGRES_MAJOR}-pgaudit \
       postgresql-${POSTGRES_MAJOR}-partman \
    && rm -rf /var/lib/apt/lists/*
