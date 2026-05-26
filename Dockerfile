FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persistent data directory (mounted as a Railway Volume at /data)
RUN mkdir -p /data

ENV DB_PATH=/data/budget_bot.db
ENV LOG_PATH=/data/budget_bot.log

# Declare /data as a volume mount-point so Railway (and Docker) know
# this directory must come from a persistent volume, not the image layer.
VOLUME ["/data"]

CMD ["python", "main.py"]
