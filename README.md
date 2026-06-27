# PDF to Markdown Converter with Candidate Extraction

Инструмент для извлечения контента из PDF-документов и конвертации в Markdown формат с сохранением изображений и векторной графики.

## Структура проекта

```
.
├── data/
│   └── pdfs/                           # Исходные PDF файлы
├── external/                           # Внешние зависимости от ChemX
├── results/
│   └── samples/
│       └── sample_<name>/              # Результаты обработки каждого PDF
│           ├── crops/                  # Извлеченные изображения и графики
│           ├── candidates.json         # Метаданные извлеченных элементов
│           ├── <name>.md               # Конвертированный Markdown
│           └── pdf_to_md_report.json   # Отчет о конвертации
└── src/
    ├── extract_candidates.py
    └── pdf_to_md.py
```

## Возможности

### extract_candidates.py
- **Извлечение текстовых блоков** с сохранением bounding box
- **Детектирование изображений** растровая графика
- **Обнаружение векторной графики** химические структуры, схемы, диаграммы
- **Автоматическое объединение** разрезанных изображений
- **Дедупликация** объектов через IoU (Intersection over Union)
- **Фильтрация boilerplate** контента (логотипы, CC BY плашки)
- **Распознавание таблиц** без границ (borderless tables)
- **Таймаут обработки** для зависающих PDF
- **Постраничная обработка** с возможностью восстановления

### pdf_to_md.py
- **Конвертация PDF в Markdown** с использованием pymupdf4llm
- **Интеграция извлеченных изображений** в markdown документ
- **Валидация результата** сверка количества изображений
- **Очистка от шума** picture placeholders
- **Генерация отчета** о конвертации

## Установка

```bash
git clone https://github.com/Sofredsun/Melatonin.pdf
cd Melatonin.pdf
python -m venv .venv
source .venv/bin/activate  # На Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Использование

### Шаг 1: Извлечение кандидатов

```bash
# Обработка всех PDF в data/pdfs/
python src/extract_candidates.py
```

**Результат:**
- `results/samples/sample_<name>/crops/` - извлеченные изображения
- `results/samples/sample_<name>/candidates.json` - метаданные

### Шаг 2: Конвертация в Markdown

```bash
# Конвертация всех PDF (требует предварительно запущенный extract_candidates.py)
python src/pdf_to_md.py
```

**Результат:**
- `results/samples/sample_<name>/<name>.md` - markdown файл
- `results/samples/sample_<name>/pdf_to_md_report.json` - отчет