# ADR 0019: Доменные модули Web Admin и обязательный lint

## Что было

Vue-приложение было разделено по техническим папкам views/stores и общим API-файлам.
Правила документов и пакетная загрузка находились в компоненте; management-api
смешивал семьи, пользователей и общий HTTP. Это не было разделением по DDD-контекстам.

## Решение

```
web-admin/src/
  main.ts, App.vue             # composition root, routes, shell
  modules/
    documents/
      domain/document.ts      # frontend document model, upload/readiness policies
      application/upload-batch.ts # use case, injected upload/queue ports
      infrastructure/api.ts   # HTTP, generated DTO mapping, browser PDF/blob handling
      presentation/DocumentsView.vue
      index.ts                # public integration surface
    identity/
      domain/roles.ts         # presentation permission policy, not server authorization
      infrastructure/api.ts
      presentation/           # session store, access form, user administration
      index.ts
    families/                 # family API + presentation, public index
    rag/                      # RAG API + presentation, public index
    operations/               # readiness API + dashboard/store, public index
  shared/infrastructure/
    http.ts                   # transport/errors/401 notification, no business endpoints
    schema.ts                 # generated OpenAPI types
```

Domain не зависит от Vue, Pinia, API DTO, HTTP или других контекстов. Application
зависит только от собственного domain/application и определяет порты. UploadBatch
работает с переданными зависимостями и plain state, сохраняет ключи failed, пропускает
saved, продолжает после частичных отказов и прекращает отправку при смене сессии.
Presentation отвечает за Vue refs, состояние диалогов и отображение; инфраструктура
содержит HTTP/browser adapters. Public index — интеграционная поверхность внешнего
слоя, не импортируется внутренними domain/application.

Другие модули с простыми CRUD не получают пустые domain/application папки ради
структуры. Не дублируются серверные агрегаты и авторизация. Разрешения клиента —
только UI policy; окончательное решение остаётся в API. Форматы/лимиты/ACL API
не изменены. Исторические ADR с прежними путями описывают структуру на момент записи.

## Проверяемые границы

ESLint local rule architecture/boundaries запрещает импорты другого контекста
в обход public index, зависимости domain от внешних слоёв, application от
infrastructure/presentation, инфраструктуры от presentation. Проверяются обычные,
динамические импорты и реэкспорты. Во внутренних слоях запрещены fetch/window/
document/localStorage/sessionStorage. TypeScript/Vue проверяются ESLint; generated
schema исключена из lint, но проходит typecheck. Негативные тесты намеренно нарушают
границы и проверяют отказ линтера; поведение upload/ACL/UI покрывают прежние тесты.

Добавлены только devDependencies: ESLint, @eslint/js, typescript-eslint,
eslint-plugin-vue и globals. Они нужны для разбора Vue SFC/TypeScript и проверки
реальных импортов. Версии и транзитивные зависимости зафиксированы package-lock;
совместимость проверяется с Docker Node 22.13.0. Runtime-зависимости не добавляются.

## Команды

- npm run lint — ESLint с max-warnings=0, без изменения файлов.
- npm run lint:fix — явное исправление поддерживаемых правил.
- npm run typecheck — vue-tsc.
- npm test — unit/component/architecture tests.
- npm run build — npm автоматически запускает prebuild (lint), затем typecheck + Vite.

Dockerfile и web-checks вызывают npm run build, поэтому lint — обязательный барьер
сборки в Docker и CI через make check. Сборка не скрывает ошибки и не вызывает fix.
Генерация OpenAPI теперь направлена в src/shared/infrastructure/schema.ts.

## Результат проверки

- Чистая Docker npm ci из package-lock и сборка: passed.
- 68 unit/component/architecture tests: passed.
- ESLint 10.13.0 без предупреждений, vue-tsc и Vite: passed.
- В одноразовом контейнере добавлен запрещённый domain -> Vue import:
  npm run build завершился ошибкой architecture/boundaries до запуска Vite.
- Повторная генерация OpenAPI дала идентичный shared/infrastructure/schema.ts.
- Web Admin обновлён, healthy; /, /documents, /rag и JS bundle доступны.
- Визуальный браузерный E2E не выполнялся; проверены компонентные тесты и HTTP.
- npm audit: 8 уязвимостей (3 moderate, 3 high, 2 critical) в прежнем стеке
  Vue/Vite/Vitest и его зависимостях. ESLint-пакеты в отчёте не указаны.
  Автоматический force upgrade не применялся; обновление runtime/build/test стека
  требует отдельной проверки совместимости. Это ограничение не скрыто прохождением lint.

Уязвимости, указанные в результате этого среза, исправляются последующим
[ADR 0020](0020-web-dependency-security-update.md); исходный отчёт выше сохранён
как исторический результат, не как текущее состояние зависимостей.
