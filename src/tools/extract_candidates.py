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


def _merge_adjacent_blocks(
    items: list[tuple[str, tuple]], edge_tol: float = 1.5, length_tol: float = 1.5
) -> list[tuple[str, tuple]]:
    """
    items: список (тег, bbox) для растровых блоков ОДНОЙ страницы.

    Склеивает два блока, если они стыкуются ровно по одной общей стороне:
      - один заканчивается там, где начинается другой (с точностью edge_tol) -
        это "угол совпадает"
      - и совпадает длина по перпендикулярной стороне (с точностью length_tol) -
        это "и длина одинаковая", иначе случайное касание уголками двух
        совершенно разных картинок тоже считалось бы стыком.

    Проверяются оба направления стыка - по вертикали (одна картинка под
    другой, совпадает левый/правый край) и по горизонтали (одна картинка
    справа от другой, совпадает верх/низ) - PyMuPDF режет крупный растровый
    рисунок на полосы и так, и так, в зависимости от PDF.

    Итеративно (while changed) - чтобы склеить цепочку из многих полос
    подряд, а не только одну пару за раз.
    """
    blocks: list[tuple[str, list] | None] = [(tag, list(bbox)) for tag, bbox in items]
    changed = True
    while changed:
        changed = False
        for i in range(len(blocks)):
            if blocks[i] is None:
                continue
            tag_a, a = blocks[i]
            for j in range(i + 1, len(blocks)):
                if blocks[j] is None:
                    continue
                tag_b, b = blocks[j]

                # стык по вертикали: одна картинка под другой - совпадает
                # левый и правый край (это и есть "длина" по X), низ верхней
                # картинки касается верха нижней
                same_x = abs(a[0] - b[0]) <= length_tol and abs(a[2] - b[2]) <= length_tol
                touch_y = abs(a[3] - b[1]) <= edge_tol or abs(b[3] - a[1]) <= edge_tol

                # стык по горизонтали: одна картинка справа от другой -
                # совпадает верхний и нижний край, правый край левой
                # картинки касается левого края правой
                same_y = abs(a[1] - b[1]) <= length_tol and abs(a[3] - b[3]) <= length_tol
                touch_x = abs(a[2] - b[0]) <= edge_tol or abs(b[2] - a[0]) <= edge_tol

                if (same_x and touch_y) or (same_y and touch_x):
                    merged = [min(a[0], b[0]), min(a[1], b[1]),
                              max(a[2], b[2]), max(a[3], b[3])]
                    blocks[i] = (tag_a, merged)
                    blocks[j] = None
                    changed = True
                    break
            if changed:
                break
    return [(tag, tuple(bb)) for tag, bb in (item for item in blocks if item is not None)]


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

        # type==1 блоки откладываем - сначала только bbox, без рендера,
        # чтобы успеть склеить полосы по углу+длине ДО того, как они лягут
        # на диск как отдельные файлы
        raw_image_blocks: list[tuple[str, tuple]] = []

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

            elif block["type"] == 1:  # изображение/вектор-блок - откладываем
                raw_image_blocks.append((f"b{b_idx}", bbox))

        # embedded images через get_images - дедуп НА УРОВНЕ ИСХОДНЫХ
        # (ещё не склеенных) блоков. Если сравнивать с уже склеенным bbox,
        # IoU маленькой полоски против большого объединённого прямоугольника
        # всегда низкий и дедуп не сработает - поэтому дедуп идёт раньше склейки.
        raw_image_bboxes = [bbox for _, bbox in raw_image_blocks]
        embedded_blocks: list[tuple[str, tuple]] = []
        for img_idx, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []
            for r in rects:
                bbox = tuple(round(v, 1) for v in r)
                if any(_bbox_iou(bbox, e) > 0.85 for e in raw_image_bboxes):
                    continue  # тот же объект уже пришёл из get_text("dict")
                embedded_blocks.append((f"embimg{img_idx}", bbox))

        # склейка по совпадению угла+длины (см. _merge_adjacent_blocks) -
        # и type==1, и embedded вместе, т.к. картинка может прийти любым путём
        merged_image_blocks = _merge_adjacent_blocks(raw_image_blocks + embedded_blocks)

        # теперь рендерим - один раз на каждый итоговый (возможно склеенный) блок
        for tag, bbox in merged_image_blocks:
            crop_path = os.path.join(out_dir, f"p{page_idx}_{tag}.png")
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


def _process_one_pdf(pdf_path: Path, project_root: Path) -> None:
    """
    Запускает extract_candidates на одном PDF и сохраняет результат в
    отдельную папку data/sample_<имя файла без .pdf>/ (crops/ + candidates.json) -
    чтобы результаты разных статей не перезатирали друг друга в общей
    data/sample/, как было раньше при одном захардкоженном пути.
    """
    out_root = project_root / "data" / f"sample_{pdf_path.stem}"
    out_dir = out_root / "crops"
    out_json = out_root / "candidates.json"

    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(out_json.parent, exist_ok=True)

    print(f"=== {pdf_path.name} ===")
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
    print(f"Сохранено в {out_json}\n")


if __name__ == "__main__":
    import sys

    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    data_dir = PROJECT_ROOT / "data"

    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
        if not pdf_path.is_absolute():
            pdf_path = PROJECT_ROOT / pdf_path
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF файл не найден по пути: {pdf_path}")
        _process_one_pdf(pdf_path, PROJECT_ROOT)
    else:
        pdf_paths = sorted(data_dir.glob("*.pdf"))
        if not pdf_paths:
            raise FileNotFoundError(f"В папке {data_dir} не найдено ни одного .pdf")
        print(f"Найдено PDF в {data_dir}: {len(pdf_paths)}\n")
        for pdf_path in pdf_paths:
            _process_one_pdf(pdf_path, PROJECT_ROOT)