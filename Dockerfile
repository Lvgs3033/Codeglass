FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

ENV PORT=8080
EXPOSE 8080

CMD gunicorn --chdir backend app:app --bind 0.0.0.0:${PORT} --workers 2 --timeout 60
