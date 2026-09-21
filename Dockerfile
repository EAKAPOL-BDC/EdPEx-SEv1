FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements-production.txt ./
RUN pip install --no-cache-dir -r requirements-production.txt
COPY . .
RUN python manage.py collectstatic --noinput --settings=edpex.static_build \
    && useradd --uid 10001 --create-home nexora
USER nexora
ENV DJANGO_SETTINGS_MODULE=edpex.production
EXPOSE 8000
# Database migration and data import are deliberate release steps, never startup side effects.
# Request access logging stays off: survey URLs can contain confidential tokens.
CMD ["sh", "-c", "exec gunicorn edpex.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --threads 2 --timeout 60"]
