FROM python:3.11-slim-bookworm AS python
FROM pgvector/pgvector:pg16-bookworm
COPY --from=python /usr/local/ /usr/local/
RUN ldconfig && apt-get update && apt-get install -y --no-install-recommends libgomp1 ca-certificates && rm -rf /var/lib/apt/lists/* && useradd -m -u 1000 coach
WORKDIR /app
COPY frontend/requirements.txt frontend/requirements.txt
COPY translation_agent_demo/requirements*.txt translation_agent_demo/
RUN pip install --no-cache-dir -r frontend/requirements.txt
COPY --chown=coach:coach . .
RUN mkdir /app/pgdata /app/model-cache && chown coach:coach /app/pgdata /app/model-cache
USER coach
ENV PYTHONUNBUFFERED=1 HOME=/home/coach HF_HOME=/app/model-cache PGDATA=/app/pgdata PATH=/usr/lib/postgresql/16/bin:$PATH
RUN python -m translation_agent_demo.providers.local_embeddings && bash seed.sh
ENV EMBEDDING_PROVIDER=local LLM_PROVIDER=responses RESPONSES_BASE_URL=https://apikey.casa/v1 LLM_MODEL=gpt-6.1-sol
EXPOSE 7860
ENTRYPOINT ["bash","start.sh"]
