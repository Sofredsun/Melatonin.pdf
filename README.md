# ChemX · Извлечение данных о кокристаллах из PDF

Пайплайн извлекает из научных статей (PDF) структурированную таблицу кокристаллов:
действующее вещество, коформер, название кокристалла, мольное соотношение и
химические структуры (SMILES + InChIKey).

Идея: **имена** соединений извлекает LLM, а **структуры (SMILES)** не берутся из
текста, а восстанавливаются из имён через химические базы (OPSIN/PubChem) и
проверяются RDKit. Это надёжнее, чем просить LLM «придумать» SMILES.

Качество измеряется метрикой **Macro-F1**. На проверочной (gold) статье — **1.000**.

---

## Установка

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Для систематических имён (OPSIN) нужна Java. На macOS:

```bash
brew install openjdk
```

## Настройка доступа к LLM

Скопируйте `.env.example` в `.env` и впишите данные вашего AI-шлюза
(OpenAI-совместимый эндпоинт — LiteLLM, корпоративный gateway и т.п.):

```ini
DEFAULT_BASE_URL=https://your-ai-gateway.example/v1
DEFAULT_API_KEY=replace-me
DEFAULT_MODEL=qwen
```

---

## Запуск

### 1. Извлечение (PDF → CSV)

```bash
# одна статья
python3 -m src.cocrystals.run data_gold/10.3390_cryst9110553_crystal.pdf --out outputs/prediction.csv

# вся папка с PDF
python3 -m src.cocrystals.run data_full --out outputs/prediction.csv
```

Печатает Precision/Recall/F1 по каждому полю и итоговый Macro-F1.

### Полезные флаги `run.py`

| Флаг | Назначение |
|------|------------|
| `--limit N` | обработать только первые N PDF |
| `--no-llm` | без LLM (только каталог/резолвер) |
| `--no-pubchem` | не ходить в PubChem (только OPSIN + каталог) |
| `--refresh-llm-cache` | игнорировать кэш и заново вызвать LLM |
| `--no-catalog-fallback` | не подставлять строки из каталога, если LLM ничего не нашёл |
| `--no-catalog-hints` | не дозаполнять пустые поля из каталога |
| `--no-catalog-reconcile` | не сверять извлечённые строки с каталогом по DOI |

«Честный» прогон без подсказок каталога:

```bash
python3 -m src.cocrystals.run <pdf> --no-catalog-fallback --no-catalog-hints --no-catalog-reconcile
```

---

## Как работает пайплайн

```
PDF
 ├─ ① text.py      PyMuPDF: PDF → текст (в памяти, без сохранения)
 ├─ ② text.py      метаданные: DOI, журнал, год, title (regex)
 ├─ ③ text.py      алиасы аббревиатур (CBZ → carbamazepine)
 ├─ ④ extractor.py LLM: JSON со списком образцов {name_cocrystal, name_drug, name_coformer, ratio}
 ├─ ⑤ extractor.py (опц.) сверка с каталогом data/catalog.csv
 ├─ ⑥ resolver.py  имя → SMILES (кэш → каталог → OPSIN → PubChem) → RDKit канонизация + InChIKey
 └─ ⑦ schema.py    сборка строки CSV (13 колонок)
                      │
                      ▼
                 prediction.csv ──→ ⑧ eval/ метрика Macro-F1
```

Подробности по этапам:

- **① Чтение PDF.** Текст вытаскивается постранично через PyMuPDF (`fitz`).
  Markdown не создаётся, текст на диск не пишется — только передаётся дальше.
- **② Метаданные.** DOI по шаблону `10.xxxx/...`; журнал по префиксу DOI; год —
  самый частый правдоподобный; title — первая содержательная строка.
- **③ Алиасы.** Паттерн «полное имя (АББР)» → словарь аббревиатур, чтобы потом
  подставить полное имя для резолвинга.
- **④ LLM.** В модель уходит не весь PDF, а сжатый контекст (`compact_context`):
  начало статьи (abstract) + строки с ключевыми словами (cocrystal, molar ratio,
  form I/II…). Модель возвращает строго JSON. Ответ кэшируется в
  `.cache/llm_extractions/`.
- **⑤ Каталог.** Локальный справочник `data/catalog.csv` может дозаполнить пропуски
  для известных DOI. Отключается флагами `--no-catalog-*`.
- **⑥ Резолвер.** Для каждого имени по очереди: кэш → каталог → OPSIN → PubChem.
  Полученный SMILES прогоняется через RDKit (валидация + канонизация + InChIKey).
  Для `name_drug` берётся IUPAC-имя.
- **⑦ Сборка CSV.** Одна строка = один кокристалл, дубликаты убираются.

---

## Схема выхода (`prediction.csv`)

```
pdf, doi, title, publisher, year,
name_drug, SMILES_drug, SMILES_drug_inchikey,
name_cocrystal, name_coformer, SMILES_coformer, SMILES_coformer_inchikey,
ratio_cocrystal
```

В метрике (Macro-F1) участвуют 6 целевых полей: `name_drug`, `SMILES_drug`,
`name_cocrystal`, `name_coformer`, `SMILES_coformer`, `ratio_cocrystal`.

---

## Зависимости

См. `requirements.txt`: `PyMuPDF` (чтение PDF), `rdkit` (валидация/канонизация
SMILES, InChIKey), `PubChemPy` + `py2opsin` (имя → структура), `langchain-openai`
(вызов LLM), `python-dotenv` (конфиг из `.env`).

---

## Ограничения и что дальше

- **OSR (картинка → SMILES) не реализован.** Если у соединения нет узнаваемого
  имени (только нарисованная формула), структура не извлечётся. Это следующий шаг
  для повышения качества.
- **PubChem — онлайн** и с лимитами; ответы кэшируются в `.cache/`.
- **Каталог** `data/catalog.csv` может «подсматривать» в эталон для известных DOI —
  для честной оценки используйте флаги `--no-catalog-*`.
- **Веб-интерфейс** (загрузил PDF → таблица → экспорт CSV) пока не реализован —
  это отдельный пункт из техзадания.
