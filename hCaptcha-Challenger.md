# Инструкция по использованию hCaptcha Challenger

## Что это такое?

**hCaptcha Challenger** - это библиотека для автоматического решения hCaptcha с использованием искусственного интеллекта. Программа использует мультимодальные большие языковые модели (LLM) для распознавания и решения различных типов капчи без использования сторонних антикапча-сервисов или Tampermonkey скриптов.

### Ключевые особенности

- ✅ Не требует сторонних антикапча-сервисов
- ✅ Не использует скрипты Tampermonkey
- ✅ Работает через Playwright (поддержка любых браузеров)
- ✅ Использует AI для решения капчи (AI vs AI)
- ✅ Поддерживает несколько типов hCaptcha заданий

---

## Поддерживаемые типы капчи

| Тип задания | Описание |
|------------|----------|
| **image_label_binary** | Выбор изображений с определенным объектом (классическая капча) |
| **image_label_area_select: point** | Указание точек на изображении |
| **image_label_area_select: bounding box** | Выделение областей рамкой |
| **image_label_multiple_choice** | Множественный выбор |
| **image_drag_drop** | Перетаскивание элементов |

---

## Установка

### Требования

- Python 3.8+ (+ uv) [https://docs.astral.sh/uv/getting-started/installation/] 
- Playwright
- API ключ от Google Gemini

### Установка через uv (рекомендуется)

```bash
uv venv
source .venv/bin/activate
uv pip install hcaptcha-challenger
playwright install
```

### Установка через pip

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install hcaptcha-challenger
playwright install
```

---

## Настройка

### Получение API ключа Google Gemini

1. Перейдите на [Google AI Studio](https://aistudio.google.com/apikey)
2. Создайте новый API ключ
3. Сохраните ключ - он понадобится для работы

### Конфигурация

1. В корневом каталоге создать файл .env и добавить в него строки
```bash
GEMINI_API_KEY=<КЛЮЧ>

CHALLENGE_CLASSIFIER_MODEL=gemini-2.5-flash
IMAGE_CLASSIFIER_MODEL=gemini-2.5-flash
SPATIAL_POINT_REASONER_MODEL=gemini-2.5-flash
```

2. Скачать скрипт для подключения проекта к AdsPower
