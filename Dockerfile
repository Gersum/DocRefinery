FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY rubric ./rubric
COPY corpus ./corpus

RUN pip install --no-cache-dir .

CMD ["python", "-m", "src.run_corpus", "--help"]
