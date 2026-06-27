"""Структуры данных и порядок колонок для домена кокристаллов"""

from __future__ import annotations
from dataclasses import dataclass

# Порядок колонок в prediction.csv
OUTPUT_COLUMNS = [
    "pdf",
    "doi",
    "title",
    "publisher",
    "year",
    "name_drug",
    "SMILES_drug",
    "SMILES_drug_inchikey",
    "name_cocrystal",
    "name_coformer",
    "SMILES_coformer",
    "SMILES_coformer_inchikey",
    "ratio_cocrystal"
]


@dataclass
class ArticleMetadata:
    """
    Метаданные статьи (не участвуют в метрике)
    """
    pdf: str
    doi: str = ""
    title: str = ""
    publisher: str = ""
    year: str = ""


@dataclass
class ExtractedSample:
    """
    Кокристалл как его возвращает LLM
    """
    name_cocrystal: str = ""
    ratio_cocrystal: str = ""
    name_drug: str = ""
    name_coformer: str = ""


@dataclass
class CompoundResolution:
    """
    Результат разрешения одного имени: канонический SMILES, InChIKey и его источник
    """

    query: str
    name: str = ""
    smiles: str = ""
    inchikey: str = ""
    source: str = ""


@dataclass
class PredictionRow:
    """
    Одна полностью разрешенная строка кокристалла
    """

    pdf: str = ""
    doi: str = ""
    title: str = ""
    publisher: str = ""
    year: str = ""
    name_drug: str = ""
    SMILES_drug: str = ""
    SMILES_drug_inchikey: str = ""
    name_cocrystal: str = ""
    name_coformer: str = ""
    SMILES_coformer: str = ""
    SMILES_coformer_inchikey: str = ""
    ratio_cocrystal: str = ""

    def as_dict(self) -> dict[str, str]:
        """
        Преобразование строки в словарь столбец->строка
        """
        return {column: str(getattr(self, column, "") or "") for column in OUTPUT_COLUMNS}
