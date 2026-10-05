FROM python:3.12-slim-bookworm
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN --mount=type=secret,id=pip_ca \
    if [ -f /run/secrets/pip_ca ]; then export PIP_CERT=/run/secrets/pip_ca; fi; \
    python -m pip install --no-cache-dir -r backend/requirements.txt
COPY database database
COPY scripts scripts
COPY backend/app/metadata backend/app/metadata
COPY backend/tests backend/tests
CMD ["python", "scripts/seed_database.py"]
