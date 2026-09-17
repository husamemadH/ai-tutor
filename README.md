# AI Tutor

Dialect-aware AI tutor grounded in textbooks. Text-only POC: ingest a book, ask
questions in Jordanian dialect, get answers grounded strictly in the book.

## Stack

- Python 3.12 (uv), FastAPI, SQLAlchemy
- Postgres + pgvector (Docker)
- OpenRouter for both chat (`deepseek/deepseek-v4.1-flash`) and embeddings (`baai/bge-m3`)

## Setup

```bash
cp .env.example .env      # add OPENROUTER_API_KEY
docker compose up -d
uv sync
uv run ai-tutor init-db

# optional: restore prebuilt books + chunks, skipping OCR and embedding
bash scripts/pull_db.sh
```

`scripts/pull_db.sh` downloads a data-only dump of `books` + `chunks` from the
`db-data` GitHub release and restores it into the local DB. This avoids re-running
OCR + embedding after a fresh clone. Note the dump contains the extracted book
text, so it is distributed as a release asset rather than tracked in git.

To regenerate and publish the dump after (re-)ingesting books:

```bash
bash scripts/dump_db.sh
gh release upload db-data dist/ai_tutor_data.sql.gz --clobber
```

## Health

```bash
uv run uvicorn ai_tutor.api.main:app --reload
curl localhost:8000/health
```

## Usage

```bash
# ingest a textbook (M1)
uv run scripts/ingest.py data/books/your-book.pdf --grade 4 --subject science

# chat (M2/M3)
uv run ai-tutor chat
```

## Testing

```bash
uv run pytest                 # offline unit tests (no API/DB)

# end-to-end without a real PDF:
uv run scripts/ingest_sample.py   # clean Arabic sample book
uv run ai-tutor books
uv run ai-tutor chat
```

Note: `scripts/make_sample_book.py` generates a PDF, but Arabic shaped-text
extraction from it is garbled (presentation forms, no ToUnicode map). Real books
must either extract cleanly or need OCR. `ingest_sample.py` bypasses extraction
so the rest of the pipeline can be tested.

## Layout

```
src/ai_tutor/
  config.py        env-driven settings
  db.py            engine + session
  models.py        books / chunks / sessions / messages
  openrouter.py    shared HTTP client
  embeddings.py    batched embeddings
  llm.py           chat completions
  api/main.py      FastAPI app
  cli.py           CLI entry point
  ingest/          parse -> chunk -> embed -> store   (M1)
  rag/             filtered vector retrieval           (M2)
  memory/          get_context / append seam           (M3)
  tutor/           prompt builder + service            (M2)
```

## Roadmap

- **M0** scaffold (done)
- **M1** ingestion pipeline (done)
- **M2** retrieval + tutor answer (done)
- **M3** sessions + last-N memory + metadata scoping (done)
- **M4** *(optional)* teaching-card generation at ingest
- **M5** *(later)* STT/TTS voice loop