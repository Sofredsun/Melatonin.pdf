from __future__ import annotations

import argparse
from pathlib import Path

from .extractor import extract_pdf, write_prediction_csv
from .resolver import lookup_key
from .schema import PredictionRow


def project_root() -> Path:
    """Repository root (two levels above this file)."""
    return Path(__file__).resolve().parents[2]


def collect_pdfs(inputs: list[str], *, limit: int | None = None) -> list[Path]:
    """Expand input files/dirs into a sorted list of existing PDF paths."""
    pdfs: list[Path] = []
    root = project_root()
    for item in inputs:
        path = Path(item)
        if not path.is_absolute():
            path = root / path
        if path.is_dir():
            pdfs.extend(sorted(path.glob("*.pdf")))
        elif path.suffix.lower() == ".pdf":
            pdfs.append(path)
        else:
            raise ValueError(f"Unsupported input path: {path}")
    pdfs = [path for path in pdfs if path.exists()]
    if limit is not None:
        pdfs = pdfs[:limit]
    return pdfs


def deduplicate_rows(rows: list[PredictionRow]) -> list[PredictionRow]:
    """Drop rows sharing the same (doi, compound_id, bacteria, target_type, value, units)."""
    result: list[PredictionRow] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for row in rows:
        key = (
            lookup_key(row.doi),
            lookup_key(row.compound_id),
            lookup_key(row.bacteria),
            lookup_key(row.target_type),
            lookup_key(row.target_value),
            lookup_key(row.target_units),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def main() -> None:
    """Parse args, extract every input PDF, and write the combined prediction CSV."""
    parser = argparse.ArgumentParser(
        description="Extract benzimidazole antimicrobial-activity fields from PDFs."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        default=["data_full"],
        help="PDF files or directories with PDF files. Defaults to data_full.",
    )
    parser.add_argument("--out", default="outputs/prediction.csv", help="Output prediction CSV path.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of PDFs.")
    parser.add_argument("--no-llm", action="store_true", help="Disable AI Gateway extraction.")
    parser.add_argument("--no-pubchem", action="store_true", help="Disable PubChem resolver.")
    parser.add_argument(
        "--refresh-llm-cache",
        action="store_true",
        help="Ignore cached LLM responses and call AI Gateway again.",
    )
    parser.add_argument(
        "--keep-duplicate-pdfs",
        action="store_true",
        help="Keep duplicate rows from duplicate PDF files with the same key.",
    )
    args = parser.parse_args()

    root = project_root()
    pdfs = collect_pdfs(args.inputs, limit=args.limit)
    if not pdfs:
        raise FileNotFoundError("No PDF files found.")

    all_rows = []
    for pdf_path in pdfs:
        print(
            f"Extracting {pdf_path.relative_to(root) if pdf_path.is_relative_to(root) else pdf_path}",
            flush=True,
        )
        rows = extract_pdf(
            pdf_path,
            project_root=root,
            use_llm=not args.no_llm,
            allow_pubchem=not args.no_pubchem,
            refresh_llm_cache=args.refresh_llm_cache,
        )
        print(f"  rows: {len(rows)}", flush=True)
        all_rows.extend(rows)

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path
    if not args.keep_duplicate_pdfs:
        all_rows = deduplicate_rows(all_rows)

    write_prediction_csv(all_rows, out_path)
    print(f"Wrote {len(all_rows)} rows to {out_path}", flush=True)


if __name__ == "__main__":
    main()
