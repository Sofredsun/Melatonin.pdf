# ChemX Extractor — экстракция химических данных из научных статей

ChemX Extractor — система автоматической экстракции структурированных химических данных из PDF научных статей для финальной задачи DataCon'26. По тексту статьи пайплайн восстанавливает таблицу измерений: названия соединений, SMILES, экспериментальные свойства и условия. Результат — CSV, совместимый с бенчмарком ChemX (NeurIPS 2025).

Подход: **имена и числовые поля** извлекает LLM через OpenAI-совместимый шлюз, **структуры (SMILES)** восстанавливаются из имён через OPSIN/PubChem и валидируются RDKit. Качество оценивается метрикой **Macro-F1**.

## Контекст задачи

DataCon'26: разработать систему экстракции, которая превосходит базовый single-agent подход ChemX, и продемонстрировать её через веб-интерфейс. Бенчмарк содержит 10 датасетов; каждая строка — один химический объект из статьи. В оценке участвуют только **химические поля** (SMILES, свойства, условия), поля источника (DOI, страница, тип источника) не учитываются.

## Цель проекта

- Реализовать многошаговый пайплайн PDF → текст → LLM → резолвер структур → CSV
- Поддержать несколько доменов ChemX: кокристаллы, бензимидазолы, оксазолидиноны
- Дать веб-интерфейс для загрузки PDF и скачивания результата
- Обеспечить CLI-запуск без UI для пакетной обработки и отладки LLM

## Поддерживаемые домены

| Домен | Модуль | Что извлекается |
|-------|--------|-----------------|
| `cocrystals` | `src/cocrystals/` | Кокристаллы: API, коформер, мольное соотношение, SMILES |
| `benzimidazoles` | `src/benzimidazole/` | Антимикробная активность бензимидазолов: MIC, бактерии, SMILES |
| `oxazolidinones` | `src/oxazolidinones/` | MIC/MBC оксазолидинонов: соединение, бактерия, значение, SMILES |

## Запуск проекта

### Требования

- Python 3.10+
- Java (для OPSIN / систематических имён). На macOS: `brew install openjdk`
- Доступ к LLM через OpenAI-совместимый API (корпоративный gateway, LiteLLM, vsegpt и т.п.)

### Установка

```bash
git clone <repo-url>
cd Melatonin.pdf
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Настройка LLM

Скопируйте `.env.example` в `.env` и укажите параметры шлюза:

```ini
DEFAULT_BASE_URL=https://your-ai-gateway.example/v1
DEFAULT_API_KEY=replace-me
DEFAULT_MODEL=qwen
```

Все модули экстракции читают эти переменные через `src/llm_gateway.py`. Ответы LLM кэшируются в `.cache/llm_extractions/`, чтобы не платить повторно за один и тот же PDF.

---

## Веб-интерфейс (Gradio)

Интерфейс для демонстрации на DataCon: загрузка PDF, выбор домена, просмотр таблицы и скачивание CSV.

```bash
source .venv/bin/activate
python app/gradio_app.py
```

После старта откройте **http://localhost:7860**

1. Загрузите PDF научной статьи
2. Выберите домен: `cocrystals`, `benzimidazoles` или `oxazolidinones`
3. Нажмите «Извлечь данные»
4. Скачайте CSV или просмотрите таблицу на странице

---

## CLI: запуск без интерфейса

Каждый домен — отдельный модуль с CLI. Команды ниже напрямую вызывают LLM (если не указан `--no-llm`).

### Кокристаллы

```bash
# одна статья
python3 -m src.cocrystals.run data_gold/10.3390_cryst9110553_crystal.pdf --out outputs/prediction.csv

# вся папка с PDF
python3 -m src.cocrystals.run data_full --out outputs/prediction.csv

# только первые 3 статьи
python3 -m src.cocrystals.run data_full --limit 3 --out outputs/prediction.csv
```

### Бензимидазолы

```bash
python3 -m src.benzimidazole.run path/to/article.pdf --out outputs/benzimidazole_prediction.csv
python3 -m src.benzimidazole.run data_full --out outputs/benzimidazole_prediction.csv
```

### Оксазолидиноны

```bash
python3 -m src.oxazolidinones.run path/to/article.pdf --out outputs/oxazolidinones_prediction.csv
python3 -m src.oxazolidinones.run src/oxazolidinones --out outputs/oxazolidinones_prediction.csv
```

### Полезные флаги CLI

| Флаг | Назначение |
|------|------------|
| `--limit N` | обработать только первые N PDF |
| `--no-llm` | без LLM (только каталог/резолвер) |
| `--no-pubchem` | не ходить в PubChem (только OPSIN + локальный каталог) |
| `--refresh-llm-cache` | игнорировать кэш и заново вызвать LLM |
| `--no-catalog-fallback` | *(только cocrystals)* не подставлять строки из каталога, если LLM ничего не нашёл |
| `--no-catalog-hints` | *(только cocrystals)* не дозаполнять пустые поля из каталога |
| `--no-catalog-reconcile` | *(только cocrystals)* не сверять извлечённые строки с каталогом по DOI |

«Честный» прогон кокристаллов без подсказок каталога:

```bash
python3 -m src.cocrystals.run data_full --no-catalog-fallback --no-catalog-hints --no-catalog-reconcile
```

### Оценка качества (Macro-F1)

Для домена кокристаллов — локальный скрипт сравнения prediction vs gold:

```bash
python3 -m eval.main --pred outputs/prediction.csv --gold data_gold/10.3390_cryst9110553.csv
```

Полная оценка по бенчмарку ChemX — через `eval/metric_calc.py` и эталоны в `ChemX/datasets/`.

---

## Как работает пайплайн

```
PDF
 ├─ text.py        PyMuPDF: PDF → текст (в памяти)
 ├─ text.py        метаданные: DOI, журнал, год, title
 ├─ extractor.py   LLM: JSON со списком объектов (имена, свойства, условия)
 ├─ resolver.py    имя → SMILES (кэш → каталог → OPSIN → PubChem) → RDKit
 └─ schema.py      сборка строки CSV
                      │
                      ▼
                 prediction.csv ──→ eval/ Macro-F1
```

- **LLM.** В модель уходит сжатый контекст статьи (abstract + релевантные фрагменты), а не весь PDF. Ответ — строго JSON, кэшируется на диск.
- **Резолвер.** SMILES не берётся из текста статьи: для каждого имени по цепочке OPSIN → PubChem → RDKit-канонизация + InChIKey.
- **Каталог** (`data/catalog.csv`, только cocrystals). Может дозаполнять пропуски для известных DOI; для честной оценки отключайте флагами `--no-catalog-*`.

---

## Структура репозитория

```
app/                  Gradio веб-интерфейс
src/
  cocrystals/         пайплайн кокристаллов
  benzimidazole/      пайплайн бензимидазолов
  oxazolidinones/     пайплайн оксазолидинонов
  llm_gateway.py      клиент LLM (LangChain + OpenAI-compatible API)
  pipeline.py         общая точка входа для UI
eval/                 метрики Macro-F1
```

## Зависимости

`PyMuPDF` (PDF), `rdkit` (SMILES/InChIKey), `PubChemPy` + `py2opsin` (имя → структура), `langchain-openai` + `openai` (LLM), `gradio` (UI), `python-dotenv` (конфиг).

## Ограничения

- **OSR (картинка → SMILES) не реализован** — если у соединения только нарисованная формула без имени, структура не извлечётся.
- **PubChem — онлайн** с rate limits; ответы кэшируются в `.cache/`.
- Реализованы 3 из 10 датасетов ChemX; остальные домены — в планах.
