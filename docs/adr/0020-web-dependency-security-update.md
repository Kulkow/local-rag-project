# ADR 0020: Исправление npm audit Web Admin

## Причина и решение

После добавления DDD/lint npm audit сообщал о 8 уязвимостях прежних Vue/Vite/Vitest
и их зависимостей, включая critical. Исправляются зависимости, а не подавляется
отчёт. Не используются audit fix --force, legacy-peer-deps, overrides на несовместимые
пакеты или исключение devDependencies из аудита.

Прямые обновления:

- Vue 3.5.13 -> 3.5.44 (согласованные Vue/compiler/server-renderer транзитивные пакеты).
- Vite 6.0.7 -> 6.4.5: сохраняется основной build tool и его major.
- @vitejs/plugin-vue 5.2.1 -> 5.2.4: совместимая ветка для Vite 6.
- Vitest 2.1.8 -> 4.1.12: исправленная ветка для замечаний к Vitest/mocker;
  старые vite-node/tinypool выводятся из дерева зависимостей тестового runner.

Версии зафиксированы package.json/package-lock.json. Сохраняются Docker Node
22.13.0, PrimeVue, Pinia, Vue Router, ESLint и DDD-границы. npm 11.21.1 закреплён
в Dockerfile/packageManager и генерации lockfile Makefile. npm 10 resolver столкнулся
с ошибкой при обновлении прежнего peer graph; lockfile пересобран
с нуля через npm 11.21.1 в чистом контейнере по фиксированным прямым версиям. Транзитивные версии
повторно разрешены и затем фиксируются новым lockfile. Итог проверяется
чистым npm ci, аудитом, тестами и сборкой, а не обходом peer constraints.

## Проверки и повторяемость

npm run audit проверяет всё дерево, включая devDependencies, и завершается ошибкой
при любой найденной уязвимости начиная с low. В CI audit запускается отдельно после
make check. npm run build сохраняет prebuild lint, typecheck и Vite: успешная локальная
сборка не требует актуального ответа npm registry. Аудит требует сети и отражает
известные registry замечания на момент запуска, а не гарантию отсутствия всех рисков.

Верификация: чистый Docker npm ci; npm run audit; все 68 unit/component/
architecture tests; prebuild ESLint, vue-tsc, Vite; обновление Web Admin и HTTP smoke
маршрутов и JavaScript assets. Тесты не ослабляются для прохождения обновления.

Источники для совместимости и миграции:
- [Vitest 4 migration](https://v4.vitest.dev/guide/migration.html).
- npm package metadata/peerDependencies/engines и npm audit advisory graph.


## Результат

- Новый lockfile разрешён через npm 11.21.1 без force/overrides.
- Чистый Docker npm ci: passed; npm audit полного дерева: **0 vulnerabilities**.
- Все прежние 68 тестов прошли на Vitest 4.1.12 без ослабления проверок.
- Prebuild ESLint, vue-tsc, Vite 6.4.5 и production Docker image: passed.
- npm run audit в свежем CI web-checks image: 0 vulnerabilities, exit 0.
- Web Admin обновлён и healthy; /, /documents, /rag и JS bundle: HTTP smoke passed.
- GitHub Actions не запускался из этой сессии; проверена добавленная audit-команда
  локально в том же образе. Визуальный браузерный E2E не выполнялся.
