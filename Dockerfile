FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 DATABASE_PATH=/data/ccc.sqlite3
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data
EXPOSE 8000

# One worker: in simple mode the agents run on threads inside it. In celery mode, scale web workers freely.
CMD gunicorn -w 1 --threads 8 -b 0.0.0.0:${PORT} --timeout 60 ccc.web:app
