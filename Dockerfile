# Stage 1: build the React app.
FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: the API, which also serves the built React app. The indexing job uses this image too.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Dependencies first: this layer is reused until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY data ./data
COPY --from=frontend /frontend/dist ./frontend/dist

# Bake the search models into the image, so a new container answers without downloading anything.
RUN python -c "from fastembed import TextEmbedding, SparseTextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='.cache/fastembed'); SparseTextEmbedding('Qdrant/bm25', cache_dir='.cache/fastembed')"

# Do not run as root.
RUN useradd --create-home opsmind && mkdir -p config && chown -R opsmind:opsmind /app
USER opsmind

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
