"""
Основной модуль извлечения для домена бензимидазолов.

Этот модуль запускает LLM для извлечения антимикробных/антипролиферативных
измерений (compound_id x bacteria x target_type) из статьи, затем разрешает
SMILES для каждого compound_id — приоритетно через детерминированный
regex-парсер раздела characterization (text.extract_compound_names_by_id),
и только при его неудаче — через имя, которое процитировала LLM.
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
from .resolver import CompoundResolution, CompoundResolver, clean_text, lookup_key
from .schema import (
    ArticleMetadata,
    ExtractedMeasurement,
    OUTPUT_COLUMNS,
    PredictionRow,
    TARGET_RELATIONS,
)
from .text import (
    article_metadata,
    compact_context,
    extract_bacteria_aliases,
    extract_compound_names_by_id,
    extract_organism_mentions,
    read_pdf_text,
)


SYSTEM_PROMPT = (
    "You are a chemistry information extraction assistant. "
    "Extract antimicrobial/antiproliferative activity measurements for benzimidazole-"
    "containing compounds from scientific articles. Return valid JSON only."
)

USER_PROMPT = """Extract every quantitative antimicrobial/antiproliferative activity measurement reported for the article's own synthesized benzimidazole-containing compounds. Return a JSON object with exactly this shape:
{{
  "measurements": [
    {{
      "compound_id": "compound label exactly as used in the article's tables, e.g. 4a, 6c, 12h",
      "compound_name": "full systematic/IUPAC name of the compound if printed in the article; empty string if you are not certain",
      "target_type": "one of: MIC, IC50, GI50, LD50, zone_of_inhibition",
      "target_relation": "one of: =, >, <, >=, <=",
      "target_value": "the bare number only, no units, no operator, e.g. 32 or 1.95",
      "target_units": "unit exactly as printed, e.g. µg/mL, µM, mm, mol/kg",
      "bacteria": "full Latin binomial species name (Genus species), resolved from any table abbreviation using the assay description and organism hints given below"
    }}
  ]
}}

Rules:
- One row = one (compound, organism-or-cell-line, target_type) combination with one reported value.
- ONLY extract compounds that the article itself synthesized and tested (its own numbered series, e.g. 4a-4f, 6a-6f).
- DO NOT extract reference/standard drugs used only as positive controls (ciprofloxacin, fluconazole, ampicillin, gentamicin, doxorubicin, voriconazole, etc.).
- DO NOT extract compounds mentioned only as literature precedent/background from other authors' work, or compounds appearing only in a review-style table that cites a different source article.
- If a value has an inequality ("> 512", "< 0.97"), put the operator in target_relation and the bare number in target_value. If no operator is shown, target_relation is "=".
- If a table cell gives a range like "32-64" that you cannot confidently decompose into a single value + relation, skip that cell rather than inventing a number.
- If the target value is reported per cell line (e.g. IC50 against a cancer cell line, not a bacterium), still extract it and put the cell line name in "bacteria" exactly as named (e.g. "MCF-7", "HepG2") — this field is reused for any biological target named in the table/column header.
- Bacteria/organism names: tables in this domain often use short column-header codes (Bc, Sa, Ec, Pa, Ab, Ca, or "E. coli", "S. aureus"...) that are usually NOT explained right next to the table. Use the assay-description text and the organism hints below to match each code to its full species name, matching the same left-to-right / Gram-positive-then-Gram-negative-then-fungi order the codes appear in the table header.
- Do not invent SMILES, names, or values. If target_value, target_type, or bacteria cannot be determined confidently for a cell, omit that measurement entirely rather than guessing.
- JSON only. No markdown.

Abbreviation/organism hints found by a deterministic scan of this article (may be incomplete or in the wrong order — verify against the assay text below before using):
{bacteria_hints}

Article metadata:
pdf: {pdf}
doi: {doi}
title: {title}

