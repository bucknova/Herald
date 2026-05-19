FROM python:3.12-slim

LABEL maintainer="bucknova"
LABEL description="Herald — D&D 5e Discord bot"

WORKDIR /app

# Build context is the repository root (see root docker-compose.yml).
# We copy herald-bot/ and shared/ into the same /app directory so the
# bot's flat imports (e.g. `import database as db`) resolve as before.

COPY herald-bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY herald-bot/ /app/
COPY shared/ /app/

# Data volume for SQLite persistence
VOLUME /app/data

CMD ["python", "bot.py"]
