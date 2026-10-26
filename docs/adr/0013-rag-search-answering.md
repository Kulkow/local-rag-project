# ADR 0013: Авторизованный поиск и ответы с цитатами

## Решение

Подключаем нестриминговый RAG поверх существующего ingestion. POST /rag/search
возвращает найденные выдержки без chat-вызова; POST /rag/ask добавляет локальный
Ollama qwen3:4b. Режимы keyword и vector — отдельные baseline algorithms.
Hybrid/RRF и reranking добавлены позднее в ADR 0023. LangGraph, SSE и evaluation
management пока не реализованы.
Новых компонентов инфраструктуры, зависимостей и миграций нет.

Keyword использует PostgreSQL generated search_vector ('simple') и search_vector_ru
('russian'), plainto_tsquery и ts_rank_cd. Это AND-поиск по словам с русским
стеммингом: полный естественный вопрос может совпадать хуже короткой фразы. Vector использует ту же embedding-модель
и digest/размерность, что ingestion. При несовместимом индексе нужен reindex;
не выполняем сравнение разных embedding spaces.

## Авторизация до evidence

Вопрос содержит только family_id, question, retrieval_mode и top_k. actor получается
из проверенного JWT. Сначала проверяется доступ к семье и выбираются только indexed
документы с подходящим checksum, visibility и активной учётной записью/token_version.
Для не-admin обязательны live membership и owner/family visibility. Максимум 500
индексов в scope; превышение даёт 429, без широкого поиска и тихого обрезания ACL.

