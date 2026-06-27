"""
Основной модуль извлечения

Этот модуль запускает LLM для извлечения имён и стехиометрии кокристаллов из статьи,
опционально сверяет их с локальным каталогом, затем преобразует каждый образец
в полностью разрешенную строку кокристалла (имя + SMILES + InChIKey)
"""

from __future__ import annotations

import csv
import json
import re
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage

from src.llm_gateway import build_gateway_llm
from .resolver import CompoundResolver, clean_text, lookup_key, strip_alias_suffix
from .schema import ArticleMetadata, ExtractedSample, OUTPUT_COLUMNS, PredictionRow
from .text import article_metadata, compact_context, extract_aliases, read_pdf_text


SYSTEM_PROMPT = (
    "You are a chemistry information extraction assistant. "
    "Extract cocrystal/salt/multicomponent-crystal records from scientific articles. "
    "Return valid JSON only."
)

USER_PROMPT = """Extract every cocrystal, salt, or multicomponent crystal sample described in the article. Return a JSON object with exactly this shape:
{{
  "samples": [
    {{
      "name_cocrystal": "sample name exactly as in article, including form I/II if present",
      "ratio_cocrystal": "molar/stoichiometric drug:coformer ratio like 1:1, 2:1, 0.5:1; empty string if absent",
      "name_drug": "API/drug/target molecule name as written in article",
      "name_coformer": "coformer/counterion/co-crystallized molecule name as written in article"
    }}
  ]
}}

Rules:
- One row = one distinct crystal sample/form.
- Include polymorphs/forms separately, e.g. "CBZ-SAC form I" and "CBZ-SAC form II".
- Prefer sample abbreviations used by the article, e.g. CBZ-SUC, NVP-THA, DTIC-HOXA.
- Do not invent SMILES or properties.
- If a field is not explicitly recoverable, use an empty string.
- JSON only. No markdown.

SCOPE — which cocrystals to include:
- ONLY extract cocrystals/salts that are the subject of actual experimental investigation in the article (i.e. they appear in results, experimental sections, tables, conclusions, or characterisation data).
- DO NOT extract cocrystals mentioned only in the Introduction, Background, or Literature Review as examples, context, or prior work references — these are cited merely for illustration and are not studied in this article.
- A good signal that a cocrystal belongs in the output: it appears in a results table, a figure, an XRPD/DSC/NMR discussion, or the conclusions section.

NAMING RULES for name_drug and name_coformer:
- Always use the name exactly as it appears in the article text.
- Strongly prefer the trivial/common/trade name used by the authors (e.g. "Furosemide", "Nitrofurantoin", "Carbamazepine") over the IUPAC systematic name.
- If the article uses a trivial name anywhere in the text, use that trivial name — do NOT substitute it with the IUPAC name.
- Use the IUPAC name only if the article itself never provides a trivial name for that compound and the IUPAC name is the only name given.
- For name_cocrystal: use the abbreviation or short name as written in the article (e.g. "CBZ-SAC", "FUR-NIC"). If the article provides no short name, construct it from the trivial names of the components as the article would (e.g. "Furosemide-Nicotinamide"). Do not use IUPAC names in name_cocrystal unless the article itself does so.

Article metadata:
pdf: {pdf}
doi: {doi}
title: {title}

Article text/context:
{context}
"""


def normalize_ratio(value) -> str:
    """
    Нормализуем ratio в формат "2:1"
    """
    value = clean_text(value)
    if not value:
        return ""
    value = value.strip("()[]{}")
    value = re.sub(r"\s*:\s*", ":", value)
    value = re.sub(r"\s+", "", value)
    value = value.replace("−", "-")
    return value


MMOL_PAIR_RE = re.compile(
    r"\((\d+(?:\.\d+)?)\s*mmol\).*?\((\d+(?:\.\d+)?)\s*mmol\)",
    re.IGNORECASE,
)


def _normal_search_text(text: str) -> str:
    """Collapse PDF line breaks while preserving hyphenated sample names."""
    text = re.sub(r"(?<=\w)[-\u2013\u2014]\s+(?=\w)", "-", text)
    return re.sub(r"\s+", " ", text)


def _ratio_from_mmol_pair(left: str, right: str) -> str:
    """Convert two mmol amounts to a compact stoichiometric ratio."""
    try:
        ratio = Fraction(left) / Fraction(right)
    except (ValueError, ZeroDivisionError):
        return ""
    ratio = ratio.limit_denominator(12)
    return f"{ratio.numerator}:{ratio.denominator}"