Article text/context:
{context}
"""


_VALUE_WITH_RELATION_RE = re.compile(
    r"^\s*(?P<rel>>=|<=|≥|≤|>|<|=)?\s*(?P<val>\d+(?:\.\d+)?)\s*$"
)

_RELATION_ALIASES = {
    "≥": ">=",
    "≤": "<=",
    "greater than or equal to": ">=",
    "less than or equal to": "<=",
    "greater than": ">",
    "less than": "<",
    "equal to": "=",
    "equals": "=",
    "equal": "=",
}

_UNIT_ALIASES = {
    "ug/ml": "µg/mL",
    "μg/ml": "µg/mL",
    "mcg/ml": "µg/mL",
    "µg/ml": "µg/mL",
    "um": "µM",
    "μm": "µM",
    "mum": "µM",
    "µm": "µM",
    "mg/ml": "mg/mL",
}

_TYPE_ALIASES = {
    "minimum inhibitory concentration": "MIC",
    "minimum inhibitory concentration (mic)": "MIC",
    "mic": "MIC",
    "ic50": "IC50",
    "gi50": "GI50",
    "ld50": "LD50",
    "zone of inhibition": "zone_of_inhibition",
    "inhibition zone": "zone_of_inhibition",
    "inhibition zone diameter": "zone_of_inhibition",
    "diameter of inhibition zone": "zone_of_inhibition",
    "zone of inhibition diameter": "zone_of_inhibition",
}

# Детерминированный backstop на случай, если LLM всё же проигнорирует инструкцию
# не извлекать эталонные/референсные препараты (позитивные контроли) — этот
# набор почти всегда встречается в антимикробной/антипролиферативной литературе
# именно как стандарт, а не как тестируемое соединение этой статьи.
_REFERENCE_DRUG_DENYLIST = {
    "ciprofloxacin", "fluconazole", "ampicillin", "amoxicillin", "gentamicin",
    "gentamycin", "doxorubicin", "voriconazole", "chloramphenicol", "vancomycin",
    "azithromycin", "norfloxacin", "cephalothin", "streptomycin", "ketoconazole",
    "nystatin", "rifampicin", "isoniazid", "griseofulvin", "tetracycline",
    "cefazolin",
}


def normalize_relation(value: str) -> str:
    """Приводим оператор отношения к одному из TARGET_RELATIONS, по умолчанию '='."""
    value = clean_text(value).lower()
    if not value:
        return "="
    if value in TARGET_RELATIONS:
        return value
    return _RELATION_ALIASES.get(value, "=")


def normalize_units(value: str) -> str:
    """Нормализуем написание единиц измерения (ug/mL, μg/mL -> µg/mL и т.п.)."""
    value = clean_text(value)
    if not value:
        return ""
    key = value.lower().replace(" ", "")
    return _UNIT_ALIASES.get(key, value)


def normalize_target_type(value: str) -> str:
    """Приводим текстовое название величины к каноническому токену из TARGET_TYPES."""
    value = clean_text(value)
    if not value:
        return ""
    return _TYPE_ALIASES.get(value.lower(), value)


def split_relation_value(relation: str, value: str) -> tuple[str, str]:
    """Защитный парсинг: если LLM всё же приклеила оператор к target_value."""
    relation = clean_text(relation)
    value = clean_text(value)
    match = _VALUE_WITH_RELATION_RE.match(value)
    if match:
        embedded_rel = match.group("rel")
        bare_value = match.group("val")
        if embedded_rel and not relation:
            relation = embedded_rel
        return normalize_relation(relation), bare_value
    return normalize_relation(relation), value


def normalize_bacteria(value: str) -> str:
    """Срезаем висящий strain-код в скобках и приводим Genus species к стандартному капитализу.

    TODO: формат сверить с golden-датасетом на HF — неясно, ожидается ли strain
    код (ATCC ...) в составе значения поля bacteria, или только Genus species.
    """
    value = clean_text(value)
    if not value:
        return ""
    value = re.sub(r"\s*\([^()]{2,60}\)\s*$", "", value).strip()
    parts = value.split()
    if not parts:
        return ""
    parts[0] = parts[0][:1].upper() + parts[0][1:].lower()
    parts[1:] = [p.lower() for p in parts[1:]]
    return " ".join(parts)


def apply_bacteria_alias(value: str, aliases: dict[str, str]) -> str:
    """Если LLM вернула короткий код (он мог проскочить из таблицы как есть), разворачиваем его."""
    value = clean_text(value)
    if not value:
        return ""
    resolved = aliases.get(value.lower(), value)
    return normalize_bacteria(resolved)


def _salvage_json_objects(text: str) -> list[dict]:
    """Спасаем все ПОЛНЫЕ JSON-объекты-измерения из обрезанного/битого ответа LLM.

    Типичный случай: статья с большим числом измерений -> ответ обрезается по
    max_tokens на середине последнего объекта массива. Без этого fallback'а
    json.loads() падает на всём массиве и мы теряем 100% строк вместо одной.

    Объекты лежат на глубине 1 (внутри обёртки {"measurements": [...]}, а не на
    depth==0), поэтому используем стек позиций "{" вместо привязки к нулевой
    глубине: при каждом "}" пробуем распарсить как JSON именно тот фрагмент,
    который сейчас закрылся, независимо от уровня вложенности.
    """
    found: list[dict] = []
    stack: list[int] = []
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            stack.append(i)
        elif ch == "}":
            if not stack:
                continue
            start = stack.pop()
            try:
                obj = json.loads(text[start : i + 1])
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if "compound_id" in obj:
                found.append(obj)
            elif isinstance(obj.get("measurements"), list):
                found.extend(m for m in obj["measurements"] if isinstance(m, dict))

    # Дедуп на случай, если обёртка {"measurements": [...]} всё же закрылась
    # целиком — иначе её элементы попали бы в found дважды (и через "compound_id"
    # отдельно, и через распаковку "measurements").
    deduped: list[dict] = []
    seen: set[str] = set()
    for obj in found:
        key = json.dumps(obj, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(obj)
    return deduped


def _json_payload(text: str) -> Any:
    """Парсим JSON из ответа LLM."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()

    candidates = [text]
    obj_start = text.find("{")
    obj_end = text.rfind("}")
    if obj_start >= 0 and obj_end > obj_start:
        candidates.append(text[obj_start : obj_end + 1])
    arr_start = text.find("[")
    arr_end = text.rfind("]")
    if arr_start >= 0 and arr_end > arr_start:
        candidates.append(text[arr_start : arr_end + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    salvaged = _salvage_json_objects(text)
    if salvaged:
        print(
            f"  warning: LLM JSON was malformed/truncated, salvaged {len(salvaged)} complete object(s) "
            "out of an unknown total — consider raising max_tokens.",
            file=sys.stderr,
        )
        return salvaged
    raise ValueError("Could not parse LLM JSON and nothing salvageable")


def parse_measurements(content: str) -> list[ExtractedMeasurement]:
    """Преобразование сырого JSON от LLM в список измерений."""
    payload = _json_payload(content)
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("measurements", [])
    else:
        items = []

    measurements: list[ExtractedMeasurement] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        compound_id = clean_text(item.get("compound_id"))
        bacteria = clean_text(item.get("bacteria"))
        target_value_raw = clean_text(item.get("target_value"))
        if not compound_id or not bacteria or not target_value_raw:
            continue
        if lookup_key(compound_id) in _REFERENCE_DRUG_DENYLIST:
            continue
        relation, value = split_relation_value(str(item.get("target_relation", "")), target_value_raw)
        measurement = ExtractedMeasurement(
            compound_id=compound_id,
            compound_name=clean_text(item.get("compound_name")),
            target_type=normalize_target_type(str(item.get("target_type", ""))),
            target_relation=relation,
            target_value=value,
            target_units=normalize_units(str(item.get("target_units", ""))),
            bacteria=bacteria,
        )
        if measurement.target_type and measurement.target_value:
            measurements.append(measurement)
    return deduplicate_measurements(measurements)


def deduplicate_measurements(measurements: list[ExtractedMeasurement]) -> list[ExtractedMeasurement]:
    """Удаляем дубликаты измерений по ключу (compound_id, bacteria, target_type, value, units)."""
    result: list[ExtractedMeasurement] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for measurement in measurements:
        key = (
            lookup_key(measurement.compound_id),
            lookup_key(measurement.bacteria),
            lookup_key(measurement.target_type),
            measurement.target_relation,
            lookup_key(measurement.target_value),
            lookup_key(measurement.target_units),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(measurement)
    return result


def extract_measurements_with_llm(
    metadata: ArticleMetadata,
    text: str,
    bacteria_aliases: dict[str, str],
    organisms: list[str],
    cache_path: Path | None = None,
    refresh_cache: bool = False,
) -> list[ExtractedMeasurement]:
    """Вызываем LLM и парсим измерения."""
    if cache_path and cache_path.exists() and not refresh_cache:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return parse_measurements(payload.get("content", ""))

    llm = build_gateway_llm(timeout=180, max_retries=1)
    context = compact_context(text)

    hint_lines = [f"{abbr} -> {full}" for abbr, full in bacteria_aliases.items()]
    if organisms:
        hint_lines.append(
            "Organisms mentioned in the article, in order of first appearance: "
            + "; ".join(organisms[:40])
        )
    bacteria_hints = "\n".join(hint_lines) if hint_lines else "(none found by the deterministic scan)"

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=USER_PROMPT.format(
                pdf=metadata.pdf,
                doi=metadata.doi,
                title=metadata.title,
                context=context,
                bacteria_hints=bacteria_hints,
            )
        ),
    ]
    response = llm.invoke(messages)
    content = str(response.content)
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"content": content}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return parse_measurements(content)


