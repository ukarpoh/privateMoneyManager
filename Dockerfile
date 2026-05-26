FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persistent data directory (mounted as a Railway Volume)
RUN mkdir -p /data

ENV DB_PATH=/data/budget_bot.db
ENV LOG_PATH=/data/budget_bot.log

CMD ["python", "main.py"]
