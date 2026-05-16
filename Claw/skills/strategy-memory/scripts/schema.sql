CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS strategy_memory_chunks (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  source_path TEXT NOT NULL,
  section TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  content_sha256 TEXT NOT NULL,
  embedding vector(384) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS strategy_memory_chunks_source_idx
  ON strategy_memory_chunks (source);

CREATE INDEX IF NOT EXISTS strategy_memory_chunks_section_idx
  ON strategy_memory_chunks (section);

CREATE INDEX IF NOT EXISTS strategy_memory_chunks_metadata_gin_idx
  ON strategy_memory_chunks USING gin (metadata);

CREATE INDEX IF NOT EXISTS strategy_memory_chunks_embedding_hnsw_idx
  ON strategy_memory_chunks USING hnsw (embedding vector_cosine_ops);
