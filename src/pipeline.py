import pandas as pd
import os
from pathlib import Path

# Импорты для каждого домена
from src.cocrystals.extractor import extract_pdf as extract_cocrystals
from src.benzimidazoles.extractor import extract_pdf as extract_benzimidazole
from src.oxazolidinones.extractor import extract_pdf as extract_oxazolidinones


def run_pipeline(pdf_path, domain, output_dir="data/output"):
    print(f"🚀 Старт пайплайна для домена: {domain}")

    results = []

    # 1. Кокристаллы
    if domain == "cocrystals":
        rows = extract_cocrystals(
            pdf_path=Path(pdf_path),
            project_root=Path(__file__).parent.parent,
            use_llm=True,
            allow_pubchem=True,
            catalog_fallback=True,
            catalog_hints=True,
            catalog_reconcile=True,
            refresh_llm_cache=False
        )
        results = [row.as_dict() for row in rows]

    # 2. Бензимидазолы (антимикробная активность)
    elif domain == "benzimidazoles":
        rows = extract_benzimidazole(
            pdf_path=Path(pdf_path),
            project_root=Path(__file__).parent.parent,
            use_llm=True,
            allow_pubchem=True,
            refresh_llm_cache=False
        )
        results = [row.as_dict() for row in rows]

    # 3. Оксазолидиноны (MIC/MBC)
    elif domain == "oxazolidinones":
        rows = extract_oxazolidinones(
            pdf_path=Path(pdf_path),
            project_root=Path(__file__).parent.parent,
            use_llm=True,
            allow_pubchem=True,
            refresh_llm_cache=False
        )
        results = [row.as_dict() for row in rows]

    else:
        print(f"⚠️ Домен '{domain}' не поддерживается. Доступны: cocrystals, benzimidazoles, oxazolidinones.")
        return []

    if results:
        os.makedirs(output_dir, exist_ok=True)
        df = pd.DataFrame(results)
        output_path = os.path.join(output_dir, f"submission_{domain}.csv")
        df.to_csv(output_path, index=False)
        print(f"💾 Результат сохранён в {output_path}")
        print(f"📊 Всего записей: {len(results)}")
    else:
        print("⚠️ Нет данных для сохранения.")

    return results
