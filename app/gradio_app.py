import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gradio as gr
import tempfile
import pandas as pd
from src.pipeline import run_pipeline


def process_pdf(file, domain):
    if file is None:
        return None, None, "Пожалуйста, загрузите PDF-файл."

    # Получаем путь к PDF
    if hasattr(file, 'name'):
        pdf_path = file.name
    elif isinstance(file, str):
        pdf_path = file
    else:
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(file.read())
                pdf_path = tmp.name
        except AttributeError:
            return None, None, "Не удалось прочитать файл. Пожалуйста, загрузите PDF."

    # Запускаем пайплайн
    results = run_pipeline(pdf_path, domain)

    # Удаляем временный файл (если создавали)
    if not hasattr(file, 'name') and not isinstance(file, str):
        try:
            os.unlink(pdf_path)
        except:
            pass

    if not results:
        return None, None, "Не удалось извлечь данные. Попробуйте другой PDF или домен."

    df = pd.DataFrame(results)
    csv_path = tempfile.NamedTemporaryFile(delete=False, suffix=".csv").name
    df.to_csv(csv_path, index=False)

    return df, csv_path, "✅ Обработка завершена!"


with gr.Blocks(title="DataCon 2026 — Экстрактор химических данных") as demo:
    gr.Markdown("# 🧪 DataCon 2026 — Экстрактор химических данных")
    gr.Markdown("Загрузите PDF научной статьи и выберите домен для извлечения данных.")
    with gr.Row():
        with gr.Column(scale=1):
            file_input = gr.File(label="Загрузите PDF", file_types=[".pdf"])
            domain_dropdown = gr.Dropdown(
                choices=["benzimidazoles", "cocrystals", "complexes", "eyedrops", "nanomag"],
                label="Выберите домен",
                value="nanomag"
            )
            submit_btn = gr.Button("🔍 Извлечь данные")
        with gr.Column(scale=2):
            status_output = gr.Textbox(label="Статус", interactive=False)
            csv_output = gr.File(label="Скачать CSV")
    gr.Markdown("### 📊 Извлечённые данные")
    table_output = gr.Dataframe(label="Результаты", interactive=False)
    submit_btn.click(
        fn=process_pdf,
        inputs=[file_input, domain_dropdown],
        outputs=[table_output, csv_output, status_output]
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
