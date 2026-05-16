from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Iterable

from docx import Document
from pypdf import PdfReader

from strategy_memory import connect, content_hash, embed_texts, stable_id, vector_literal


@dataclass
class Chunk:
    source: str
    source_path: str
    section: str
    chunk_index: int
    content: str
    metadata: dict


HEADING_RE = re.compile(
    r"^(MODULE\s+\d+|(?:\d{1,2})(?:\.\d+)?[\.\s]+[A-Z][A-Za-z0-9 ,/&:'()\\-]+|[A-Z][A-Za-z ,/&\\-]+ Strategy)$"
)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def read_docx(path: Path) -> list[str]:
    doc = Document(path)
    return [normalize_text(p.text) for p in doc.paragraphs if normalize_text(p.text)]


def read_pdf(path: Path) -> list[str]:
    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if normalize_text(text):
            pages.append(normalize_text(text))
    return pages


def split_sections(paragraphs: list[str], default_section: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_title = default_section
    current: list[str] = []

    for para in paragraphs:
        is_heading = bool(HEADING_RE.match(para)) or para.upper() == para and 8 <= len(para) <= 120
        if is_heading and current:
            sections.append((current_title, current))
            current_title = para[:180]
            current = []
        elif is_heading:
            current_title = para[:180]
        else:
            current.append(para)

    if current:
        sections.append((current_title, current))
    return sections


def chunk_paragraphs(paragraphs: list[str], max_chars: int = 1800, overlap_chars: int = 250) -> list[str]:
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = current[-overlap_chars:] + "\n\n" + para
        else:
            for i in range(0, len(para), max_chars - overlap_chars):
                chunks.append(para[i : i + max_chars])
            current = ""
    if current:
        chunks.append(current)
    return chunks


def manual_chunks(path: Path, root: Path) -> Iterable[Chunk]:
    paragraphs = read_docx(path) if path.suffix.lower() == ".docx" else read_pdf(path)
    sections = split_sections(paragraphs, path.stem)
    chunk_index = 0
    for section, section_paragraphs in sections:
        for content in chunk_paragraphs(section_paragraphs):
            chunk_index += 1
            yield Chunk(
                source=path.name,
                source_path=str(path.relative_to(root)),
                section=section,
                chunk_index=chunk_index,
                content=content,
                metadata={"type": "strategy_manual", "extension": path.suffix.lower()},
            )


def text_chunks(path: Path, root: Path) -> Iterable[Chunk]:
    text = normalize_text(path.read_text(encoding="utf-8", errors="ignore"))
    if not text:
        return
    for index, content in enumerate(chunk_paragraphs([text], max_chars=1200), 1):
        yield Chunk(
            source=path.name,
            source_path=str(path.relative_to(root)),
            section=path.stem,
            chunk_index=index,
            content=content,
            metadata={"type": "text", "extension": path.suffix.lower()},
        )


def sql_chunks(path: Path, root: Path) -> Iterable[Chunk]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    statements = [normalize_text(part) for part in text.split(";") if normalize_text(part)]
    for index, content in enumerate(chunk_paragraphs(statements, max_chars=1600), 1):
        yield Chunk(
            source=path.name,
            source_path=str(path.relative_to(root)),
            section=f"SQL chunk {index}",
            chunk_index=index,
            content=content,
            metadata={"type": "sql"},
        )


def csv_small_chunks(path: Path, root: Path) -> Iterable[Chunk]:
    with path.open(newline="", encoding="utf-8", errors="ignore") as fh:
        rows = list(csv.DictReader(fh))
    lines = [", ".join(f"{key}: {value}" for key, value in row.items()) for row in rows]
    for index, content in enumerate(chunk_paragraphs(lines, max_chars=1600), 1):
        yield Chunk(
            source=path.name,
            source_path=str(path.relative_to(root)),
            section=f"CSV dictionary chunk {index}",
            chunk_index=index,
            content=content,
            metadata={"type": "csv_dictionary", "rows": len(rows)},
        )


def as_float(value: str) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except ValueError:
        return None


def rms_aggregate_chunks(path: Path, root: Path) -> Iterable[Chunk]:
    group_specs = [
        ("Room type strategy", ("room_type",)),
        ("Room type season strategy", ("room_type", "season")),
        ("Season demand strategy", ("season", "demand_level")),
        ("Event compression strategy", ("event_flag",)),
        ("Channel rate-plan strategy", ("channel", "rate_plan")),
        ("Market segment strategy", ("market_segment",)),
    ]
    groups: dict[tuple[str, tuple[str, ...], tuple[str, ...]], dict] = {}

    with path.open(newline="", encoding="utf-8", errors="ignore") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            for label, fields in group_specs:
                key_values = tuple(row.get(field, "") or "Unknown" for field in fields)
                key = (label, fields, key_values)
                item = groups.setdefault(
                    key,
                    {
                        "rows": 0,
                        "occupied": 0,
                        "prices": [],
                        "bars": [],
                        "discounts": [],
                        "targets": [],
                        "min_los": [],
                        "start": row.get("date"),
                        "end": row.get("date"),
                    },
                )
                item["rows"] += 1
                if row.get("stay_status") == "occupied":
                    item["occupied"] += 1
                for target, source in (
                    ("prices", "price"),
                    ("bars", "bar_rate"),
                    ("discounts", "discount_rate"),
                    ("targets", "simulated_target_occupancy_pct"),
                    ("min_los", "min_los"),
                ):
                    value = as_float(row.get(source, ""))
                    if value is not None:
                        item[target].append(value)
                item["start"] = min(item["start"], row.get("date") or item["start"])
                item["end"] = max(item["end"], row.get("date") or item["end"])

    for index, ((label, fields, values), item) in enumerate(groups.items(), 1):
        name = ", ".join(f"{field}={value}" for field, value in zip(fields, values))
        rows = item["rows"]
        occupied_pct = (item["occupied"] / rows * 100) if rows else 0
        avg_price = mean(item["prices"]) if item["prices"] else 0
        avg_bar = mean(item["bars"]) if item["bars"] else 0
        avg_discount = mean(item["discounts"]) if item["discounts"] else 0
        avg_target = mean(item["targets"]) if item["targets"] else 0
        avg_min_los = mean(item["min_los"]) if item["min_los"] else 0
        content = (
            f"Dream Inn Santa Cruz RMS aggregate for {label}: {name}. "
            f"Date range {item['start']} to {item['end']}. Rows {rows}; occupied share {occupied_pct:.1f}%; "
            f"average final price ${avg_price:.2f}; average BAR ${avg_bar:.2f}; "
            f"average discount {avg_discount:.3f}; average simulated target occupancy {avg_target:.1f}%; "
            f"average minimum length of stay {avg_min_los:.2f}. "
            "Use this aggregate as supporting context for pricing strategy, rate fences, seasonality, demand, channel, and revenue-management decisions."
        )
        yield Chunk(
            source=path.name,
            source_path=str(path.relative_to(root)),
            section=f"{label}: {name}",
            chunk_index=index,
            content=content,
            metadata={"type": "rms_aggregate", "group": label, "fields": list(fields), "values": list(values)},
        )


def collect_chunks(root: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".pdf" and path.with_suffix(".docx").exists():
            continue
        if suffix == ".docx" or suffix == ".pdf":
            chunks.extend(manual_chunks(path, root))
        elif suffix == ".txt":
            chunks.extend(text_chunks(path, root))
        elif suffix == ".sql":
            chunks.extend(sql_chunks(path, root))
        elif suffix == ".csv" and path.stat().st_size > 5_000_000:
            chunks.extend(rms_aggregate_chunks(path, root))
        elif suffix == ".csv":
            chunks.extend(csv_small_chunks(path, root))
    return chunks


def setup_schema(conn) -> None:
    schema_path = Path(__file__).with_name("schema.sql")
    with conn.cursor() as cur:
        cur.execute(schema_path.read_text(encoding="utf-8"))
    conn.commit()


def ingest(root: Path, reset: bool = True) -> dict:
    chunks = collect_chunks(root)
    if not chunks:
        raise RuntimeError(f"No chunks collected from {root}")

    with connect() as conn:
        setup_schema(conn)
        with conn.cursor() as cur:
            if reset:
                cur.execute("TRUNCATE strategy_memory_chunks")
        conn.commit()

        batch_size = 32
        inserted = 0
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vectors = embed_texts([chunk.content for chunk in batch])
            rows = []
            for chunk, vector in zip(batch, vectors):
                digest = content_hash(chunk.content)
                rows.append(
                    (
                        stable_id(chunk.source_path, chunk.section, str(chunk.chunk_index), digest),
                        chunk.source,
                        chunk.source_path,
                        chunk.section,
                        chunk.chunk_index,
                        chunk.content,
                        json.dumps(chunk.metadata),
                        digest,
                        vector_literal(vector),
                    )
                )
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO strategy_memory_chunks
                      (id, source, source_path, section, chunk_index, content, metadata, content_sha256, embedding)
                    VALUES
                      (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::vector)
                    ON CONFLICT (id) DO UPDATE SET
                      source = EXCLUDED.source,
                      source_path = EXCLUDED.source_path,
                      section = EXCLUDED.section,
                      chunk_index = EXCLUDED.chunk_index,
                      content = EXCLUDED.content,
                      metadata = EXCLUDED.metadata,
                      content_sha256 = EXCLUDED.content_sha256,
                      embedding = EXCLUDED.embedding,
                      updated_at = now()
                    """,
                    rows,
                )
            conn.commit()
            inserted += len(rows)

    return {"root": str(root), "chunks": len(chunks), "inserted": inserted}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest RevNest strategy memory into pgvector.")
    parser.add_argument("--data-dir", default="/sandbox/.openclaw/workspace/revnest/claw/data")
    parser.add_argument("--no-reset", action="store_true")
    args = parser.parse_args()
    result = ingest(Path(args.data_dir).expanduser().resolve(), reset=not args.no_reset)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
