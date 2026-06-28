"""
Основной модуль извлечения MIC/MBC для оксазолидинонов

Этот модуль запускает LLM для извлечения антибактериальных данных из таблиц статьи,
затем разрешает IUPAC-имена соединений в SMILES и формирует выходные строки prediction CSV.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm_gateway import build_gateway_llm
from src.cocrystals.resolver import CompoundResolver, clean_text, lookup_key, strip_alias_suffix
from src.cocrystals.text import article_metadata, read_pdf_text
from .schema import ArticleMetadata, ExtractedRecord, OUTPUT_COLUMNS, PredictionRow


SYSTEM_PROMPT = (
    "You are a chemistry and microbiology information extraction assistant. "
    "Extract antibacterial MIC/MBC activity data from scientific articles. "
    "Return valid JSON only."
)

USER_PROMPT = """Extract every antibacterial activity measurement from the tables in this article.
Return a JSON object with exactly this shape:

{{
  "records": [
    {{
      "compound_id": "compound label as written in the table (e.g. '3a', '11b', '2', 'Linezolid')",
      "compound_name": "IUPAC or systematic name of the compound if explicitly stated in the paper text (empty string if not given)",
      "bacteria": "full bacteria name resolved from the table footnotes or column header (e.g. 'Bacillus subtilis MTCC 121', 'Staphylococcus aureus ATCC 25923')",
      "target_type": "MIC or MBC",
      "target_relation": "one of: =, >, <, >=, <=",
      "target_value": "numeric value as a string (e.g. '1.17', '125', '256')",
      "target_units": "units string (e.g. 'µg/mL')"
    }}
  ]
}}

Rules:
- Extract EVERY SINGLE CELL from EVERY antibacterial/antimicrobial MIC or MBC table. Do NOT skip rows, do NOT skip columns, do NOT only report notable values. Include all ">125", ">256", and every other value.
- Do NOT extract anthelmintic, cytotoxic or other non-antibacterial data.
- One record = one (compound_id, bacteria, target_type) triple. If a paper has a table with N compound rows and M bacteria columns, you must emit N × M records (for each target_type).
- When a table cell contains both an MIC value and a parenthesized MBC value like "1.17 (2.34)", emit TWO records: one for MIC=1.17 and one for MBC=2.34. The parenthesized number is MBC.
- When a value starts with ">", use target_relation=">" and target_value = the number without ">". Example: ">125" → relation=">", value="125".
- When a value has no prefix, use target_relation="=".
- Use the footnotes at the bottom of each table to resolve bacteria abbreviations to their full names (e.g. "B. s" → "Bacillus subtilis MTCC 121").
- For compound_name: only fill this if the article's experimental section explicitly gives an IUPAC/systematic name for that compound_id. Leave empty if the compound is only shown as a structural figure.
- Include reference/control compounds (e.g. Neomycin, Linezolid) with their full name as compound_id.
- JSON only. No markdown.

Article metadata:
pdf: {pdf}
doi: {doi}
title: {title}

