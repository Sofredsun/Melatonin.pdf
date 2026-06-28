"""Структуры данных и порядок колонок для домена оксазолидинонов (MIC/MBC)."""

from __future__ import annotations
from dataclasses import dataclass

# Порядок колонок в prediction CSV
OUTPUT_COLUMNS = [
    "pdf",
    "doi",
    "compound_id",
    "smiles",
    "target_type",
    "target_relation",
    "target_value",
    "target_units",
    "bacteria"
]


@dataclass
class ArticleMetadata:
    """
    Метаданные
    """
    doi: str = ""
    title: str = ""
    publisher: str = ""
    year: str = ""
    pdf: str = ""


@dataclass
class ExtractedRecord:
    """
    Одна строка MIC/MBC (соединение × бактерия), как её возвращает LLM
    """
    compound_id: str = ""
    compound_name: str = ""
    bacteria: str = ""
    target_type: str = ""
    target_relation: str = ""
    target_value: str = ""
    target_units: str = ""


@dataclass
class PredictionRow:
    """
    Одна полностью разрешённая выходная строка
    """
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
        """
        Преобразование строки в словарь столбец -> значение
        """
        return {column: str(getattr(self, column, "") or "") for column in OUTPUT_COLUMNS}
