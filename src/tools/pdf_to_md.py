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
    """
    Берет basename вручную по обоим разделителям.
    """
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
    """
    Сверка против candidates.json
    """
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


if __name__ == "__main__":
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

    default_pdf = PROJECT_ROOT / "data" / "crystals-09-00553-v2.pdf"
    default_candidates = PROJECT_ROOT / "data" / "sample" / "candidates.json"
    out_md = PROJECT_ROOT / "data" / "sample" / "crystals-09-00553-v2.md"
    out_report = PROJECT_ROOT / "data" / "sample" / "pdf_to_md_report.json"

    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
        if not pdf_path.is_absolute():
            pdf_path = PROJECT_ROOT / pdf_path
    else:
        pdf_path = default_pdf

    candidates_json_path = Path(sys.argv[2]) if len(sys.argv) > 2 else default_candidates

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF файл не найден по пути: {pdf_path}")
    if not candidates_json_path.exists():
        raise FileNotFoundError(
            f"candidates.json не найден по пути: {candidates_json_path}. "
            f"Сначала запустите extract_candidates.py на этом же PDF."
        )

    os.makedirs(out_md.parent, exist_ok=True)

    md_text = build_markdown(str(pdf_path), str(candidates_json_path))
    report = validate_md(str(candidates_json_path), md_text)

    out_md.write_text(md_text, encoding="utf-8")
    out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Markdown сохранён в {out_md} ({report['md_char_count']} символов)")
    print(f"Отчёт сохранён в {out_report}")
    if report["warning"]:
        print(f"ВНИМАНИЕ: {report['warning']}")
    if report["leftover_picture_noise"]:
        print("ВНИМАНИЕ: остался необработанный блок 'Start of picture text' - проверить _strip_picture_noise")
