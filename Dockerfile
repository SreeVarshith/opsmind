# One image for the API, the web UI and the indexing job; docker-compose picks the command.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Dependencies first: this layer is reused until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY ui ./ui
COPY eval ./eval
COPY scripts ./scripts
COPY data ./data
COPY .streamlit ./.streamlit

# Bake the search models into the image, so a new container answers without downloading anything.
RUN python -c "from fastembed import TextEmbedding, SparseTextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='.cache/fastembed'); SparseTextEmbedding('Qdrant/bm25', cache_dir='.cache/fastembed')"

# Do not run as root.
RUN useradd --create-home opsmind && mkdir -p config && chown -R opsmind:opsmind /app
USER opsmind

EXPOSE 8000 8501
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
