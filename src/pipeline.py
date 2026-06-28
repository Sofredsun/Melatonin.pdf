import pandas as pd
import os
from pathlib import Path
from src.cocrystals.extractor import extract_pdf


def run_pipeline(pdf_path, domain, output_dir="data/output"):
    print(f"🚀 Старт пайплайна для домена: {domain}")

    # Для cocrystals используем специализированный пайплайн
    if domain == "cocrystals":
        rows = extract_pdf(
            pdf_path=Path(pdf_path),
            project_root=Path(__file__).parent.parent,
            use_llm=True,
            allow_pubchem=True,
            catalog_fallback=True,
            catalog_hints=True,
            catalog_reconcile=True,
            refresh_llm_cache=False
        )
        # Преобразуем в список словарей
        results = [row.as_dict() for row in rows]
        if results:
            os.makedirs(output_dir, exist_ok=True)
            df = pd.DataFrame(results)
            output_path = os.path.join(output_dir, f"submission_{domain}.csv")
            df.to_csv(output_path, index=False)
            print(f"💾 Результат сохранён в {output_path}")
        else:
            print("⚠️ Нет данных для сохранения.")
        return results

