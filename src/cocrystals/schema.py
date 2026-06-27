"""Структуры данных и порядок колонок для домена кокристаллов"""

from __future__ import annotations
from dataclasses import dataclass

# Порядок колонок в prediction.csv
OUTPUT_COLUMNS = [
    "pdf",
    "name_cocrystal",
    "ratio_cocrystal",
    "name_drug",
    "SMILES_drug",
    "name_coformer",
    "SMILES_coformer",
    "photostability_change",
]

@dataclass
class ArticleMetadata:
    """
    Метаданные статьи (не участвуют в метрике)
    """
    doi: str = ""
    title: str = ""
    publisher: str = ""
    year: str = ""
    pdf: str = ""


@dataclass
class ExtractedSample:
    """
    Кокристалл как его возвращает LLM
    """
    name_cocrystal: str = ""
    ratio_cocrystal: str = ""
    name_drug: str = ""
    name_coformer: str = ""
    photostability_change: str = ""


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
    photostability_change: str = ""

    def as_dict(self) -> dict[str, str]:
        """
        Преобразование строки в словарь столбец->строка
        """
        return {column: str(getattr(self, column, "") or "") for column in OUTPUT_COLUMNS}