Qdrant получает family_id AND authorized document_ids AND active generations ДО
поиска. Это соответствует [фильтрам Qdrant 1.12](https://api.qdrant.tech/v-1-12-x/api-reference/search/points).
Payload не содержит текста. После поиска SQL повторно проверяет scope, chunk/document
identity, checksum, indexed state и generation, и только затем читает текст.
Подложный/устаревший кандидат исключается. Keyword фильтрует scope в самом SQL.
Права, индекс и токен дополнительно проверяются перед chat и перед выдачей ответа;
изменение evidence даёт 409, отзыв токена — 401. Текст не передаётся модели до этих
проверок. Mid-request revocation не может отменить уже отправленный локальной модели
контекст; конечный ответ повторно проверяется до возврата клиенту.

family_id — существующая область авторизации, не новая универсальная tenant-модель.
Даже admin явно выбирает одну семью. Авторизация не делегируется LLM.

## Генерация и цитаты

Ввод question ограничен 2000 символами, top_k — 1..8, context — 6000 символов.
В ответ возвращаются именно выдержки, переданные генератору. Источники маркируются
сервером 1..N. Модель получает system-policy и отдельный JSON user payload с вопросом
и evidence. Документы — недоверенные данные; инструменты/сеть/файловая система модели
не предоставляются. System запрещает следовать инструкциям источников и использовать
внешние знания. Thinking отключён, chain-of-thought в ответ не включается.

[Ollama structured outputs](https://github.com/ollama/ollama/blob/main/docs/api.md)
задаёт схему answer/citations/insufficient_evidence. Приложение проверяет типы,
допустимые номера, inline [n] и их принадлежность citations. Если модель вернула допустимые номера
только в structured array, сервер добавляет эти маркеры к тексту. Группы [1,2]
нормализуются в отдельные ссылки. Неизвестные номера не исправляются. Неизвестные/пустые
цитаты, некорректный JSON, либо признанная моделью нехватка данных дают безопасный
abstained с фиксированным сообщением. Нет evidence — нет chat-вызова. Существование
цитат не доказывает семантическую faithfulness: модель может ошибаться. Это требует
отдельного golden evaluation и человеческой проверки, которые здесь не заявляются.
Prompt-policy снижает injection risk, но не доказывает устойчивость произвольной модели.

Vector threshold RAG_MIN_VECTOR_SCORE=0.35 — исходный operating default, не
калиброванный quality gate. Keyword rank и cosine несопоставимы; hybrid объединяет позиции через RRF (ADR 0023).
Отсутствие evidence/ответа не доказывает отсутствие фактов во всей базе.

## API и эксплуатация

Ответ: answer, abstained/reason, citations с document/chunk/page IDs и текстом,
retrieved_chunks со scores, retrieval_mode, chat_model, trace_id и timings.
Trace ID совпадает с X-Request-ID, это correlation ID, а не реализованный Langfuse trace.
Timings: retrieval_ms, generation_ms (при вызове) и total_ms; очередь ожидания API
и сетевой overhead не входят в total_ms сценария.

Один RAG-запрос одновременно на API-процесс, ожидание слота 3 секунды, whole-request
80 секунд, HTTP provider 65 секунд, connect 5 секунд; бесконечных retry нет.
CPU/память делятся с ingestion, inference latency не измерялась. Модель должна
быть установлена отдельно. /rag/search keyword работает без LLM.
Провайдерные ошибки санитизированы; запросы, passages, prompts и tokens не логируются.
SQL hide_parameters уже включён. Nginx 90 секунд, browser client 85 секунд.

Web Admin /rag — доступен вошедшим пользователям, включая member. Есть выбор семьи,
режима, top_k, вопрос, answer/search buttons, отказ, loading/errors, trace/timing,
кликабельные citations к выдержкам и ranking scores. Контент отображается как text,
без v-html/Markdown HTML. Правила доступа обеспечиваются сервером.

## Проверка

Unit tests используют fake providers: citations, abstention, pre-chat revocation,
empty scope, timeout, injection data boundary. Qdrant MockTransport проверяет
фильтры; PostgreSQL/HTTP-тест использует synthetic семьи, private/shared документы,
подложные и stale candidates. Обычные pytest не требуют LLM.
Расширенный smoke создаёт synthetic PDF с retention fact, запускает ingestion,
проверяет keyword/vector chat answers с источниками и отсутствие evidence для
несуществующего keyword. Вывод не печатает полный ответ/контекст и очищает свои данные.

## Проверка browser proxy после обновления API

Реальный smoke дополнительно обнаружил 502 после пересоздания API: Nginx со
статическим proxy_pass сохранял старый IP контейнера. Web Admin теперь использует
Docker resolver 127.0.0.11 (TTL 5 секунд) и фиксированный upstream через переменную;
rewrite/break убирает /api и сохраняет query string. Семантика следует
[NGINX proxy_pass](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass).
Адрес upstream не берётся из пользовательского ввода. Регрессия проверяется
запуском smoke после пересоздания API: authenticated /api/rag/search и SPA /rag.
Обновление IP может дать краткий отказ в пределах DNS TTL; zero-downtime rollout
этим изменением не заявляется.

## Результаты локальной проверки

- Ruff lint/format, strict mypy (82 source files): passed.
- Полный pytest с реальными PostgreSQL/MinIO: 128 passed, 2 skipped (Compose CLI
  внутри checks отсутствует); оба Compose-теста отдельно прошли на хосте.
- Frontend: 37 passed, TypeScript и Vite production build passed.
- Реальный Ollama qwen3:4b ответил на synthetic retention question с числом 37 и
  допустимыми citations в keyword/vector режимах. Отсутствующий keyword дал
  no-evidence abstention без chat. Это smoke, не измерение faithfulness/Recall.
- Проверены ingestion/reindex без дублей, источник/trace mapping, scoped Qdrant
  cleanup, authenticated Nginx RAG proxy и SPA route после пересоздания API.
- PostgreSQL/HTTP ACL-тесты подтвердили private/cross-family isolation и исключение
  stale/poisoned vector candidates. Provider tests проверили prompt data boundary,
  отсутствие thinking в ответе и sanitized timeout; общая injection robustness не доказана.
- nginx -t прошёл. Проверены Prometheus scrape/heartbeat и provisioned Grafana.
  Синтетические SQL-записи, MinIO objects и Qdrant vectors удалены.
- Во время повторных проверок Docker VM исчерпала диск. Удаление неиспользуемого
  build cache старше часа освободило около 4 GB без удаления volumes/данных;
  после этого полный pytest и smoke повторно прошли.
- Визуальный браузерный QA не выполнялся; component tests и реальные HTTP proxy
  проверки не заменяют визуальную приёмку. Production outcomes не заявляются.

## Qdrant Query API

Векторный адаптер использует POST /collections/{collection}/points/query:
вектор передаётся в query, кандидаты читаются из result.points. API поддерживается
закреплённой Qdrant 1.12.5; фильтры доступа, score_threshold и top_k сохраняются.
[Контракт Qdrant 1.12.x](https://api.qdrant.tech/v-1-12-x/api-reference/search/query-points).

## Русские словоформы в keyword-поиске

Миграция 0012 добавляет generated search_vector_ru с PostgreSQL russian и GIN.
Существующие фрагменты обрабатываются при миграции, повторные загрузка и embeddings
не нужны. Запрос сопоставляется с simple либо russian; score — максимум двух
рангов, без дублирования фрагментов. Фильтры доступа одинаковы для обоих условий.
«лейкоцит», «лейкоциты», «лейкоцитов» находят один фрагмент. Это stemming,
не исправление опечаток и не поиск подстрок. Векторный режим не меняется.
Добавление stored-колонки пересчитывает строки и требует блокировки таблицы;
для большой базы миграцию следует планировать отдельно.

У Snowball формы «лейкоцит» и «лейкоциты» имеют разные основы («лейкоц»
и «лейкоцит»). Для одиночного кириллического слова от четырёх букв используется
префикс нормализованной основы; синтаксис строится из escaped tsquery PostgreSQL,
не из пользовательского текста. Это расширяет совпадения и может снизить точность
на словах с общим корнем; многословные запросы сохраняют AND-семантику.
