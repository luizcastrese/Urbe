FROM python:3.12-slim-bookworm

RUN useradd --create-home --uid 1000 urbe
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=urbe:urbe . .
USER urbe

ENV PORT=3000
ENV PYTHONUNBUFFERED=1
EXPOSE 3000

CMD ["python3", "-m", "py_backend.server"]