def build_prediction_rows(
    metadata: ArticleMetadata,
    measurements: list[ExtractedMeasurement],
    resolver: CompoundResolver,
    compound_names_by_id: dict[str, str] | None = None,
) -> list[PredictionRow]:
    """Собираем выходные строки измерений, разрешая SMILES для каждого compound_id."""
    compound_names_by_id = compound_names_by_id or {}
    resolved_cache: dict[str, CompoundResolution] = {}
    rows: list[PredictionRow] = []
    for measurement in measurements:
        cid = measurement.compound_id.strip()
        if cid not in resolved_cache:
            # Детерминированное имя из characterization-секции имеет приоритет
            # над тем, что (возможно неточно) процитировала LLM.
            name = compound_names_by_id.get(cid) or measurement.compound_name
            resolved_cache[cid] = resolver.resolve_for_compound(name, doi=metadata.doi, compound_id=cid)
        resolution = resolved_cache[cid]
        rows.append(
            PredictionRow(
                pdf=metadata.pdf,
                doi=metadata.doi,
                compound_id=cid,
                smiles=resolution.smiles,
                target_type=measurement.target_type,
                target_relation=measurement.target_relation,
                target_value=measurement.target_value,
                target_units=measurement.target_units,
                bacteria=measurement.bacteria,
            )
        )
    return rows


