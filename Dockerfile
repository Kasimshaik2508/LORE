# LORE in one container: the public agent (mailbox) plus the four specialists.
# Set LORE_SEED to keep the same agent addresses as your local install.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PYTHONUNBUFFERED=1 \
    LORE_MAILBOX=1 \
    LORE_PORT=8000 \
    LORE_DB=/app/data/lore.db
EXPOSE 8000

CMD ["python", "-u", "run_agents.py"]
