FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WOT_DATA_ROOT=/data
RUN pip install --no-cache-dir gunicorn==26.2.0
COPY wot_engine /app/wot_engine
COPY mechanics.md weave-catalogue.md curriculum.md lore-and-oaths.md /app/
COPY deployment/gunicorn.conf.py /app/gunicorn.conf.py
CMD ["gunicorn", "--config", "/app/gunicorn.conf.py", "wot_engine.cloud_http:application_from_environment()"]
