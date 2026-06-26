import fitz  # PyMuPDF
import json
import os
from dataclasses import dataclass, asdict
from typing import Literal
from pathlib import Path


@dataclass
class Candidate:
    page: int
    candidate_type: Literal["text_candidate", "image_candidate", "vector_candidate"]
    bbox: tuple
    text: str | None = None
    crop_path: str | None = None
    n_words: int | None = None
    is_boilerplate: bool = False


def _bbox_iou(a: tuple, b: tuple) -> float:
    """
    Intersection-over-Union для двух bbox в формате (x0, y0, x1, y1).
    Нужна для дедупа: один и тот же визуальный объект на странице может
    прийти и как block type==1 из get_text("dict"), и как embedded image
    из get_images() - у обоих почти одинаковый bbox, но это не два
    разных объекта, а один и тот же, отрендеренный дважды.
    """
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = (ax1 - ax0) * (ay1 - ay0)
    area_b = (bx1 - bx0) * (by1 - by0)
    denom = area_a + area_b - inter
    return inter / denom if denom > 0 else 0.0


def _merge_overlapping_rects(rects: list[fitz.Rect], pad: float = 4.0) -> list[fitz.Rect]:
    """
    Группирует близкие/перекрывающиеся векторные пути в кластеры.
    Нужно потому, что одна структурная формула на странице обычно
    состоит из десятков отдельных vector paths (связи, кольца, метки),
    а не из одного объекта
    """
    rects = [fitz.Rect(r) for r in rects]
    changed = True
    while changed:
        changed = False
        merged = []
        used = [False] * len(rects)
        for i, r in enumerate(rects):
            if used[i]:
                continue
            current = fitz.Rect(r)
            for j in range(i + 1, len(rects)):
                if used[j]:
                    continue
                other = rects[j]
                expanded = fitz.Rect(current)
                expanded.x0 -= pad
                expanded.y0 -= pad
                expanded.x1 += pad
                expanded.y1 += pad
                if expanded.intersects(other):
                    current |= other
                    used[j] = True
                    changed = True
            used[i] = True
            merged.append(current)
        rects = merged
    return rects


def _is_probably_table_like(text: str) -> bool:
    """
    Грубая эвристика: если в текстовом блоке много коротких "ячеек"
    через множественные пробелы/таб - вероятно это безграничная
    (borderless) таблица, а не обычный абзац.
    """
    lines = [l for l in text.split("\n") if l.strip()]
    if not lines:
        return False
    multi_gap_lines = sum(1 for l in lines if len(l.split("  ")) >= 3)
    return multi_gap_lines / len(lines) > 0.5


def _is_probably_boilerplate(bbox: tuple, page: fitz.Page, page_idx: int, n_pages: int) -> bool:
    """
    Грубая позиционная эвристика для логотипов журнала / CC BY плашек.

    Расширено после проверки на реальной статье: логотипы на первой
    странице может стоять как в правом, так и в левом верхнем углу (два
    разных лого), а плашка CC BY на последней странице стоит сразу после
    "Conflicts of Interest" - это середина страницы, не нижний край.
    Поэтому для последней страницы берём широкий нижний пояс (от 50% высоты),
    а не жесткие 85%.
    """
    x0, y0, x1, y1 = bbox
    area = (x1 - x0) * (y1 - y0)
    near_top_corner = page_idx == 0 and y1 < 100 and (
        x0 > page.rect.width * 0.7 or x1 < page.rect.width * 0.3
    )
    near_lower_half_last = page_idx == n_pages - 1 and y0 > page.rect.height * 0.5
    return area < 3000 and (near_top_corner or near_lower_half_last)


