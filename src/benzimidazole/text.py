from __future__ import annotations
import re
from collections import Counter
from pathlib import Path
import fitz
from .schema import ArticleMetadata


DOI_RE = re.compile(r"10\.\d{4,9}/[^\s,;)\]}<>\"']+", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def read_pdf_text(pdf_path: Path) -> str:
    """Извлекаем текст из PDF с маркерами номера страницы, картинки игнорируем."""
    doc = fitz.open(pdf_path)
    pages = []
    for page_idx, page in enumerate(doc):
        text = page.get_text() or ""
        pages.append(f"\n\n<!-- page {page_idx + 1} -->\n{text}")
    return "\n".join(pages)


def doi_from_filename(pdf_path: Path) -> str:
    """Если DOI в тексте нет, используем fallback из имени файла."""
    stem = re.sub(r"\s+\d+$", "", pdf_path.stem)
    if not stem.startswith("10."):
        return ""
    prefix, _, suffix = stem.partition("_")
    if not suffix:
        return ""
    return f"{prefix}/{suffix}"


def extract_doi(text: str, pdf_path: Path) -> str:
    """Ищем DOI в тексте."""
    match = DOI_RE.search(text[:12000])
    if match:
        return match.group(0).rstrip(".,;")
    return doi_from_filename(pdf_path)


def guess_publisher(doi: str, text: str) -> str:
    """Определяем издателя по префиксу DOI."""
    doi_lower = doi.lower()
    if "mdpi" in text[:4000].lower() or doi_lower.startswith("10.3390/"):
        return "MDPI"
    if doi_lower.startswith("10.1021/"):
        return "ACS"
    if doi_lower.startswith("10.1016/"):
        return "Elsevier"
    if doi_lower.startswith("10.1002/"):
        return "Wiley"
    if doi_lower.startswith("10.1186/"):
        return "Springer Nature"
    if doi_lower.startswith("10.1038/"):
        return "Springer Nature"
    if doi_lower.startswith("10.31788/"):
        return "Rasayan"
    return ""


def guess_title(text: str) -> str:
    """Название статьи с первой страницы."""
    first_page = text.split("<!-- page 2 -->", 1)[0]
    lines = [" ".join(line.split()) for line in first_page.splitlines()]
    lines = [line for line in lines if len(line) >= 12]
    skip = re.compile(
        r"^(<!--|citation|article|abstract|keywords|contents lists|available online|"
        r"research|review|open access|copyright|©|http|www\.)",
        re.IGNORECASE
    )
    for idx, line in enumerate(lines[:30]):
        if skip.search(line):
            continue
        if "doi" in line.lower() and len(line) < 80:
            continue
        title = line
        if idx + 1 < len(lines) and len(title) < 80:
            nxt = lines[idx + 1]
            if not skip.search(nxt) and len(nxt) < 160:
                title = f"{title} {nxt}"
        return title[:300]
    return ""


def format_publisher_year(publisher: str, year: str, author_surname: str = "") -> str:
    """Склеиваем идентификатор статьи и год в формате Wang2024 или MDPI2019."""
    year = (year or "").strip()
    author_surname = re.sub(r"[^A-Za-z\-']", "", (author_surname or "").strip())
    if author_surname and year:
        return f"{author_surname}{year}"
    publisher = re.sub(r"\s+", "", (publisher or "").strip())
    if publisher and year:
        return f"{publisher}{year}"
    return author_surname or publisher or year


AUTHOR_ENTRY_RE = re.compile(
    r"[A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][A-Za-z\-']+(?:\s+\d+[,\*]*)?"
)


def guess_first_author_surname(text: str) -> str:
    """Фамилия первого автора с первой страницы."""
    first_page = text.split("<!-- page 2 -->", 1)[0]
    lines = [" ".join(line.split()) for line in first_page.splitlines()]
    skip = re.compile(
        r"^(<!--|citation|article|abstract|keywords|contents lists|available online|"
        r"research open access|copyright|©|http|www\.|how to cite|international edition|"
        r"german edition|supporting information|correspondence|received:|accepted:|published:)",
        re.IGNORECASE,
    )
    for line in lines[:35]:
        if skip.search(line) or len(line) < 20 or len(line) > 350:
            continue
        if not re.match(
            r"^[A-Z][a-z]+\s+[A-Z][A-Za-z\-']+(?:\s+\d+[,\*]*)?(?:,|\s+and\b)",
            line,
        ):
            continue
        entries = AUTHOR_ENTRY_RE.findall(line)
        if len(entries) < 2:
            continue
        match = re.match(
            r"^(?:[A-Z][a-z]+\.?\s+)+([A-Z][A-Za-z\-']+)",
            re.sub(r"\*+", "", entries[0]).strip(),
        )
        if match:
            return match.group(1)
    return ""


def guess_year(text: str, doi: str) -> str:
    """Определяем год статьи по наиболее часто встречающемуся году в начале текста."""
    window = text[:8000]
    years = [int(m.group(0)) for m in YEAR_RE.finditer(window)]
    plausible = [year for year in years if 1990 <= year <= 2035]
    if plausible:
        counts = Counter(plausible)
        return str(max(counts, key=lambda year: (counts[year], -plausible.index(year))))
    match = re.search(r"\.(20\d{2})\.", doi)
    return match.group(1) if match else ""


def article_metadata(pdf_path: Path, text: str) -> ArticleMetadata:
    """Объединяем все метаданные."""
    doi = extract_doi(text, pdf_path)
    publisher = guess_publisher(doi, text)
    year = guess_year(text, doi)
    author_surname = guess_first_author_surname(text)
    return ArticleMetadata(
        doi=doi,
        title=guess_title(text),
        publisher=publisher,
        year=year,
        pdf=format_publisher_year(publisher, year, author_surname),
    )


# Compound_id -> систематическое имя (для резолва SMILES без LLM)

_NAME_START_RE = r"\d{1,2}(?:,\d{1,2})*-|N,N-|N-"
_COMPOUND_NAME_RE = re.compile(
    r"(?:^|\n)\s*(?P<name>(?:" + _NAME_START_RE + r")[^\n]{10,170}(?:\n[^\n]{10,170}){0,6}?)"
    r"\s*\(\s*(?P<cid>\d{1,3}[a-z]{0,3})\)\.\s"
)


def _join_wrapped_name(raw_name: str) -> str:
    """Склеиваем перенос строки внутри имени без лишнего пробела на дефисе."""
    joined = re.sub(r"-\s*\n\s*", "-", raw_name)
    joined = re.sub(r"\s*\n\s*", " ", joined)
    return " ".join(joined.split())


def extract_compound_names_by_id(text: str) -> dict[str, str]:
    """
    Детерминированно вытаскиваем compound_id -> систематическое (IUPAC) имя.
    """
    names_by_id: dict[str, str] = {}
    for match in _COMPOUND_NAME_RE.finditer(text):
        name = _join_wrapped_name(match.group("name"))
        name = name.strip(" ,;:-")
        cid = match.group("cid").strip()
        lowered = name.lower()
        if "imidazol" not in lowered:
            continue
        if "-" not in name and "[" not in name:
            continue
        existing = names_by_id.get(cid)
        if existing is None or len(name) > len(existing):
            names_by_id[cid] = name
    return names_by_id


# Организмы/штаммы: упоминания, и аббревиатура -> полное латинское название

_BACTERIA_GENUS_WHITELIST = (
    "Staphylococcus", "Escherichia", "Pseudomonas", "Bacillus", "Klebsiella",
    "Enterococcus", "Serratia", "Salmonella", "Proteus", "Streptococcus",
    "Micrococcus", "Clostridium", "Vibrio", "Acinetobacter", "Listeria",
    "Shigella", "Mycobacterium",
)
_FUNGUS_GENUS_DENYLIST = (
    "candida", "aspergillus", "penicillium", "fusarium", "cryptococcus",
    "trichophyton", "microsporum", "saccharomyces", "rhizopus", "mucor",
    "histoplasma", "blastomyces", "coccidioides", "malassezia",
)

_MICROBE_STRAIN_RE = re.compile(
    r"\b([A-Z][a-z]+\s+[a-z]{3,}(?:\s+[a-z]{3,})?)\s*"
    r"\(?\s*(?:ATCC|ATTC|NCTC|NRRL|MTCC|NCCB|CECT)\s*[\dA-Za-z\-]{2,12}\)?"
)
_MICROBE_GENUS_RE = re.compile(
    r"\b(" + "|".join(_BACTERIA_GENUS_WHITELIST) + r")\s+([a-z]{3,}(?:\s+[a-z]{3,})?)\b"
)


def extract_organism_mentions(text: str) -> list[str]:
    """Список организмов, упомянутых в статье, в порядке первого появления.

    Используется как hint для LLM при сопоставлении табличных аббревиатур с
    полными латинскими названиями. _MICROBE_STRAIN_RE (по суффиксу ATCC/MTCC/...)
    род-агностичен, поэтому отдельно отфильтровываем всё, что начинается с
    грибкового рода — иначе хинт сам подсунет LLM, например, "Candida albicans
    (ATCC 10231)" как валидный вариант.
    """
    seen: dict[str, None] = {}
    for match in _MICROBE_STRAIN_RE.finditer(text):
        name = " ".join(match.group(1).split())
        if name.split()[0].lower() in _FUNGUS_GENUS_DENYLIST:
            continue
        seen.setdefault(name, None)
    for match in _MICROBE_GENUS_RE.finditer(text):
        name = f"{match.group(1)} {match.group(2)}"
        seen.setdefault(name, None)
    return list(seen.keys())


_FOOTNOTE_ALIAS_STOPWORDS = {"fig", "eq", "ref", "vol", "no", "viz", "cf", "ie", "eg", "etc"}
_FOOTNOTE_ALIAS_RE = re.compile(r"\b([A-Za-z]{1,3})\s*[:.]\s*([A-Z][a-z]*\.?\s+[a-z]{3,}[a-z]*)")
_NAME_PAREN_ABBR_RE = re.compile(r"\b([A-Z][a-z]+\s+[a-z]{3,})\s*\(\s*([A-Za-z]{1,4})\s*\)")


def extract_bacteria_aliases(text: str) -> dict[str, str]:
    """Словарь короткий-код (lowercase) -> полное латинское название организма.

    Покрывает два распространенных в этой области шаблона:
    1) легенда под таблицей вида "A: E. coli. B: S. marcescens. C: K. pneumoniae.";
    2) имя прямо с аббревиатурой в скобках: "Staphylococcus aureus (Sa)".
    """
    aliases: dict[str, str] = {}
    for abbr, full in _FOOTNOTE_ALIAS_RE.findall(text):
        if abbr.lower() in _FOOTNOTE_ALIAS_STOPWORDS:
            continue
        full = " ".join(full.split())
        if len(full.split()) < 2:
            continue
        if full.split()[0].lower() in _FUNGUS_GENUS_DENYLIST:
            continue
        aliases.setdefault(abbr.lower(), full)
    for full, abbr in _NAME_PAREN_ABBR_RE.findall(text):
        if full.split()[0].lower() in _FUNGUS_GENUS_DENYLIST:
            continue
        aliases.setdefault(abbr.lower(), " ".join(full.split()))
    return aliases


# Контекст для LLM: голова статьи + таблицы целиком + строки с ключевыми словами

KEYWORD_RE = re.compile(
    r"\bMIC\b|minimum inhibitory concentration|zone of inhibition|inhibition zone|"
    r"\bIC50\b|\bGI50\b|\bLD50\b|antibacterial|antimicrobial|antifungal|"
    r"disk diffusion|disc diffusion|broth microdilution|microdilution|"
    r"\bATCC\b|\bATTC\b|\bMTCC\b|\bNCTC\b|\bNRRL\b|Gram-positive|Gram-negative|"
    r"µg\s*/?\s*mL|ug/mL|mg/mL|mol/kg|standard drug|reference (?:drug|standard)",
    re.IGNORECASE,
)

_TABLE_START_RE = re.compile(r"^\s*Table\s+\d+\b", re.IGNORECASE)
_TABLE_STOP_RE = re.compile(
    r"^\s*(Table\s+\d+\b|Fig(?:ure)?\.?\s*\d+\b|References|Conclusion|Acknowledg)",
    re.IGNORECASE,
)


def extract_table_blocks(text: str, max_chars: int = 6000, max_lines_per_table: int = 80) -> str:
    """Грубо вырезаем блоки текста, начинающиеся со строки "Table N"."""
    lines = text.splitlines()
    blocks: list[str] = []
    used = 0
    i = 0
    while i < len(lines):
        if not _TABLE_START_RE.match(lines[i]):
            i += 1
            continue
        block_lines = [lines[i]]
        j = i + 1
        while j < len(lines) and len(block_lines) < max_lines_per_table:
            if _TABLE_STOP_RE.match(lines[j]):
                break
            block_lines.append(lines[j])
            j += 1
        block = "\n".join(" ".join(line.split()) for line in block_lines if line.strip())
        if used + len(block) > max_chars:
            block = block[: max(0, max_chars - used)]
        if block:
            blocks.append(block)
            used += len(block)
        i = j
        if used >= max_chars:
            break
    return "\n\n".join(blocks)


def compact_context(text: str, max_chars: int = 14000) -> str:
    """Компактный контекст для LLM: голова статьи + таблицы + строки-по-ключевым-словам."""
    head = text[:3000]

    table_budget = min(7000, max_chars // 2)
    tables = extract_table_blocks(text, max_chars=table_budget)

    remaining = max_chars - len(head) - len(tables) - 200
    remaining = max(remaining, 0)

    keyword_lines: list[str] = []
    seen: set[str] = set()
    used = 0
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if len(line) < 35 or not KEYWORD_RE.search(line):
            continue
        if line in seen:
            continue
        seen.add(line)
        used += len(line) + 1
        if used > remaining:
            break
        keyword_lines.append(line)

    parts = [head]
    if tables:
        parts.append("\n\nTables found in the article (raw text, may be imperfectly ordered):\n" + tables)
    if keyword_lines:
        parts.append(
            "\n\nRelevant lines (assay methodology, organism strain codes):\n" + "\n".join(keyword_lines)
        )
    return "".join(parts)[:max_chars]