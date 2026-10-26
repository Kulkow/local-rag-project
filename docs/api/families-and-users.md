# Пользователи и семьи: запуск и API

## Запуск

В .env задайте собственные ADMIN_USERNAME (3–100 строчных латинских букв, цифр,
`_.@-`) и ADMIN_PASSWORD (12–128 символов), а также отдельный случайный JWT_SECRET
(не менее 32 байт, команда генерации есть в .env.example). Это явные bootstrap-данные, общих
учётных данных по умолчанию нет. Существующие семейные данные сохраняются.

```sh
docker compose build api migrate web-admin
make migrate
make bootstrap-admin
docker compose up -d api worker web-admin
```

Повторный bootstrap не меняет существующую запись и не сбрасывает пароль.
Изменение .env не меняет пароль пользователя в БД: используйте страницу
«Пользователи» или PUT /users/{id} от имени администратора. .env Basic для /ready
ротируется отдельно пересозданием API/worker. Не удаляйте volumes для обновления.

Web Admin: http://localhost:3000/families, пользователи:
http://localhost:3000/users. JWT хранится в Pinia и localStorage, вход сохраняется после перезагрузки
страницы и закрытия вкладки. При запуске профиль и права подтверждаются через
/auth/me. Кнопка «Выйти» отзывает все JWT пользователя и очищает localStorage.
Истёкший или отозванный токен удаляется после 401; при сетевой ошибке доступ
не выдаётся, сохранённый токен можно проверить повторно.

1. Войдите bootstrap-администратором.
2. На странице «Семьи» создайте семью и добавьте участников с именем, фамилией
   и семейной ролью. Можно изменить название/роль или удалить запись с подтверждением.
3. На странице «Пользователи» создайте логин, пароль, выберите системную роль,
   затем семью и участника. Для manager/member связь обязательна.
4. Войдите новой учётной записью: manager управляет своей семьёй, member видит
   только её состав. Управление аккаунтами доступно только admin.
5. Для отключения/смены прав/сброса пароля выберите «Изменить» и подтвердите.
   Все токены изменённого пользователя отзываются; изменение своей записи завершает вход.

Член семьи и пользователь не одно и то же. Семейная роль `parent` не даёт прав
менеджера. Связанного с аккаунтом участника нельзя удалить даже после отключения
аккаунта; перепривяжите аккаунт к другому участнику. Пользователь без связи может
иметь только системную роль admin. Животные пока не редактируются через этот UI.

## REST-контракт

API с хоста: http://localhost:8000; из браузера Nginx проксирует `/api`.
Актуальные DTO: `/docs`, `/openapi.json`; TypeScript-схема генерируется из FastAPI.
Доступ к любому /users и /families требует `Authorization: Bearer TOKEN`.

| Метод | Путь | Назначение |
|---|---|---|
| POST | /auth/login | username, password → access_token, user, expires_in |
| GET | /auth/me | Текущий пользователь |
| POST | /auth/logout | Отозвать все JWT пользователя (204) |
| GET | /users | Пользователи (admin), offset/limit |
| POST | /users | username, password, role, family_member_id (201) |
| PUT | /users/{id} | role, is_active, family_member_id, необязательный password |
| GET | /families | Только доступные семьи, offset/limit |
| POST | /families | name (admin, 201) |
| PUT | /families/{id} | name |
| DELETE | /families/{id} | Удаление семьи (admin, 204) |
| GET | /families/{id}/members | Состав, offset/limit |
| POST | /families/{id}/members | first_name, last_name, role (201) |
| PATCH | /families/{id}/members/{member_id} | Семейная role |
| DELETE | /families/{id}/members/{member_id} | Удаление членства (204) |

По умолчанию limit=50, максимум 100. Web Admin использует страницы по 20 записей.
PUT пользователя заменяет все перечисленные поля; опущенная связь становится NULL,
поэтому для manager/member её нужно передавать каждый раз. Пустой пароль не
принимается, для сохранения прежнего пароля опустите поле или передайте null.

Коды ошибок: 401 неверный/истёкший вход; 403 недостаточно прав; 404 отсутствующая
или недоступная семья/участник; 409 конфликт логина, связи или удаления; 422
ошибка полей/обязательной связи; 429 превышен лимит входа, Retry-After: 60.
Неопознанная учётная запись и неверный пароль дают одинаковый ответ.

Пример входа: команда читает JSON со stdin, не записывая пароль в shell history.
После запуска введите JSON с вашими username/password и завершите ввод Ctrl-D.
Не публикуйте полученный access_token.

```sh
curl -sS http://localhost:8000/auth/login -H 'Content-Type: application/json' --data-binary @-
```

Примеры с заменяемым токеном:

```sh
curl -sS http://localhost:8000/auth/me -H 'Authorization: Bearer YOUR_TOKEN'
curl -sS http://localhost:8000/families -H 'Authorization: Bearer YOUR_TOKEN'
curl -sS -X POST http://localhost:8000/families \
  -H 'Authorization: Bearer YOUR_TOKEN' -H 'Content-Type: application/json' \
  -d '{"name":"Example family"}'
```

## Проверка

`make check` запускает Python lint/format/mypy/pytest, экспорт OpenAPI,
генерацию TypeScript, frontend-тесты и production build в Docker.
PostgreSQL-тесты покрывают полный цикл управления, запрет чужих семей и повышения
прав, связи FK, отзыв JWT, сброс пароля, expiry, throttling и последнего admin.
Компонентные тесты Vue проверяют создание семьи, ограничение экранов по роли и
ошибки API. Они не заменяют визуальный браузерный E2E.

См. [ADR 0006](../adr/0006-identity-family-access.md) для прав и
[ADR 0007](../adr/0007-jwt-pinia.md) для JWT, хранения и ограничений.

## Результаты локальной проверки

- Миграция 0003 применена к PostgreSQL; первоначальный admin создан явной командой.
- Ruff lint и format: passed; strict mypy: passed (46 source files).
- Python pytest в Docker: 25 passed, 1 skipped. Пропущен тест Compose CLI внутри
  checks image; он отдельно выполнен на хосте и прошёл.
- Frontend: 14 тестов passed, vue-tsc и Vite production build passed при Docker build.
- `docker compose up -d --build --no-deps api worker web-admin`: выполнено;
  API, worker и Web Admin — healthy.
- Проверка через реальный Nginx: /families и /users 200; вход, /auth/me,
  списки семей/пользователей и /ready 200; logout 204; отозванный токен 401.
- Визуальный браузерный E2E не выполнялся: браузерный инструмент недоступен.
  Доступность SPA по HTTP и компонентные тесты не являются визуальной проверкой.


## Обновление на JWT

```sh
docker compose build api migrate web-admin
make migrate
docker compose up -d api worker web-admin
```

Предварительно задайте JWT_SECRET в .env. Миграция 0004 добавляет token_version;
существующие пользователи и семейные данные сохраняются. Таблица user_sessions
сохранена как неиспользуемая историческая таблица. После обновления войдите заново.
Для смены ключа измените JWT_SECRET и пересоздайте API/worker: все старые JWT
станут недействительны. На нескольких экземплярах API ключ должен быть одинаковым.

Роль member также может загружать документы в доступную семью и запускать обработку
своих документов. Это не даёт прав управления семьёй или учётными записями.
См. [политику документов](../adr/0014-member-document-upload.md).
