# Use an official Python runtime as the base image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install dependencies first so this layer is cached unless
# requirements.txt actually changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# The app listens on 8080 (see main.py / docker-compose.yml) — this used
# to say 5000 while the app actually ran on 8080; fixed to match.
EXPOSE 8080

# MONGO_URI is intentionally left unset here: the app falls back to its
# built-in map data if it's not provided. Set it via `docker run -e` or
# docker-compose.yml to enable the MongoDB-backed features.
ENV MONGO_URI=""

# gunicorn (already in requirements.txt) instead of the Flask dev server —
# appropriate for anything beyond local development.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "main:app"]
