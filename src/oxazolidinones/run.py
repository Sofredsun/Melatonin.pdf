"""
Точка входа CLI: запуск пайплайна извлечения MIC/MBC оксазолидинонов из PDF.
"""

from __future__ import annotations

from pathlib import Path

from .extractor import extract_pdf, write_prediction_csv
from src.cocrystals.resolver import lookup_key
from .schema import PredictionRow

INPUT_DIR = "src/oxazolidinones"
OUTPUT_PATH = "outputs/oxazolidinones_prediction.csv"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]

def collect_pdfs(input_dir: Path) -> list[Path]:
    """Собираем все PDF"""
    return sorted(path for path in input_dir.glob("*.pdf") if path.exists())

def deduplicate_rows(rows: list[PredictionRow]) -> list[PredictionRow]:
    """Убираем дубликаты"""
    result: list[PredictionRow] = []
    seen: set[tuple] = set()
    for row in rows:
        key = (
            lookup_key(row.doi),
            lookup_key(row.compound_id),
            lookup_key(row.bacteria),
            row.target_type.upper(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def main() -> None:
    """Извлекаем данные из каждого PDF и записываем общий prediction CSV"""
    root = project_root()
    input_dir = root / INPUT_DIR
    out_path = root / OUTPUT_PATH

    pdfs = collect_pdfs(input_dir)
    if not pdfs:
        raise FileNotFoundError(f"No PDF files found in {input_dir}")

    all_rows: list[PredictionRow] = []
    for pdf_path in pdfs:
        print(
            f"Extracting {pdf_path.relative_to(root) if pdf_path.is_relative_to(root) else pdf_path}",
            flush=True
        )
        rows = extract_pdf(pdf_path, project_root=root)
        print(f"rows: {len(rows)}", flush=True)
        all_rows.extend(rows)

    all_rows = deduplicate_rows(all_rows)
    write_prediction_csv(all_rows, out_path)
    print(f"Wrote {len(all_rows)} rows to {out_path}", flush=True)


if __name__ == "__main__":
    main()
