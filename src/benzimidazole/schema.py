"""Структуры данных и порядок колонок для домена бензимидазолов (антимикробная активность)."""

from __future__ import annotations
from dataclasses import dataclass

OUTPUT_COLUMNS = [
    "pdf",
    "doi",
    "compound_id",
    "smiles",
    "target_type",
    "target_relation",
    "target_value",
    "target_value",
    "target_units",
    "bacteria",
]

# Допустимые типы измеряемой величины
TARGET_TYPES = {"MIC", "pMIC"}

# Допустимые операторы отношения значение/порог.
TARGET_RELATIONS = {"=", ">", "<", ">=", "<="}


@dataclass
class ArticleMetadata:
    """Метаданные статьи (из колонок метрики участвует только doi)."""

    doi: str = ""
    title: str = ""
    publisher: str = ""
    year: str = ""
    pdf: str = ""


@dataclass
class ExtractedMeasurement:
    """Одно измерение (соединение x бактерия/клеточная линия x тип величины), как его вернула LLM."""

    compound_id: str = ""
    compound_name: str = ""
    target_type: str = ""
    target_relation: str = ""
    target_value: str = ""
    target_units: str = ""
    bacteria: str = ""


@dataclass
class CompoundResolution:
    """Результат разрешения одного имени: канонический SMILES, InChIKey и источник."""

    query: str
    name: str = ""
    smiles: str = ""
    inchikey: str = ""
    source: str = ""


@dataclass
class PredictionRow:
    """Одна полностью разрешённая строка измерения."""

    pdf: str = ""
    doi: str = ""
    compound_id: str = ""
    smiles: str = ""
    target_type: str = ""
    target_relation: str = ""
    target_value: str = ""
    target_units: str = ""
    bacteria: str = ""

    def as_dict(self) -> dict[str, str]:
        """Преобразование строки в словарь столбец->строка."""
        return {column: str(getattr(self, column, "") or "") for column in OUTPUT_COLUMNS}
