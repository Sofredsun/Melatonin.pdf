"""
Разрешаем имена на канонические SMILES + InChIKey

Имя разрешается через цепочку приоритетов (cache -> local catalog -> OPSIN -> PubChem);
что бы мы ни получили, оно затем валидируется и канонизируется RDKit. Мы намеренно никогда не позволяем LLM изобретать SMILES: структуры всегда берутся из химической базы данных или детерминированного парсера имён.
"""

from __future__ import annotations

import csv
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any
from rdkit import Chem, RDLogger
from rdkit.Chem import inchi

from .schema import CompoundResolution

RDLogger.DisableLog("rdApp.error")

EMPTY_VALUES = {"", "nan", "none", "null", "not_detected", "not detected"}
PREFERRED_IUPAC_BY_INCHIKEY = {
    # В статье Gold используется корректный IUPAC-синоним для carbamazepine.
    "FFGPTBGBLSHEPO-UHFFFAOYSA-N": "5H-dibenzo[b,f]azepine-5-carboxamide"
}
RESOLVER_QUERY_ALIASES = {
    # Формулировка из статьи; в PubChem стандартное тривиальное имя.
    "chrysanthemum acid": "chrysanthemic acid"
}


def default_catalog_path(project_root: Path, catalog_path: Path | None = None) -> Path:
    """
    Предпочитаем локальный каталог проекта; иначе используем встроенную таблицу ChemX.
    """
    if catalog_path is not None:
        return catalog_path
    candidates = [
        project_root / "data" / "catalog.csv",
        project_root / "ChemX" / "datasets" / "Co-crystals.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def clean_text(value: str | None) -> str:
    """
    Нормализуем текст
    """
    if value is None:
        return ""
    value = unicodedata.normalize("NFKC", str(value))
    value = value.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    value = re.sub(r"\s+", " ", value).strip()
    return "" if value.lower() in EMPTY_VALUES else value


# Убираем аббревиатуру в скобках, например "Carbamazepine (CBZ)" -> "Carbamazepine"
_ALIAS_SUFFIX_RE = re.compile(r"\s*\([A-Z][A-Z0-9\-]{0,9}\)\s*$")


def strip_alias_suffix(name: str | None) -> str:
    """Убираем аббревиатуру в скобках, например "Carbamazepine (CBZ)"

    LLM часто повторяет аббревиатуру в имени, которое химические резолверы не могут найти.
    Возвращаем исходное имя если после удаления аббревиатуры останется пустая строка.
    """
    name = clean_text(name)
    if not name:
        return ""
    stripped = _ALIAS_SUFFIX_RE.sub("", name).strip()
    return stripped or name


def lookup_key(value: str | None) -> str:
    """Создаем нормализованный ключ для сопоставления/дедупликации имен между источниками"""
    value = clean_text(value).lower()
    value = value.replace("′", "'").replace("`", "'")
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .,:;")


def canonicalize_smiles(smiles: str | None) -> tuple[str, str]:
    """Валидируем и канонизируем SMILES через RDKit.

    Возвращаем canonical_smiles, inchikey, или "", "" если SMILES пустой или RDKit не может его распарсить
    InChIKey используется для сравнения структур, поэтому структуры равны даже если представление различается
    """
    smiles = clean_text(smiles)
    if not smiles:
        return "", ""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return "", ""
    return Chem.MolToSmiles(mol), inchi.MolToInchiKey(mol)


class CompoundResolver:
    """
    Разрешаем имена на структуры, кешируем результаты чтобы избежать повторных запросов.
    Источники пробуются в порядке стоимости/надежности: кеш в памяти, локальный CSV каталог, OPSIN, затем PubChem
    """

    def __init__(self, project_root: Path, cache_path: Path | None = None, catalog_path: Path | None = None, allow_pubchem: bool = True, allow_opsin: bool = True) -> None:
        """
        Инициализируем резолвер
        """
        self.project_root = project_root
        self.cache_path = cache_path or project_root / ".cache" / "compound_resolver.json"
        self.catalog_path = default_catalog_path(project_root, catalog_path)
        self.allow_pubchem = allow_pubchem
        self.allow_opsin = allow_opsin
        self.cache: dict[str, dict[str, Any]] = self._load_cache()
        self.catalog = self._load_catalog()

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        """Загружаем кеш из файла"""
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def save_cache(self) -> None:
        """Сохраняем кеш в файл"""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8"
        )

    def _load_catalog(self) -> dict[str, CompoundResolution]:
        """Загружаем локальный каталог имя->SMILES (для обоих колонок drug и coformer)

        Только строки с именем и RDKit-parseable SMILES сохраняются; первое вхождение каждого имени побеждает
        """
        catalog: dict[str, CompoundResolution] = {}
        if not self.catalog_path.exists():
            return catalog
        with self.catalog_path.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for name_col, smiles_col in (
                    ("name_drug", "SMILES_drug"),
                    ("name_coformer", "SMILES_coformer")
                ):
                    name = clean_text(row.get(name_col))
                    smiles, inchikey = canonicalize_smiles(row.get(smiles_col))
                    if not name or not smiles:
                        continue
                    key = lookup_key(name)
                    catalog.setdefault(
                        key,
                        CompoundResolution(
                            query=name,
                            name=name,
                            smiles=smiles,
                            inchikey=inchikey,
                            source=str(self.catalog_path)
                        )
                    )
        return catalog

    def resolve(self, name: str, *, prefer_iupac_name: bool = False) -> CompoundResolution:
        """
        Резолвим одно имя на ``CompoundResolution``.
        Устанавливаем prefer_iupac_name для поля drug: возвращаемое name это
        IUPAC имя (из PubChem или переопределение) вместо исходного имени.
        Результат кешируется по нормализованному ключу.
        """
        name = clean_text(name)
        if not name:
            return CompoundResolution(query="")

        query_name = name
        name = RESOLVER_QUERY_ALIASES.get(lookup_key(name), name)
        key = lookup_key(name)
        cached = self.cache.get(key)
        if cached:
            resolution = CompoundResolution(query=query_name, **cached)
            return self._finalize_name(resolution, prefer_iupac_name)

        local = self.catalog.get(key)
        if local:
            resolution = CompoundResolution(
                query=query_name,
                name=local.name,
                smiles=local.smiles,
                inchikey=local.inchikey,
                source=local.source
            )
            # Каталог имеет структуру, но не IUPAC имя; для поля drug запрашиваем IUPAC имя из PubChem, только если оно совпадает с структурой
            if prefer_iupac_name and self.allow_pubchem:
                enriched = self._resolve_pubchem(name)
                if enriched.smiles and enriched.inchikey == resolution.inchikey:
                    resolution.name = enriched.name or resolution.name
                    resolution.source = f"{resolution.source}+PubChem"
            resolution = self._finalize_name(resolution, prefer_iupac_name)
            self._remember(key, resolution)
            return resolution

        resolution = self._resolve_opsin(name)
        if not resolution.smiles and self.allow_pubchem:
            resolution = self._resolve_pubchem(name)
        if not resolution.smiles:
            resolution = self._resolve_cactus(name)
        resolution.query = query_name

        resolution = self._finalize_name(resolution, prefer_iupac_name)
        self._remember(key, resolution)
        return resolution

    def _remember(self, key: str, resolution: CompoundResolution) -> None:
        """
        Сохраняем результат в кеш в памяти
        """
        self.cache[key] = {
            "name": resolution.name,
            "smiles": resolution.smiles,
            "inchikey": resolution.inchikey,
            "source": resolution.source
        }

    def _resolve_opsin(self, name: str) -> CompoundResolution:
        """Резолвим систематическое/IUPAC имя offline через OPSIN (нужно Java).

        Возвращаем пустой результат если OPSIN недоступен или имя не является
        систематическим именем
        """
        if not self.allow_opsin:
            return CompoundResolution(query=name)
        # OPSIN работает на JVM; убеждаемся что Homebrew JDK на PATH если он есть
        openjdk_bin = Path("/usr/local/opt/openjdk/bin")
        if openjdk_bin.exists():
            os.environ["PATH"] = f"{openjdk_bin}:{os.environ.get('PATH', '')}"
        try:
            from py2opsin import py2opsin

            raw_smiles = clean_text(py2opsin(name))
        except Exception:
            return CompoundResolution(query=name)
        smiles, inchikey = canonicalize_smiles(raw_smiles)
        if not smiles:
            return CompoundResolution(query=name)
        return CompoundResolution(
            query=name,
            name=name,
            smiles=smiles,
            inchikey=inchikey,
            source="OPSIN"
        )

    def _resolve_pubchem(self, name: str) -> CompoundResolution:
        """Резолвим тривиальное имя через PubChem

        Возвращает IUPAC имя из PubChem
        """
        try:
            import pubchempy as pcp

            compounds = pcp.get_compounds(name, "name")
        except Exception:
            return CompoundResolution(query=name)
        for compound in compounds:
            raw_smiles = (
                getattr(compound, "canonical_smiles", "")
                or getattr(compound, "connectivity_smiles", "")
                or getattr(compound, "isomeric_smiles", "")
            )
            smiles, inchikey = canonicalize_smiles(raw_smiles)
            if smiles:
                return CompoundResolution(
                    query=name,
                    name=clean_text(getattr(compound, "iupac_name", "")) or name,
                    smiles=smiles,
                    inchikey=inchikey,
                    source="PubChem"
                )
        return CompoundResolution(query=name)

    def _resolve_cactus(self, name: str) -> CompoundResolution:
        """Резолвим IUPAC-имя через NCI Cactus Chemical Identifier Resolver.

        Хорошо справляется с систематическими IUPAC-именами, которых нет в PubChem.
        Пробуем несколько нормализованных вариантов имени если первый не даёт результата.
        """
        import ssl
        import urllib.request
        import urllib.parse

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        def _fetch_smiles(query: str) -> str:
            try:
                encoded = urllib.parse.quote(query, safe="")
                url = f"https://cactus.nci.nih.gov/chemical/structure/{encoded}/smiles"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                    return resp.read().decode("utf-8").strip()
            except Exception:
                return ""

        # Собираем небольшой набор вариантов имени для перебора по порядку
        variants = [name]
        # Убираем пробел между закрывающей скобкой и следующим словом (артефакт PDF):
        # например "-5-yl) methyl" → "-5-yl)methyl"
        v = re.sub(r"\)\s+(?=[a-z])", ")", name)
        if v != name:
            variants.append(v)
        # Исправляем типичную OCR/копипаст-опечатку: "morpholinpyridin" → "morpholinopyridin"
        for base in list(variants):
            fixed = base.replace("morpholinpyridin", "morpholinopyridin")
            if fixed != base:
                variants.append(fixed)

        for variant in variants:
            raw = _fetch_smiles(variant)
            smiles, inchikey = canonicalize_smiles(raw)
            if smiles:
                return CompoundResolution(
                    query=name,
                    name=variant,
                    smiles=smiles,
                    inchikey=inchikey,
                    source="Cactus"
                )
        return CompoundResolution(query=name)

    def _finalize_name(self, resolution: CompoundResolution, prefer_iupac_name: bool) -> CompoundResolution:
        """Применяем переопределения IUPAC"""
        if prefer_iupac_name and resolution.inchikey in PREFERRED_IUPAC_BY_INCHIKEY:
            resolution.name = PREFERRED_IUPAC_BY_INCHIKEY[resolution.inchikey]
        elif not resolution.name:
            resolution.name = resolution.query
        return resolution
