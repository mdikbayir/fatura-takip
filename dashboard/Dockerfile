FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=Europe/Istanbul

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install \
    --no-cache-dir \
    --disable-pip-version-check \
    -r /app/requirements.txt

COPY app.py /app/app.py

CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "1", \
     "--threads", "4", \
     "--access-logfile", "-", \
     "app:app"]
