FROM python:3.12-slim

# Python runtime configuration
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Create a non-root application user
RUN groupadd --system django \
    && useradd --system --gid django --create-home django

# Copy application source
COPY --chown=django:django . .

# Directory used by Django collectstatic
RUN mkdir -p /app/staticfiles \
    && chown -R django:django /app

USER django

EXPOSE 8000

# Production default: Gunicorn
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--graceful-timeout", "30", \
     "--timeout", "60"]