def extract_pdf(
    pdf_path: Path,
    project_root: Path,
    use_llm: bool = True,
    allow_pubchem: bool = True,
    refresh_llm_cache: bool = False,
) -> list[PredictionRow]:
    """Полный пайплайн для одного PDF."""
    text = read_pdf_text(pdf_path)
    metadata = article_metadata(pdf_path, text)
    compound_names_by_id = extract_compound_names_by_id(text)
    bacteria_aliases = extract_bacteria_aliases(text)
    organisms = extract_organism_mentions(text)

    measurements: list[ExtractedMeasurement] = []
    if use_llm:
        try:
            measurements = extract_measurements_with_llm(
                metadata,
                text,
                bacteria_aliases=bacteria_aliases,
                organisms=organisms,
                cache_path=project_root / ".cache" / "llm_extractions" / f"{pdf_path.stem}.json",
                refresh_cache=refresh_llm_cache,
            )
        except Exception as exc:
            print(
                f"  warning: LLM extraction failed for {pdf_path.name}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            measurements = []

    # Финальная нормализация bacteria уже после LLM: на случай, если LLM всё же
    # вернула короткий код как есть, а не развёрнутое имя.
    measurements = [
        ExtractedMeasurement(
            compound_id=m.compound_id,
            compound_name=m.compound_name,
            target_type=m.target_type,
            target_relation=m.target_relation,
            target_value=m.target_value,
            target_units=m.target_units,
            bacteria=apply_bacteria_alias(m.bacteria, bacteria_aliases),
        )
        for m in measurements
    ]

    resolver = CompoundResolver(project_root=project_root, allow_pubchem=allow_pubchem)
    rows = build_prediction_rows(metadata, measurements, resolver, compound_names_by_id=compound_names_by_id)
    resolver.save_cache()
    return rows


def write_prediction_csv(rows: list[PredictionRow], out_path: Path) -> None:
    """Записываем строки в CSV файл."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_dict())