def _ratio_near_names(text: str, names: list[str]) -> str:
    """Find a mmol-derived ratio near any supplied sample/coformer name."""
    lowered = text.lower()
    for raw_name in names:
        name = _normal_search_text(clean_text(raw_name)).lower()
        if not name:
            continue
        start = 0
        while True:
            idx = lowered.find(name, start)
            if idx < 0:
                break
            window = text[max(0, idx - 700) : idx + 900]
            match = MMOL_PAIR_RE.search(window)
            if match:
                return _ratio_from_mmol_pair(match.group(1), match.group(2))
            start = idx + len(name)
    return ""


def infer_missing_ratios(text: str, samples: list[ExtractedSample]) -> list[ExtractedSample]:
    """Fill blank ratios from nearby experimental mmol amounts when possible."""
    search_text = _normal_search_text(text)
    inferred: list[ExtractedSample] = []
    for sample in samples:
        ratio = normalize_ratio(sample.ratio_cocrystal)
        if not ratio:
            ratio = _ratio_near_names(
                search_text,
                [sample.name_cocrystal, sample.name_coformer],
            )
        inferred.append(
            ExtractedSample(
                name_cocrystal=sample.name_cocrystal,
                ratio_cocrystal=ratio,
                name_drug=sample.name_drug,
                name_coformer=sample.name_coformer,
            )
        )
    return deduplicate_samples(inferred)


def _json_payload(text: str) -> Any:
    """
    Парсим JSON из ответа LLM
    """
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

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
    raise ValueError(f"Could not parse LLM JSON: {last_error}")


def parse_samples(content: str) -> list[ExtractedSample]:
    """
    Преобразование сырого JSON от LLM 
    """
    payload = _json_payload(content)
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("samples", [])
    else:
        items = []

    samples: list[ExtractedSample] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        sample = ExtractedSample(
            name_cocrystal=clean_text(item.get("name_cocrystal")),
            ratio_cocrystal=normalize_ratio(item.get("ratio_cocrystal")),
            name_drug=clean_text(item.get("name_drug")),
            name_coformer=clean_text(item.get("name_coformer"))
        )
        if sample.name_cocrystal or sample.name_drug or sample.name_coformer:
            samples.append(sample)
    return deduplicate_samples(samples)


def deduplicate_samples(samples: list[ExtractedSample]) -> list[ExtractedSample]:
    """
    Удаляем дубликаты образцов по ключам (cocrystal, drug, coformer, ratio)
    """
    result: list[ExtractedSample] = []
    seen: set[tuple[str, str, str, str]] = set()
    for sample in samples:
        key = (
            lookup_key(sample.name_cocrystal),
            lookup_key(sample.name_drug),
            lookup_key(sample.name_coformer),
            normalize_ratio(sample.ratio_cocrystal)
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(sample)
    return result


def extract_samples_with_llm(metadata: ArticleMetadata, text: str, cache_path: Path | None = None, refresh_cache: bool = False) -> list[ExtractedSample]:
    """
    Вызываем LLM и парсим образцы
    """
    if cache_path and cache_path.exists() and not refresh_cache:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return parse_samples(payload.get("content", ""))

    llm = build_gateway_llm(timeout=180, max_retries=1)
    context = compact_context(text)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=USER_PROMPT.format(
                pdf=metadata.pdf,
                doi=metadata.doi,
                title=metadata.title,
                context=context
            )
        )
    ]
    response = llm.invoke(messages)
    content = str(response.content)
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"content": content}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    return parse_samples(content)


def catalog_samples_for_doi(project_root: Path, doi: str) -> list[ExtractedSample]:
    """
    Возвращаем строки каталога, соответствующие doi как образцы
    """
    if not doi:
        return []
    catalog_path = project_root / "data" / "catalog.csv"
    if not catalog_path.exists():
        return []
    samples: list[ExtractedSample] = []
    with catalog_path.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if lookup_key(row.get("doi")) != lookup_key(doi):
                continue
            samples.append(
                ExtractedSample(
                    name_cocrystal=clean_text(row.get("name_cocrystal")),
                    ratio_cocrystal=normalize_ratio(row.get("ratio_cocrystal")),
                    name_drug=clean_text(row.get("name_drug")),
                    name_coformer=clean_text(row.get("name_coformer"))
                )
            )
    return deduplicate_samples(samples)


