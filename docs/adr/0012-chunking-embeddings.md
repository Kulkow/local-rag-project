# ADR 0012: Детерминированный чанкинг и локальные эмбеддинги

## Решение и настройки

Продолжаем существующую однопоточную очередь: PDF → нормализованные страницы →
чанки → Ollama → Qdrant и PostgreSQL. Новых Python/npm-зависимостей нет;
REST-адаптеры используют httpx. Domain/application не зависят от клиентов сервисов.

Baseline chunker `page-characters-v1` режет каждую страницу окнами по CHUNK_SIZE
символов с CHUNK_OVERLAP. Defaults: 1000/150, batch 8, максимум 2000 чанков на
документ. Это символы Python Unicode, не токены; пустые окна пропускаются,
страницы не смешиваются. Размер окна положительный, overlap меньше размера.
Номер страницы, ordinal и полуоткрытые смещения start/end сохраняются для цитат.
Chunk UUIDv5 зависит от документа, checksum, версии алгоритма и параметров окна.
Повтор той же операции не создаёт новые chunk IDs. Разбиение по предложениям,
разделам и адаптивный tokenizer пока не реализованы.

Модель по умолчанию — установленная локально embeddinggemma:latest, размерность
768 подтверждена реальным /api/embed на синтетической строке. Это функциональная
проверка, не оценка retrieval quality. Raw chunk text передаётся без task prefix;
это явно фиксированный baseline, а не утверждение об оптимальном prompting модели.
Поддержка батчей и truncate=false следует [Ollama API](https://github.com/ollama/ollama/blob/main/docs/api.md).
Тихое усечение запрещено: слишком большой ввод даёт ошибку, настройки нужно менять.
Проверяются число векторов, размерность, конечность значений и отсутствие zero vector.

## Хранение и воспроизводимость

Миграция 0008 добавляет document_indexes и document_chunks. Первая таблица хранит
checksum, extraction generation, chunker/config, имя и digest модели, размерность,
collection, fingerprint, статус и число чанков. Вторая хранит текст и координаты
чанков; generated tsvector ('simple') и GIN подготавливают keyword retrieval,
поисковый API добавлен позднее (ADR 0013), hybrid/RRF/reranker — в ADR 0023.

Digest модели читается из /api/tags до и после индексации. Изменение тега во время
операции даёт conflict и не публикует ready state. Не меняйте локальную модель
во время ingestion: проверка до/после не является атомарной блокировкой Ollama.
Fingerprint включает исходник, extraction generation, chunker/config и модель с digest.
Qdrant collection называется rag_chunks_<hash(model,digest,dimensions)>.
Это разделяет несовместимые embedding spaces, даже если их размерности совпадают.
Проверяется конфигурация Cosine/size существующей collection согласно
[Qdrant](https://qdrant.tech/documentation/concepts/collections/).

Qdrant payload: chunk/document/family/owner IDs, visibility, generation, страница,
ordinal и digest. Сам текст хранится только в PostgreSQL/MinIO. Payload indexes
создаются для family_id, document_id и index_generation. Удаление векторов
всегда фильтруется одновременно по семье и документу. Qdrant не открыт на хост.

Семья — существующая область авторизации, отдельного tenant_id в текущем приложении
нет. Авторизация проверяется до чтения артефакта и до вызова модели. Будущий retrieval
обязан передавать family/authorized-document/generation filters в Qdrant и повторно
проверять доступ в PostgreSQL до чтения текста/передачи LLM. Поискового пути сейчас
нет; наличие ACL payload само по себе не реализует retrieval authorization.

## Публикация, повторы и переиндексация

SQL status: indexing → indexed или failed. Перед записью векторов фиксируется
indexing; при удачном upsert всех batch одной SQL-транзакцией заменяются чанки и
выставляется indexed. Готовность требует indexed и совпадения generation.
Failure оставляет индекс неготовым; частичные векторы могут оставаться до retry.
Повтор сначала удаляет векторы своего документа и пишет их с детерминированными IDs.
При смене collection старые векторы документа очищаются перед заменой её ссылки.
PostgreSQL/Qdrant не имеют общей транзакции: zero-downtime reindex не гарантируется,
старые чанки могут остаться в SQL при failed, их нельзя использовать без ready/generation.

Одинаковый fingerprint в indexed пропускается, но не проверяет сохранность Qdrant
после потери volume. Для восстановления служит явный POST /documents/{id}/reindex.
Миграция 0009 сохраняет reindex_requested в задании: force rebuild переживает retries.
Обычный /process остаётся идемпотентным для succeeded, /reindex возвращает terminal
job в queued. Активная задача не перезапускается. Оригинал и извлечённый артефакт
сохраняются. Старые документы не переобрабатываются автоматически: нажмите
«Переиндексировать» или вызовите API. После смены конфигурации сделайте это явно.

Worker остаётся concurrency=1 с глобальным advisory lock. Лимит всего pipeline —
480 секунд, Celery soft/hard 510/540, lease 600. Heartbeat TTL увеличен до 600;
он показывает свежесть tick, а не готовность модели. Ограничения объёма/тайм-аута
могут остановить большой документ до завершения; throughput не измерялся.

HTTP provider errors и SQL bind parameters скрываются, текст/векторы в telemetry
не пишутся. Grafana показывает текущие indexed documents/chunks агрегатами без IDs.
GET /documents/{id}/index доступен только после проверки семьи и видимости.
Web Admin показывает реальные chunk_count/model/dimensions и умеет переиндексировать.

## Проверка

Unit-тесты не требуют модели: Unicode/overlap, deterministic IDs, batching,
idempotence, модель/digest, ACL, invalid vectors и failure/ready gating проверяются
фейками и httpx.MockTransport. PostgreSQL-тест проверяет generated full-text index,
атомарную замену и защиту от устаревшей generation в изолированной rollback schema.
Реальный scripts/smoke_processing_queue.py проверяет Ollama, PostgreSQL, MinIO,
Qdrant count, повторную индексацию без дублей и мониторинг; свои синтетические
записи, оригиналы, артефакты и векторы удаляются.

## Результаты локальной проверки

- Миграции 0008/0009 применены, существующие volumes и оригиналы сохранены.
- Ruff lint/format и strict mypy (74 source files) прошли.
- Полный pytest с live MinIO: 113 passed, 2 skipped (Compose CLI отсутствует
  внутри checks). Оба Compose-теста отдельно прошли на хосте.
- Frontend: 33 passed, TypeScript и production Vite build прошли.
- Реальный pipeline обработал два многочанковых synthetic PDF последовательно,
  получил embeddinggemma vectors размерности 768 и сохранил соответствующее число
  точек в Qdrant. Явная повторная индексация прошла без дублирования точек.
- Повреждённый PDF завершился failed после одной попытки. Тестовые SQL-записи,
  MinIO objects и scoped Qdrant vectors очищены.
- Проверены heartbeat/privacy exporter, Prometheus up=1 и авторизованный Grafana
  dashboard с девятью панелями. API/worker/Web Admin и monitoring healthy.
- Визуальная браузерная проверка не выполнялась. Эти проверки не измеряют Recall,
  faithfulness, throughput или production reliability.
