FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml .

RUN uv pip install --system -e ".[web]"

COPY core.py gui_web.py ./

EXPOSE 8080

CMD ["python", "gui_web.py"]