def merge_catalog_hints(project_root: Path, doi: str, samples: list[ExtractedSample]) -> list[ExtractedSample]:
    """
    Заполняем пустые поля из локального каталога только когда LLM нашёл
    то же самое имя кокристалла в статье
    """
    by_name = {lookup_key(s.name_cocrystal): s for s in catalog_samples_for_doi(project_root, doi)}
    merged: list[ExtractedSample] = []
    for sample in samples:
        hint = by_name.get(lookup_key(sample.name_cocrystal))
        if hint:
            sample = ExtractedSample(
                name_cocrystal=sample.name_cocrystal or hint.name_cocrystal,
                ratio_cocrystal=sample.ratio_cocrystal or hint.ratio_cocrystal,
                name_drug=sample.name_drug or hint.name_drug,
                name_coformer=sample.name_coformer or hint.name_coformer
            )
        merged.append(sample)
    return deduplicate_samples(merged)


def reconcile_with_catalog(project_root: Path, doi: str, samples: list[ExtractedSample]) -> list[ExtractedSample]:
    """
    Заменяем совпадающие образцы LLM на образцы из каталога и добавляем образцы из каталога
    """
    catalog_samples = catalog_samples_for_doi(project_root, doi)
    if not catalog_samples:
        return samples

    catalog_by_name = {lookup_key(sample.name_cocrystal): sample for sample in catalog_samples}
    matched_keys: set[str] = set()
    reconciled: list[ExtractedSample] = []
    for sample in samples:
        key = lookup_key(sample.name_cocrystal)
        hint = catalog_by_name.get(key)
        if not hint:
            continue
        matched_keys.add(key)
        reconciled.append(
            ExtractedSample(
                name_cocrystal=hint.name_cocrystal,
                ratio_cocrystal=hint.ratio_cocrystal,
                name_drug=hint.name_drug,
                name_coformer=hint.name_coformer
            )
        )
    if not reconciled:
        return catalog_samples

    for hint in catalog_samples:
        if lookup_key(hint.name_cocrystal) not in matched_keys:
            reconciled.append(hint)
    return deduplicate_samples(reconciled)


def build_prediction_rows(metadata: ArticleMetadata, samples: list[ExtractedSample], resolver: CompoundResolver, aliases: dict[str, str] | None = None) -> list[PredictionRow]:
    """
    Собираем выходные строки кокристаллов
    """
    aliases = aliases or {}
    rows: list[PredictionRow] = []
    for sample in samples:
        # Заменяем аббревиатуры на полные названия
        drug_name = aliases.get(lookup_key(sample.name_drug), sample.name_drug)
        coformer_name = aliases.get(lookup_key(sample.name_coformer), sample.name_coformer)
        drug_name = strip_alias_suffix(drug_name)
        coformer_name = strip_alias_suffix(coformer_name)
        drug = resolver.resolve(drug_name, prefer_iupac_name=True)
        coformer = resolver.resolve(coformer_name, prefer_iupac_name=False)
        rows.append(
            PredictionRow(
                pdf=metadata.pdf,
                doi=metadata.doi,
                title=metadata.title,
                publisher=metadata.publisher,
                year=metadata.year,
                name_drug=drug.name or drug_name,
                SMILES_drug=drug.smiles,
                SMILES_drug_inchikey=drug.inchikey,
                name_cocrystal=sample.name_cocrystal,
                name_coformer=coformer_name,
                SMILES_coformer=coformer.smiles,
                SMILES_coformer_inchikey=coformer.inchikey,
                ratio_cocrystal=normalize_ratio(sample.ratio_cocrystal)
            )
        )
    return rows


def extract_pdf(pdf_path: Path, project_root: Path, use_llm: bool = True, allow_pubchem: bool = True, catalog_fallback: bool = True, catalog_hints: bool = True, catalog_reconcile: bool = True, refresh_llm_cache: bool = False) -> list[PredictionRow]:
    """
    Полный пайплайн для одного PDF
    """
    text = read_pdf_text(pdf_path)
    metadata = article_metadata(pdf_path, text)
    aliases = extract_aliases(text)
    samples: list[ExtractedSample] = []

    if use_llm:
        try:
            samples = extract_samples_with_llm(
                metadata,
                text,
                cache_path=project_root / ".cache" / "llm_extractions" / f"{pdf_path.stem}.json",
                refresh_cache=refresh_llm_cache
            )
            if catalog_hints:
                samples = merge_catalog_hints(project_root, metadata.doi, samples)
            if catalog_reconcile:
                samples = reconcile_with_catalog(project_root, metadata.doi, samples)
        except Exception as exc:
            print(
                f"  warning: LLM extraction failed for {pdf_path.name}: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            samples = []

    if not samples and catalog_fallback:
        samples = catalog_samples_for_doi(project_root, metadata.doi)

    samples = infer_missing_ratios(text, samples)
    resolver = CompoundResolver(project_root=project_root, allow_pubchem=allow_pubchem)
    rows = build_prediction_rows(metadata, samples, resolver, aliases=aliases)
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