Article text/context:
{context}
"""


def build_context(text: str, max_chars: int = 45000) -> str:
    """
    Возвращаем как можно больше текста статьи в пределах max_chars
    """
    return text[:max_chars]


def _json_payload(text: str) -> Any:
    """
    Парсим JSON из ответа LLM
    """
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    candidates = [text]
    obj_start, obj_end = text.find("{"), text.rfind("}")
    if obj_start >= 0 and obj_end > obj_start:
        candidates.append(text[obj_start: obj_end + 1])
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
    raise ValueError(f"Could not parse LLM JSON: {last_error}")


def parse_records(content: str) -> list[ExtractedRecord]:
    """
    Преобразование сырого JSON от LLM в список ExtractedRecord
    """
    payload = _json_payload(content)
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("records", [])
    else:
        items = []

    records: list[ExtractedRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rec = ExtractedRecord(
            compound_id=clean_text(item.get("compound_id")),
            compound_name=clean_text(item.get("compound_name")),
            bacteria=clean_text(item.get("bacteria")),
            target_type=clean_text(item.get("target_type")).upper() or "MIC",
            target_relation=_normalize_relation(item.get("target_relation")),
            target_value=clean_text(item.get("target_value")),
            target_units=clean_text(item.get("target_units")) or "µg/mL"
        )
        if rec.compound_id and rec.bacteria and rec.target_value:
            records.append(rec)
    return deduplicate_records(records)


def _normalize_relation(value: Any) -> str:
    """
    Приводим ответ LLM к одному из канонических операторов сравнения
    """
    v = clean_text(value)
    mapping = {">=": ">=", "<=": "<=", ">": ">", "<": "<", "=": "=", "==": "="}
    return mapping.get(v, "=")


def deduplicate_records(records: list[ExtractedRecord]) -> list[ExtractedRecord]:
    """
    Удаляем дубликаты по ключам (compound_id, bacteria, target_type)
    """
    result: list[ExtractedRecord] = []
    seen: set[tuple] = set()
    for rec in records:
        key = (
            lookup_key(rec.compound_id),
            lookup_key(rec.bacteria),
            rec.target_type.upper()
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(rec)
    return result


def extract_records_with_llm(
    metadata: ArticleMetadata,
    text: str,
    cache_path: Path | None = None,
    refresh_cache: bool = False
) -> list[ExtractedRecord]:
    """
    Вызываем LLM и парсим записи MIC/MBC
    """
    if cache_path and cache_path.exists() and not refresh_cache:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return parse_records(payload.get("content", ""))

    llm = build_gateway_llm(timeout=300, max_retries=1)
    context = build_context(text)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=USER_PROMPT.format(
                pdf=metadata.pdf,
                doi=metadata.doi,
                title=metadata.title,
                context=context
            )
        ),
    ]
    response = llm.invoke(messages)
    content = str(response.content)
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"content": content}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    return parse_records(content)


def build_prediction_rows(
    metadata: ArticleMetadata,
    records: list[ExtractedRecord],
    resolver: CompoundResolver,
) -> list[PredictionRow]:
    """
    Собираем выходные строки prediction CSV
    """
    resolved_cache: dict[str, str] = {}
    rows: list[PredictionRow] = []
    for rec in records:
        cid = rec.compound_id.strip()
        if cid not in resolved_cache:
            # Приоритет: явное IUPAC-имя от LLM, иначе compound_id
            # (работает для референсных препаратов типа Linezolid)
            name = rec.compound_name or cid
            resolution = resolver.resolve(strip_alias_suffix(name), prefer_iupac_name=False)
            resolved_cache[cid] = resolution.smiles
        rows.append(
            PredictionRow(
                pdf=metadata.pdf,
                doi=metadata.doi,
                compound_id=cid,
                smiles=resolved_cache[cid],
                target_type=rec.target_type,
                target_relation=rec.target_relation,
                target_value=rec.target_value,
                target_units=rec.target_units,
                bacteria=rec.bacteria
            )
        )
    return rows


def extract_pdf(
    pdf_path: Path,
    project_root: Path,
    use_llm: bool = True,
    allow_pubchem: bool = True,
    refresh_llm_cache: bool = False
) -> list[PredictionRow]:
    """
    Полный пайплайн для одного PDF
    """
    text = read_pdf_text(pdf_path)
    metadata_obj = article_metadata(pdf_path, text)
    # Приводим ArticleMetadata из cocrystals к локальному типу (поля совместимы)
    metadata = ArticleMetadata(
        doi=metadata_obj.doi,
        title=metadata_obj.title,
        publisher=metadata_obj.publisher,
        year=metadata_obj.year,
        pdf=metadata_obj.pdf
    )
    records: list[ExtractedRecord] = []

    if use_llm:
        try:
            records = extract_records_with_llm(
                metadata,
                text,
                cache_path=project_root / ".cache" / "llm_oxazolidinones" / f"{pdf_path.stem}.json",
                refresh_cache=refresh_llm_cache
            )
        except Exception as exc:
            print(
                f"  warning: LLM extraction failed for {pdf_path.name}: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True
            )
            records = []

    resolver = CompoundResolver(project_root=project_root, allow_pubchem=allow_pubchem)
    rows = build_prediction_rows(metadata, records, resolver)
    resolver.save_cache()
    return rows


def write_prediction_csv(rows: list[PredictionRow], out_path: Path) -> None:
    """Записываем строки в CSV файл"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_dict())
