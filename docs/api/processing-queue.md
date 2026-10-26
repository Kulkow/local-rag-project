# Очередь извлечения текста

После загрузки PDF задание уже записано в БД вместе со статусом uploaded.
Для ранее загруженного PDF или повторного запуска failed используется POST ниже.
Worker запускается одной репликой через Docker Compose; monitoring включается
профилем monitoring. [Настройка и ограничения](../adr/0011-processing-queue-monitoring.md).

## POST /documents/{document_id}/process

JWT обязателен. Проверяются доступность документа, доступ к семье и право записи.
Тело не требуется. Только uploaded и поддерживаемый extractor (сейчас PDF).
Ответ: 202 с ProcessingJobView. Active/succeeded возвращаются без нового задания;
failed сбрасывается в queued с новым циклом до трёх попыток.

## GET /documents/{document_id}/processing

JWT и право чтения документа/семьи обязательны. Ответ 200 — текущее задание.
Чужой документ/семья или отсутствие задания дают 404. Member может читать статус
доступного документа, но не запускать обработку (403).

| Поле ответа | Значение |
| --- | --- |
| document_id | UUID документа. |
| status | queued / processing / retry_wait / succeeded / failed. |
| attempts | 0–3 в текущем цикле повторов. |
| error_code | null либо безопасная категория ошибки. |
| created_at | Время создания задания. |
| started_at | Начало последней попытки либо null. |
| finished_at | Время завершения succeeded/failed либо null. |

Содержимое документа, ключи MinIO, пользователь и lease в ответ не входят.
При succeeded текст читается через GET /documents/{id}/pages; статус оригинала
остаётся uploaded. Для новых задач succeeded означает завершение чанкинга и embedding-индексации;
старые задачи до расширения pipeline могли завершить только извлечение. Проверяйте /index.

Постоянные ошибки: invalid (например, повреждённый PDF), forbidden (права отозваны),
not_found, unsupported_media. Повторяемые: storage_unavailable, throttled,
conflict, processing_unavailable. Worker_lost после исчерпания попыток при падении
worker. Подробный код parser при ошибке можно читать через существующий
GET /documents/{id}/extraction с той же авторизацией.

Старый синхронный POST /extract остаётся диагностическим API и обходит очередь.
В Web Admin используется очередь. При потере HTTP-ответа проверьте processing:
задание могло сохраниться, и повтор POST безопасен для active/succeeded.


## Индекс и принудительное обновление

GET /documents/{id}/index возвращает document_id, status (indexing/indexed/failed),
embedding_model, embedding_digest, dimensions, chunk_count и error_code.
Требуются JWT и право чтения документа/семьи; чужие и неиндексированные документы
возвращают 404. Текст чанков/ключи коллекций через этот endpoint не выдаются.

POST /documents/{id}/reindex (202) требует права записи. Позволяет повторно
обработать succeeded/failed с принудительной перестройкой векторов. Active job
возвращается без сброса. Оригинал и извлечённый текст сохраняются. Используйте
после смены модели/настроек или потери vector volume. Индексирование не реализует
retrieval и ответы на вопросы. Детали: [ADR 0012](../adr/0012-chunking-embeddings.md).