def extract_candidates(pdf_path: str, out_dir: str, zoom: float = 3.0) -> list[Candidate]:
    doc = fitz.open(pdf_path)
    n_pages = doc.page_count
    os.makedirs(out_dir, exist_ok=True)
    candidates: list[Candidate] = []

    for page_idx, page in enumerate(doc):
        blocks = page.get_text("dict")["blocks"]

        for b_idx, block in enumerate(blocks):
            bbox = tuple(round(v, 1) for v in block["bbox"])

            if block["type"] == 0:  # текстовый блок
                text = "\n".join(
                    "".join(span["text"] for span in line["spans"])
                    for line in block["lines"]
                )
                n_words = len(text.split())
                if n_words == 0:
                    continue
                candidates.append(
                    Candidate(
                        page=page_idx,
                        candidate_type="text_candidate",
                        bbox=bbox,
                        text=text,
                        n_words=n_words,
                    )
                )

            elif block["type"] == 1:  # изображение/вектор-блок
                crop_path = os.path.join(
                    out_dir, f"p{page_idx}_b{b_idx}.png"
                )
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, clip=fitz.Rect(bbox))
                pix.save(crop_path)
                candidates.append(
                    Candidate(
                        page=page_idx,
                        candidate_type="image_candidate",
                        bbox=bbox,
                        crop_path=crop_path,
                        is_boilerplate=_is_probably_boilerplate(bbox, page, page_idx, n_pages),
                    )
                )

        # embedded images через get_images (с дедупом против блоков выше)
        page_img_bboxes = [
            c.bbox for c in candidates
            if c.page == page_idx and c.candidate_type == "image_candidate"
        ]
        for img_idx, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []
            for r in rects:
                bbox = tuple(round(v, 1) for v in r)
                if any(_bbox_iou(bbox, e) > 0.85 for e in page_img_bboxes):
                    continue  # тот же объект уже пришёл из get_text("dict")
                crop_path = os.path.join(out_dir, f"p{page_idx}_embimg{img_idx}.png")
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, clip=r)
                pix.save(crop_path)
                candidates.append(
                    Candidate(
                        page=page_idx,
                        candidate_type="image_candidate",
                        bbox=bbox,
                        crop_path=crop_path,
                        is_boilerplate=_is_probably_boilerplate(bbox, page, page_idx, n_pages),
                    )
                )
                page_img_bboxes.append(bbox)

        # векторная графика (структуры/схемы, нарисованные линиями)
        drawing_rects = [d["rect"] for d in page.get_drawings() if not d["rect"].is_empty]
        clusters = [r for r in _merge_overlapping_rects(drawing_rects)
                    if r.width >= 15 and r.height >= 15]
        absorb_pad = 28.0
        absorbed_idx: set[int] = set()
        merged_clusters: list[fitz.Rect] = []
        for rect in clusters:
            expanded = fitz.Rect(rect.x0 - absorb_pad, rect.y0 - absorb_pad,
                                  rect.x1 + absorb_pad, rect.y1 + absorb_pad)
            for ci, c in enumerate(candidates):
                if c.page != page_idx or c.candidate_type not in ("image_candidate", "text_candidate"):
                    continue
                if ci in absorbed_idx:
                    continue
                cb = fitz.Rect(c.bbox)
                inter_area = (expanded & cb).get_area()
                cb_area = max(cb.get_area(), 1)
                if inter_area / cb_area > 0.8:
                    rect |= cb
                    absorbed_idx.add(ci)
            merged_clusters.append(rect)

        if absorbed_idx:
            candidates = [c for ci, c in enumerate(candidates) if ci not in absorbed_idx]

        for v_idx, rect in enumerate(merged_clusters):
            crop_path = os.path.join(out_dir, f"p{page_idx}_vec{v_idx}.png")
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, clip=rect)
            pix.save(crop_path)
            vec_bbox = tuple(round(v, 1) for v in rect)
            candidates.append(
                Candidate(
                    page=page_idx,
                    candidate_type="vector_candidate",
                    bbox=vec_bbox,
                    crop_path=crop_path,
                    is_boilerplate=_is_probably_boilerplate(vec_bbox, page, page_idx, n_pages),
                )
            )

    return candidates


if __name__ == "__main__":
    import sys

    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

    default_pdf = PROJECT_ROOT / "data" / "crystals-09-00553-v2.pdf"
    out_dir = PROJECT_ROOT / "data" / "sample" / "crops"
    out_json = PROJECT_ROOT / "data" / "sample" / "candidates.json"

    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
        if not pdf_path.is_absolute():
            pdf_path = PROJECT_ROOT / pdf_path
    else:
        pdf_path = default_pdf

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF файл не найден по пути: {pdf_path}")

    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(out_json.parent, exist_ok=True)

    candidates = extract_candidates(str(pdf_path), str(out_dir))

    print(f"Найдено кандидатов: {len(candidates)}")
    for c in candidates:
        flag = ""
        if c.candidate_type == "text_candidate" and _is_probably_table_like(c.text or ""):
            flag = "  <- похоже на borderless-таблицу, проверить классификатором"
        if c.is_boilerplate:
            flag += "  <- помечено как boilerplate (логотип/CC-плашка)"
        print(f"  [{c.candidate_type}] page={c.page} bbox={c.bbox}{flag}")

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump([asdict(c) for c in candidates], f, ensure_ascii=False, indent=2)
    print(f"Сохранено в {out_json}")
