# yandex-wiki-mcp

MCP (Model Context Protocol) сервер для чтения страниц Яндекс Вики от имени пользователя.

Сервер поддерживает **нескольких пользователей одновременно**: каждый пользователь запускает сервер со своим email, единоразово регистрирует OAuth-токен (напрямую через MCP-инструмент, не через LLM), после чего токен хранится в памяти 2 часа.

## Возможности

| Инструмент | Описание |
|---|---|
| **`register_token(oauth_token)`** | Регистрирует OAuth-токен текущего пользователя. Email берётся из `YANDEX_WIKI_USER_EMAIL`. Токен хранится 2 часа. |
| **`read_page(url)`** | Читает содержимое страницы Яндекс Вики по URL. Email берётся из `YANDEX_WIKI_USER_EMAIL`. Если токен не зарегистрирован или истёк — возвращает инструкцию со ссылкой для получения токена. |

## Требования

- Python ≥ 3.10
- [uv](https://docs.astral.sh/uv/) (рекомендуется) или `pip`

## Установка

```bash
uv pip install .
```

Или для разработки (включая тесты):

```bash
uv pip install -e ".[dev]"
```

## Настройка

Укажите email Яндекс-аккаунта в переменной окружения:

```bash
export YANDEX_WIKI_USER_EMAIL=user@yandex.ru
```

Это единственная переменная окружения — токен передавать в env не нужно.

## Запуск

```bash
yandex-wiki-mcp
# или напрямую:
python -m yandex_wiki_mcp.server
```

## Подключение к Claude Desktop

Добавьте в `~/.config/claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "yandex-wiki": {
      "command": "yandex-wiki-mcp",
      "env": {
        "YANDEX_WIKI_USER_EMAIL": "user@yandex.ru"
      }
    }
  }
}
```

## Использование

### Шаг 1 — Зарегистрировать токен (один раз, действует 2 часа)

1. Получите OAuth-токен на [https://oauth.yandex.ru](https://oauth.yandex.ru) (нужно право `wiki:read`).
2. Вызовите инструмент **напрямую** (не через LLM-чат):

```
register_token(oauth_token="<ваш_oauth_токен>")
```

Токен не нужно вставлять в переписку с LLM — достаточно вызвать инструмент один раз.

### Шаг 2 — Читать страницы

```
read_page(url="https://wiki.yandex.ru/org/team/page")
```

Возвращает текст страницы в формате вики-разметки.

Если токен не зарегистрирован или истёк, `read_page` вернёт инструкцию с ссылкой для получения нового токена — повторите шаг 1.

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


