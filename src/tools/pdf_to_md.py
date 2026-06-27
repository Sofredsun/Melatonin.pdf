import json
import os
import re
import sys
from pathlib import Path

import pymupdf4llm

_PICTURE_NOISE_RE = re.compile(
    r"\*\*==> picture \[\d+ x \d+\] intentionally omitted <==\*\*\s*"
    r"(\*\*----- Start of picture text -----\*\*.*?\*\*----- End of picture text -----\*\*\s*)?",
    re.DOTALL,
)


def _strip_picture_noise(text: str) -> str:
    return _PICTURE_NOISE_RE.sub("", text)


def _basename_any(path: str) -> str:
    """Берет basename вручную по обоим разделителям."""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def text_only_markdown(pdf_path: str) -> list[dict]:
    """
    Текст постранично, без картинок и без векторной графики.
    page_chunks=True чтобы знать, к какой странице относится кусок текста
    """
    pages = pymupdf4llm.to_markdown(
        pdf_path,
        page_chunks=True,
        ignore_images=True,
        ignore_graphics=True,
    )
    for p in pages:
        p["text"] = _strip_picture_noise(p["text"])
    return pages


def load_page_images(candidates_json_path: str) -> dict[int, list[dict]]:
    """
    Берет уже готовые image_candidate/vector_candidate из candidates.json
    (результат extract_candidates.py)
    Пропускает text_candidate (это не картинки) и is_boilerplate=True
    Внутри страницы сортирует по bbox y0, чтобы порядок в .md примерно
    совпадал с порядком на странице сверху вниз.
    """
    with open(candidates_json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    by_page: dict[int, list[dict]] = {}
    for c in raw:
        if c["candidate_type"] not in ("image_candidate", "vector_candidate"):
            continue
        if c.get("is_boilerplate"):
            continue
        if not c.get("crop_path"):
            continue
        by_page.setdefault(c["page"], []).append(c)

    for page, items in by_page.items():
        items.sort(key=lambda c: c["bbox"][1])  # y0, сверху вниз
    return by_page


def build_markdown(pdf_path: str, candidates_json_path: str, crops_rel_dir: str = "crops") -> str:
    """
    Собирает финальный markdown: текст страницы + после него ссылки на
    картинки этой же страницы из candidates.json.
    """
    pages = text_only_markdown(pdf_path)
    images_by_page = load_page_images(candidates_json_path)

    parts = []
    for page_idx, page in enumerate(pages):
        parts.append(page["text"])
        for c in images_by_page.get(page_idx, []):
            name = _basename_any(c["crop_path"])
            label = c["candidate_type"].replace("_candidate", "")
            parts.append(f"![{label} p{page_idx}]({crops_rel_dir}/{name})")
        parts.append(f"\n<!-- end of page {page_idx} -->\n")

    return "\n\n".join(parts)


def validate_md(candidates_json_path: str, md_text: str) -> dict:
    """Сверка против candidates.json"""
    images_by_page = load_page_images(candidates_json_path)
    expected = sum(len(v) for v in images_by_page.values())
    actual = md_text.count("![")
    return {
        "expected_image_refs_from_candidates_json": expected,
        "actual_image_refs_in_md": actual,
        "table_like_lines_in_md": sum(1 for l in md_text.split("\n") if l.count("|") >= 2),
        "md_char_count": len(md_text),
        "leftover_picture_noise": "**----- Start of picture text" in md_text,
        "warning": (
            "Число ссылок на картинки в .md не совпадает с candidates.json - "
            "проверить load_page_images/build_markdown."
            if expected != actual else None
        ),
    }


def _process_one_pdf(pdf_path: Path, project_root: Path,
                     candidates_json_override: Path | None = None) -> None:
    """
    Конвертирует один PDF в markdown и кладет результат в ту же папку
    data/sample_<имя файла>/, что уже создал extract_candidates.py для
    этого PDF (там лежит его candidates.json и crops/) - чтобы не
    разводить два разных способа именования папок между двумя скриптами
    пайплайна.

    Если candidates.json для этого PDF еще не существует (extract_candidates.py
    не запускали) - не падаем всем batch-прогоном, а пропускаем файл с
    предупреждением, чтобы один забытый шаг не останавливал обработку
    остальных статей.
    """
    sample_dir = project_root / "results" / "samples" / f"sample_{pdf_path.stem}"
    candidates_json_path = candidates_json_override or (sample_dir / "candidates.json")
    out_md = sample_dir / f"{pdf_path.stem}.md"
    out_report = sample_dir / "pdf_to_md_report.json"

    print(f"=== {pdf_path.name} ===")

    if not candidates_json_path.exists():
        print(
            f"ПРОПУЩЕНО: {candidates_json_path} не найден. "
            f"Сначала запустите extract_candidates.py на {pdf_path.name}.\n"
        )
        return

    os.makedirs(out_md.parent, exist_ok=True)

    md_text = build_markdown(str(pdf_path), str(candidates_json_path))
    report = validate_md(str(candidates_json_path), md_text)

    out_md.write_text(md_text, encoding="utf-8")
    out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                          encoding="utf-8")

    print(f"Markdown сохранен в {out_md} ({report['md_char_count']} символов)")
    print(f"Отчет сохранен в {out_report}")
    if report["warning"]:
        print(f"ВНИМАНИЕ: {report['warning']}")
    if report["leftover_picture_noise"]:
        print(
            "ВНИМАНИЕ: остался необработанный блок 'Start of picture text' - проверить _strip_picture_noise")
    print()


if __name__ == "__main__":
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    data_dir = PROJECT_ROOT / "data" / "pdfs"

    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
        if not pdf_path.is_absolute():
            pdf_path = PROJECT_ROOT / pdf_path
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF файл не найден по пути: {pdf_path}")

        candidates_override = None
        if len(sys.argv) > 2:
            candidates_override = Path(sys.argv[2])
            if not candidates_override.is_absolute():
                candidates_override = PROJECT_ROOT / candidates_override

        _process_one_pdf(pdf_path, PROJECT_ROOT, candidates_override)
    else:
        pdf_paths = sorted(data_dir.glob("*.pdf"))
        if not pdf_paths:
            raise FileNotFoundError(f"В папке {data_dir} не найдено ни одного .pdf")
        print(f"Найдено PDF в {data_dir}: {len(pdf_paths)}\n")
        for pdf_path in pdf_paths:
            _process_one_pdf(pdf_path, PROJECT_ROOT)