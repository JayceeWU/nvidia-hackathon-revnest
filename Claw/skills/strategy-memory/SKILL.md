---
name: strategy-memory
description: Search RevNest pricing strategy memory with local sentence-transformers embeddings and pgvector. Use this skill for RevNest, Dream Inn, Airbnb pricing strategy, RMS data, revenue management, rate architecture, seasonality, booking-window, channel, promotion, package, and strategy questions.
---

# Strategy Memory

Use this skill for RevNest, Dream Inn, Airbnb pricing strategy, RMS data, revenue management, rate architecture, seasonality, booking-window, channel, promotion, package, and strategy questions.

## Required Retrieval Step

Always call `search_strategy_memory(query)` before answering.

## Grounding Rule

Answer strictly and only based on the provided context. If you cannot find the answer in the context, say you don't know.

## Answer Rules

- Use only chunks returned by `search_strategy_memory`.
- Cite concise source and section names from the returned chunks.
- If the tool returns no chunks, low-confidence chunks, or chunks that do not answer the question, answer: `I don't know.`
- Do not use prior knowledge, web results, or unsupported assumptions to fill gaps.

## Tool

`search_strategy_memory(query, top_k = 8)` returns:

```json
{
  "query": "user query",
  "expanded_query": "query used for embedding search",
  "chunks": [
    {
      "source": "document or dataset name",
      "section": "section heading",
      "score": 0.42,
      "content": "retrieved context",
      "metadata": {}
    }
  ]
}
```
