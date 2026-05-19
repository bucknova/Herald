FROM python:3.12-slim

LABEL maintainer="bucknova"
LABEL description="Herald Web — D&D 5e campaign portal"

WORKDIR /app

# Build context is the repository root (see root docker-compose.yml).
# herald-web/ and shared/ are copied into /app so the web app can import
# from `shared.*` without path gymnastics.

COPY herald-web/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY herald-web/ /app/
COPY shared/ /app/shared/

EXPOSE 8088

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
