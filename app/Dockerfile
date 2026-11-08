FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The build context is ./app, copied as the "app" package (imports are "from app.domain...").
COPY . ./app

RUN useradd --create-home appuser
USER appuser

EXPOSE 5000

# Single worker on purpose: requests, rate limiter and background jobs live in process memory.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000", "--no-access-log"]
