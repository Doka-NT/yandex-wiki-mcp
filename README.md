# yandex-wiki-mcp

MCP (Model Context Protocol) сервер для чтения страниц Яндекс Вики от имени пользователя.

Сервер поддерживает **нескольких пользователей одновременно**: каждый пользователь регистрирует свой OAuth-токен по email, токен хранится в памяти 2 часа.

## Возможности

| Инструмент | Описание |
|---|---|
| **`register_token`** | Регистрирует OAuth-токен пользователя (по email). Токен хранится 2 часа. |
| **`read_page`** | Читает содержимое страницы Яндекс Вики по URL от имени пользователя. |

## Требования

- Python ≥ 3.10
- [uv](https://docs.astral.sh/uv/) (рекомендуется) или `pip`
- Персональный OAuth-токен Яндекс с правами `wiki:read`

## Получение OAuth-токена

1. Зайдите на [https://oauth.yandex.ru](https://oauth.yandex.ru) и создайте новое приложение.
2. Выдайте приложению права `wiki:read` (чтение Вики).
3. Получите токен и скопируйте его.

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

```bash
yandex-wiki-mcp
# или напрямую:
python -m yandex_wiki_mcp.server
```

Никаких переменных окружения не требуется — каждый пользователь регистрирует токен через MCP-инструмент.

## Подключение к Claude Desktop

Добавьте в `~/.config/claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "yandex-wiki": {
      "command": "yandex-wiki-mcp"
    }
  }
}
```

## Использование

### 1. Зарегистрировать токен (один раз, действует 2 часа)

```
register_token(
  email="user@yandex.ru",
  oauth_token="<ваш_oauth_токен>"
)
```

### 2. Читать страницу

```
read_page(
  url="https://wiki.yandex.ru/org/team/page",
  email="user@yandex.ru"
)
```

Возвращает текст страницы в формате вики-разметки.

> **Примечание:** Несколько пользователей могут зарегистрировать свои токены и работать одновременно — токены хранятся независимо, идентифицируются по email.

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

