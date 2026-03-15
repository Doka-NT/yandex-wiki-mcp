# yandex-wiki-mcp

MCP (Model Context Protocol) сервер для чтения страниц Яндекс Вики от имени пользователя.

## Возможности

- **`read_page`** — читает содержимое страницы Яндекс Вики по её URL.

## Требования

- Python ≥ 3.10
- [uv](https://docs.astral.sh/uv/) (рекомендуется) или `pip`
- OAuth-токен Яндекс с доступом к Яндекс Вики

## Получение OAuth-токена

1. Зайдите на [https://oauth.yandex.ru](https://oauth.yandex.ru) и создайте новое приложение.
2. Выдайте приложению права `wiki:read` (чтение Вики).
3. Получите токен и сохраните его.

Подробнее: [Документация Яндекс Вики API — Доступ](https://yandex.ru/support/wiki/api-ref/access.html)

## Установка

```bash
uv pip install .
```

Или для разработки (включая тесты):

```bash
uv pip install -e ".[dev]"
```

## Запуск

Перед запуском экспортируйте OAuth-токен:

```bash
export YANDEX_WIKI_OAUTH_TOKEN=<ваш_токен>
```

Запустите сервер (режим stdio):

```bash
python -m yandex_wiki_mcp.server
# или через точку входа:
yandex-wiki-mcp
```

## Подключение к Claude Desktop

Добавьте в `~/.config/claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "yandex-wiki": {
      "command": "yandex-wiki-mcp",
      "env": {
        "YANDEX_WIKI_OAUTH_TOKEN": "<ваш_токен>"
      }
    }
  }
}
```

## Использование инструмента

```
read_page(url="https://wiki.yandex.ru/org/team/page")
```

Возвращает текст страницы в формате вики-разметки.

## Структура проекта

```
yandex-wiki-mcp/
├── pyproject.toml
├── README.md
├── src/
│   └── yandex_wiki_mcp/
│       ├── __init__.py
│       └── server.py      # MCP сервер
└── tests/
    └── test_server.py     # Тесты
```

## Тесты

```bash
python -m pytest tests/ -v
```
