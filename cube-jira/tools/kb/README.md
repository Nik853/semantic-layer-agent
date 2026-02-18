# Knowledge Base — подсказки для генерации Cube-моделей

Knowledge Base (KB) — это YAML-файл с описаниями таблиц и колонок вашего домена.
Data loader использует KB для обогащения автоматически сгенерированных описаний.

## Зачем

GigaChat генерирует описания на основе имён колонок и примеров данных, но:
- Может не знать доменную специфику вашего хранилища
- Иногда возвращает невалидный JSON (fallback)
- Не знает какие доп. меры (measures) имеют смысл для таблицы

KB решает это: даёт точные описания, подсказки по колонкам и рекомендуемые меры.

## Подключение

```yaml
# config.yml
knowledge_base_path: "./kb/jira_kb.yml"
```

Без KB data_loader работает как и раньше — только GigaChat.

## Формат файла

```yaml
# Паттерн имени таблицы (без схемы, регистр неважен)
имя_таблицы:
  title: "Русское название (2-3 слова)"
  description: "Описание таблицы (1-2 предложения)"

  # Подсказки по колонкам (необязательно)
  column_hints:
    имя_колонки: "Что хранит эта колонка"
    другая_колонка: "Описание"

  # Дополнительные меры для Cube (необязательно)
  suggested_measures:
    - name: имя_меры
      sql: "SQL-выражение с {CUBE}.column"
      type: count | sum | avg | min | max | count_distinct
      title: "Русское название"
      description: "Что считает эта мера"
```

## Сопоставление имён

Паттерн из KB сопоставляется с реальным именем таблицы в БД нечётко:

| Паттерн в KB | Совпадёт с таблицей в БД |
|---|---|
| `jiraissue` | `jiraissue`, `jira_issue`, `issues`, `jira_issues` |
| `priority` | `priority`, `priorities`, `issue_priorities` |
| `projectversion` | `projectversion`, `project_versions`, `versions` |
| `user` | `user`, `users`, `cwd_user` |

Логика: нормализация разделителей → единственное число → удаление префиксов (jira*, project*) → суффиксы → подстроки.

## Готовые KB

| Файл | Домен | Таблиц |
|------|-------|--------|
| `jira_kb.yml` | Atlassian JIRA | 22 |

## Создание своей KB

```bash
cp template_kb.yml my_domain_kb.yml
# Заполните описания ваших таблиц
# Укажите путь в config.yml → knowledge_base_path
```
