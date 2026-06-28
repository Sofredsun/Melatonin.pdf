"""PDF text reading, metadata heuristics, and LLM context preparation.

This module owns everything that turns a raw PDF into the plain-text inputs the
extractor needs: the article text, regex-based metadata (DOI/title/year/...),
abbreviation aliases, and a compacted context fed to the LLM.
"""

from __future__ import annotations
import re
from collections import Counter
from pathlib import Path
import fitz
from .schema import ArticleMetadata


# паттерны для DOI, года и названия
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s,;)\]}<>\"']+", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
KEYWORD_RE = re.compile(
    r"co-?crystal|cocrystal|salt|multicomponent|molar|stoichiometric|"
    r"ratio|prepared|obtained|form\s+[IVX]+|coformer|co-former",
    re.IGNORECASE
)
ALIAS_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9,\-'\u2013\u2014\u2032\s]+?)\s*\(([A-Z0-9][A-Z0-9\-]{1,10})\)")


def read_pdf_text(pdf_path: Path) -> str:
    """
    Извлекаем текст из PDFтс маркерами для нумерации страниц, картинки игнорируем
    """
    doc = fitz.open(pdf_path)
    pages = []
    for page_idx, page in enumerate(doc):
        text = page.get_text() or ""
        pages.append(f"\n\n<!-- page {page_idx + 1} -->\n{text}")
    return "\n".join(pages)


def doi_from_filename(pdf_path: Path) -> str:
    """
    Если DOI в тексте нет, то используем fallback из имени файла
    """
    stem = re.sub(r"\s+\d+$", "", pdf_path.stem)
    stem = re.sub(r"_crystal$", "", stem)
    if not stem.startswith("10."):
        return ""
    prefix, _, suffix = stem.partition("_")
    if not suffix:
        return ""
    return f"{prefix}/{suffix}"


def extract_doi(text: str, pdf_path: Path) -> str:
    """
    Ищем DOI в тексте
    """
    match = DOI_RE.search(text[:12000])
    if match:
        return match.group(0).rstrip(".,;")
    return doi_from_filename(pdf_path)


def guess_publisher(doi: str, text: str) -> str:
    """
    Определяем издателя из префикса DOI
    """
    # пока сделала так, думаю тут можно сделать агента, который ходит например на
    # https://journaltoolkit.com/tools/doi-checker, всталвяет туда DOI и возвращает издатля
    # хотя вроде такую инфу нам необязательно вытаскивать
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
    if doi_lower.startswith("10.1248/"):
        return "Pharmaceutical Society of Japan"
    return ""


def guess_title(text: str) -> str:
    """
    Название статьи с первой страницы
    """
    # аналоигчно можно доставать название как я писала в guess_publisher
    first_page = text.split("<!-- page 2 -->", 1)[0]
    lines = [" ".join(line.split()) for line in first_page.splitlines()]
    lines = [line for line in lines if len(line) >= 12]
    skip = re.compile(
        r"^(<!--|citation|article|abstract|keywords|contents lists|available online|"
        r"research open access|copyright|©|http|www\.)",
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
    """Фамилия первого автора с первой страницы, например Yutani или Li."""
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
    """
    Определяем год статьи по наиболее часто встречающемуся году в тексте
    """
    # аналоигчно можно доставать год как я писала в guess_publisher
    window = text[:8000]
    years = [int(m.group(0)) for m in YEAR_RE.finditer(window)]
    plausible = [year for year in years if 1990 <= year <= 2035]
    if plausible:
        counts = Counter(plausible)
        return str(max(counts, key=lambda year: (counts[year], -plausible.index(year))))
    match = re.search(r"\.(20\d{2})\.", doi)
    return match.group(1) if match else ""


def article_metadata(pdf_path: Path, text: str) -> ArticleMetadata:
    """
    Объединяем все метаданные
    """
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


def compact_context(text: str, max_chars=8000) -> str:
    """
    Сохраняем начало статьи плюс дедуплицированные строки, 
    которые соответствуют ключевым словам
    """
    head = text[:3500]
    keyword_lines: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if len(line) < 35 or not KEYWORD_RE.search(line):
            continue
        if line in seen:
            continue
        seen.add(line)
        keyword_lines.append(line)
        if sum(len(item) + 1 for item in keyword_lines) > max_chars - len(head):
            break
    context = head + "\n\nRelevant lines:\n" + "\n".join(keyword_lines)
    return context[:max_chars]


def extract_aliases(text: str) -> dict[str, str]:
    """
    Маппим аббревиатуры статьи на полные названия, например cbz: carbamazepine
    Позволяет заменять аббревиатуры на полные названия, когда LLM возвращает только аббревиатуру
    """
    aliases: dict[str, str] = {}
    for match in ALIAS_RE.finditer(text[:30000]):
        full, alias = match.groups()
        full = " ".join(full.split()).strip(" ,;:.")
        full = re.sub(r"^(?:and|or)\s+", "", full, flags=re.IGNORECASE)
        alias = alias.strip()
        if not full or not alias:
            continue
        if not re.search(r"[A-Z]", alias):
            continue
        # Часто в заголовках говорится "CBZ-succinic acid (SUC)";
        # сохраняем химическое название после аббревиатуры, но не режем IUPAC-дефисы.
        cocrystal_prefix = re.match(r"^[A-Z0-9]{2,10}\s*[-\u2013\u2014]\s*(.+[a-z].*)$", full)
        if cocrystal_prefix:
            full = cocrystal_prefix.group(1).strip()
        words = full.split()
        if len(words) > 8:
            full = " ".join(words[-8:])
        if len(full) < 3 or full.lower() in {"figure", "table", "form"}:
            continue
        aliases[alias.lower()] = full
    return aliases
