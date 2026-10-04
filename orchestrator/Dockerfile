FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir psycopg2-binary httpx psutil

COPY . .

CMD ["python", "orchestrator.py"]