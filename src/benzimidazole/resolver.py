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

RESOLVER_QUERY_ALIASES: dict[str, str] = {}

_SALT_SUFFIXES = (
    " hydrochloride", " hydrobromide", " hydroiodide", " bromide", " chloride",
    " iodide", " sulfate", " acetate", " trifluoroacetate", " hydrate",
)


def default_catalog_path(project_root: Path, catalog_path: Path | None = None) -> Path:
    """Используем проектный каталог data/catalog.csv, если он есть."""
    if catalog_path is not None:
        return catalog_path
    return project_root / "data" / "catalog.csv"


def clean_text(value: str | None) -> str:
    """Нормализуем текст."""
    if value is None:
        return ""
    value = unicodedata.normalize("NFKC", str(value))
    value = value.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    value = re.sub(r"\s+", " ", value).strip()
    return "" if value.lower() in EMPTY_VALUES else value


_ALIAS_SUFFIX_RE = re.compile(r"\s*\([A-Z][A-Z0-9\-]{0,9}\)\s*$")


def strip_alias_suffix(name: str | None) -> str:
    """Убираем короткую аббревиатуру/код в скобках на конце имени.

    Возвращаем исходное имя, если после удаления получилась пустая строка.
    """
    name = clean_text(name)
    if not name:
        return ""
    stripped = _ALIAS_SUFFIX_RE.sub("", name).strip()
    return stripped or name


def lookup_key(value: str | None) -> str:
    """Нормализованный ключ для сопоставления/дедупликации между источниками."""
    value = clean_text(value).lower()
    value = value.replace("′", "'").replace("`", "'")
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .,:;")


def canonicalize_smiles(smiles: str | None) -> tuple[str, str]:
    """Валидируем и канонизируем SMILES через RDKit.
    """
    smiles = clean_text(smiles)
    if not smiles:
        return "", ""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return "", ""
    return Chem.MolToSmiles(mol), inchi.MolToInchiKey(mol)


def _strip_salt_suffix(name: str) -> str | None:
    """Возвращаем имя без солевого суффикса, либо None, если суффикса нет."""
    lowered = name.lower()
    for suffix in _SALT_SUFFIXES:
        if lowered.endswith(suffix):
            return name[: -len(suffix)].rstrip(" ,")
    return None


class CompoundResolver:
    """
    Разрешаем имена на структуры, кешируем результаты, чтобы избежать повторных запросов.
    """

    def __init__(
        self,
        project_root: Path,
        cache_path: Path | None = None,
        catalog_path: Path | None = None,
        allow_pubchem: bool = True,
        allow_opsin: bool = True,
    ) -> None:
        self.project_root = project_root
        self.cache_path = cache_path or project_root / ".cache" / "compound_resolver.json"
        self.catalog_path = default_catalog_path(project_root, catalog_path)
        self.allow_pubchem = allow_pubchem
        self.allow_opsin = allow_opsin
        self.cache: dict[str, dict[str, Any]] = self._load_cache()
        self.catalog_by_name: dict[str, CompoundResolution] = {}
        self.catalog_by_id: dict[tuple[str, str], CompoundResolution] = {}
        self._load_catalog()

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        """Загружаем кеш из файла."""
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def save_cache(self) -> None:
        """Сохраняем кеш в файл."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _load_catalog(self) -> None:
        """Загружаем локальный каталог имя/compound_id -> SMILES."""
        if not self.catalog_path.exists():
            return
        with self.catalog_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fields = set(reader.fieldnames or [])
            has_name_col = {"name", "smiles"} <= fields
            has_id_cols = {"doi", "compound_id", "smiles"} <= fields
            for row in reader:
                smiles, inchikey = canonicalize_smiles(row.get("smiles"))
                if not smiles:
                    continue
                if has_name_col:
                    name = clean_text(row.get("name"))
                    if name:
                        key = lookup_key(name)
                        self.catalog_by_name.setdefault(
                            key,
                            CompoundResolution(
                                query=name, name=name, smiles=smiles, inchikey=inchikey,
                                source=str(self.catalog_path),
                            ),
                        )
                if has_id_cols:
                    doi = lookup_key(row.get("doi"))
                    cid = clean_text(row.get("compound_id"))
                    if doi and cid:
                        self.catalog_by_id[(doi, cid)] = CompoundResolution(
                            query=cid,
                            name=clean_text(row.get("name")) or cid,
                            smiles=smiles,
                            inchikey=inchikey,
                            source=f"{self.catalog_path} (manual override)",
                        )

    def resolve(self, name: str) -> CompoundResolution:
        """Резолвим одно имя на CompoundResolution. Результат кешируется по ключу."""
        name = clean_text(name)
        if not name:
            return CompoundResolution(query="")

        query_name = name
        name = RESOLVER_QUERY_ALIASES.get(lookup_key(name), name)
        key = lookup_key(name)

        cached = self.cache.get(key)
        if cached:
            return CompoundResolution(query=query_name, **cached)

        local = self.catalog_by_name.get(key)
        if local:
            resolution = CompoundResolution(
                query=query_name, name=local.name, smiles=local.smiles,
                inchikey=local.inchikey, source=local.source,
            )
            self._remember(key, resolution)
            return resolution

        resolution = self._resolve_opsin(name)
        if not resolution.smiles and self.allow_pubchem:
            resolution = self._resolve_pubchem(name)
        resolution.query = query_name
        if not resolution.name:
            resolution.name = query_name

        self._remember(key, resolution)
        return resolution

    def resolve_for_compound(self, name: str, doi: str = "", compound_id: str = "") -> CompoundResolution:
        """
        Резолвим SMILES для конкретного (doi, compound_id).
        """
        if doi and compound_id:
            override = self.catalog_by_id.get((lookup_key(doi), compound_id))
            if override:
                return override
        return self.resolve(name)

    def _remember(self, key: str, resolution: CompoundResolution) -> None:
        """Сохраняем результат в кеш в памяти."""
        self.cache[key] = {
            "name": resolution.name,
            "smiles": resolution.smiles,
            "inchikey": resolution.inchikey,
            "source": resolution.source,
        }

    def _resolve_opsin(self, name: str) -> CompoundResolution:
        """
        Резолвим систематическое/IUPAC имя offline через OPSIN (нужна Java).
        """
        if not self.allow_opsin:
            return CompoundResolution(query=name)
        openjdk_bin = Path("/usr/local/opt/openjdk/bin")
        if openjdk_bin.exists():
            os.environ["PATH"] = f"{openjdk_bin}:{os.environ.get('PATH', '')}"
        try:
            from py2opsin import py2opsin
        except Exception:
            return CompoundResolution(query=name)

        candidates = [(name, "OPSIN")]
        desalted = _strip_salt_suffix(name)
        if desalted:
            candidates.append((desalted, "OPSIN (desalted)"))

        for candidate, source in candidates:
            try:
                raw_smiles = clean_text(py2opsin(candidate))
            except Exception:
                continue
            smiles, inchikey = canonicalize_smiles(raw_smiles)
            if smiles:
                return CompoundResolution(query=name, name=name, smiles=smiles, inchikey=inchikey, source=source)
        return CompoundResolution(query=name)

    def _resolve_pubchem(self, name: str) -> CompoundResolution:
        """Резолвим имя через PubChem (по точному имени)."""
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
                    source="PubChem",
                )
        return CompoundResolution(query=name)
