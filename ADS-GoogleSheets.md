# Инструкция по использованию ADS-GoogleSheets

## Что это такое?

Программа для автоматической синхронизации данных из AdsPower в Google Таблицы. Берет файлы `*.txt` из папки AdsPower и автоматически загружает их в вашу Google Таблицу.

---

## Подготовка (делается один раз)

### 1. Установка программы

Склонируйте репозиторий или скачайте код, затем откройте терминал в папке с программой и выполните:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install .[dev]
```

### 2. Настройка доступа к Google Таблицам

1. Зайдите в Google Cloud Console
2. Создайте сервисный аккаунт с ролью **Editor** для Google Sheets
3. Скачайте JSON-файл с ключами (например, `service-account.json`)
4. Откройте вашу Google Таблицу и дайте доступ email'у сервисного аккаунта (он указан в JSON-файле)

### 3. Настройка конфигурации

В папке с программой есть файл `config.toml` - откройте его и настройте:

- `spreadsheet_id` - ID вашей таблицы (из URL)
- `credentials_path` - путь к JSON-файлу с ключами
- `worksheet_title` - имя листа в таблице
- Остальные настройки можно оставить по умолчанию

---

## Как запускать

### Разовый запуск

Проверить и загрузить данные один раз:

```bash
ads-google-sheets --config /путь/к/config.toml
```

### Тестовый запуск (Dry Run)

Посмотреть что будет, но не загружать данные:

```bash
ads-google-sheets --config /путь/к/config.toml --dry-run
```

### Указать конкретный лист

```bash
ads-google-sheets --config /путь/к/config.toml --worksheet-title "Отчёт"
```

### Автоматический режим

Программа сама следит за новыми файлами:

- Вариант 1: В `config.toml` поставьте `watch = true` в секции `[processing]`
- Вариант 2: Запустите с флагом `--watch`

---

## Полезные настройки

### Секция [synchronization]

```toml
[synchronization]
# Какие столбцы проверять на изменения
watch_columns = ["A", "B"]

# Какие столбцы обновлять при изменениях
update_columns = ["B", "C"]

# Принудительная подстановка значений
[synchronization.replacements]
C = "static value"

# Явное сопоставление столбцов
[synchronization.column_mapping]
A = 0
F = 1
```

### Секция [processing]

```toml
[processing]
max_cell_length = 50000  # Максимальная длина ячейки
skip_header_rows = 1  # Сколько строк заголовка пропустить
watch = false  # Режим непрерывного наблюдения
dry_run = false  # Тестовый режим без реальных действий
```

### Переменные окружения

Можно переопределить настройки через переменные:

- `ADS_SPREADSHEET_ID` - ID таблицы
- `ADS_WORKSHEET_TITLE` - название листа
- `ADS_SERVICE_ACCOUNT_JSON` - путь к JSON-файлу
- `ADS_DRY_RUN` - режим dry-run

---

## Если что-то пошло не так

- Проверьте логи программы
- Убедитесь, что сервисный аккаунт имеет доступ к таблице
- Попробуйте запустить с `--dry-run` для диагностики
- Проверьте правильность путей в config.toml
