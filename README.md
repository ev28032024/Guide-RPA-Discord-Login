### Сценарий использования для работы с RPA Discord — Login
---
**1.** Открываем две вкладки в терминале.

**2.** Запускаем в первой вкладке софт ADS-GoogleSheets (--watch) и во второй вкладке hCaptcha-Challenger

**3.** Запускаем RPA Discord — Login

**ИТОГ:** RPA выполняет авторизацию в аккаунты Discord, при наличии hCaptcha софт подхватывает её и производит решение, а через ADS-GoogleSheets результаты авторизации записываются в Google таблицу.

### Репозитории
---
>https://github.com/ev28032024/ADS-GoogleSheets
>https://github.com/QIN2DIM/hcaptcha-challenger
