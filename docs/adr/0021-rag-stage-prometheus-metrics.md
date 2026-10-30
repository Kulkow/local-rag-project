# ADR 0021: Время этапов RAG в Prometheus/Grafana

## Решение

Добавлен prometheus-client 0.22.1: стандартный collector/экспортёр нужен для
корректных cumulative histogram buckets, sum/count, счётчиков и изоляции registry.
Одна новая Python-зависимость зафиксирована uv.lock; новых сервисов нет.

Application определяет RagObserver/NullRagObserver и измеряет perf_counter через
RagMeasurements. PrometheusRagObserver во внешнем observability реализует порт.
Без адаптера use case остаётся пригодным для unit tests, не импортирует библиотеку
Prometheus и не зависит от доступности monitoring. У каждого FastAPI app свой
registry; process-global регистраций и смешивания тестовых приложений нет.

Измеряются только выполненные этапы: scope, embedding_identity, query_embedding,
keyword_search, vector_search, candidate_read, context, acl_revalidation, generation,
citation_validation; retrieval — общее время поиска с подготовкой контекста.
Повторные ACL/embedding_identity вызовы дают несколько observations и суммарное
значение соответствующего API timings *_ms. retrieval содержит дочерние этапы;
суммировать все гистограммы как независимые интервалы нельзя.

- rag_stage_duration_seconds{mode,operation,stage,outcome}: histogram; outcome
  success/error/cancelled, включая завершившиеся исключением и отменой вызовы.
- rag_request_duration_seconds{mode,operation,outcome}: histogram времени admitted
  application-вызова, без ожидания capacity и сериализации HTTP DTO.
- rag_requests_total{mode,operation,outcome}: завершённые admitted вызовы;
  answered/abstained/search_only/error/cancelled. Для search ответ не генерируется;
  пустая выдача остаётся search_only в счётчике, а API сохраняет прежний reason.
- rag_capacity_wait_seconds{mode,operation,outcome}: histogram ожидания слота,
  admitted/throttled/cancelled/error. Throttled не включается в admitted counter.

Все секунды монотонные, bucket границы 1 ms .. 90 s + Inf. p50/p95 вычисляет
Prometheus; короткое окно/малая выборка не являются бенчмарком. До вызова этапа его
серия отсутствует, а не выдается за измеренный ноль. Счётчики process-local и
сбрасываются при restart (rate учитывает resets). Текущий Compose запускает один
API-процесс; несколько workers/реплик требуют отдельного multiprocess/scrape решения.

Labels ограничены фиксированными режимами/операциями/этапами/исходами. Нет текста,
ответа, filename, user/family/document/chunk ID, trace ID, имён моделей и текста ошибок.
Ошибки не проглатываются: наблюдение выполняется в finally. Deadline cancellation
на уровне внешнего API timeout учитывается как cancelled в application-этапе;
отдельный timeout outcome не имитируется. ACL до evidence/model и финальная повторная
проверка остаются прежними.

## Доступ и отображение

GET /internal/metrics, вне OpenAPI, отдаёт только агрегаты. Prometheus внутри Compose
scrapes api:8000/internal/metrics (job rag-api). Nginx /api/internal/* возвращает 404,
поэтому SPA не получает metrics. Прямой localhost:8000/internal/metrics доступен
локальному оператору как и существующий loopback API; JWT для aggregate endpoint
не требуется. Не публикуйте API порт наружу без отдельного сетевого контроля.

Grafana RAG / RAG Performance: http://localhost:3001/d/rag-performance.
Панели: p50/p95 admitted runtime и этапов, p95 keyword/vector search, throughput,
ошибки/отмены, ожидание/отказ capacity, доля abstention и up API scrape target.
Rate/quantiles используют 5m окно: после старта требуется несколько scrapes и
реальные запросы; без них отсутствие графика не маскируется dummy данными.

## Проверки

Unit проверяет ветки keyword/vector/search-only, повторные ACL, failed/cancelled
provider, приватность, изоляцию registry, валидность exposition и throttling до RAG.
API сохраняет подробные timings без изменения схемы словаря. Live smoke проверяет
реальные Ollama/Qdrant вызовы, счётчики/этапы, Prometheus scrape, закрытие browser
proxy и provisioned Grafana dashboard. Все документы/пользователи smoke синтетические.

## Результат

Ruff lint/format, strict mypy (85 модулей), pytest с PostgreSQL/MinIO:
148 passed, 2 skipped. Дополнительная проверка запрета observability/Prometheus
во внутренних слоях: passed. Frontend: 68 passed, ESLint/typecheck/Vite build passed.
Promtool check config: passed. API/worker/Web Admin/Prometheus/Grafana обновлены,
healthy. Live smoke от member подтвердил keyword/vector/generation observations,
outcome счётчики, приватность и 404 browser proxy, реальный Prometheus scrape,
provisioned RAG Performance dashboard и валидность всех его PromQL выражений.
Полный путь ingestion -> RAG -> citations/download и прежний queue dashboard также
прошли. Синтетические строки и объекты очищены. Результат smoke не является
бенчмарком производительности или доказательством качества ответов.

## Дополнение: диагностика отдельного запроса

Playground выводит таблицу всех выполненных этапов из API timings, а не только
retrieval/generation. Request-scoped RagMeasurements передаётся обработчиком в
use case: finally сохраняет итог и частичные измерения при ошибке/отмене. Глобальные
объекты не хранят timings отдельных запросов. Обработчик ApplicationError добавляет
числовые timings и trace ID только при наличии RAG-контекста текущего запроса.

Дополнительно измеряются capacity_wait_ms и request_ms; total_ms сохраняет смысл
application runtime. Аутентификация, сериализация HTTP и сеть не входят в request_ms.
Ошибка внешнего deadline остаётся cancelled в Prometheus, а HTTP-ответ содержит
частичные timings. UI не подставляет нули для пропущенных этапов, объясняет вложенные
интервалы и очищает диагностику при повторном запросе/смене scope/сессии.

## Учёт токенов LLM

`RagMeasurements` хранит отдельную запись на каждый начатый LLM-вызов.
Application передаёт `TokenCounts` через порт провайдеру; Ollama-адаптер заполняет
только целые неотрицательные `prompt_eval_count` / `eval_count` из envelope,
до валидации model content. Это позволяет учитывать и отклонённые ответы без
записи их содержимого. Нет глобального mutable state и общих provider-счётчиков.
`finally` публикует известные значения в `rag_llm_tokens_total` с фиксированными
stage/direction labels; embeddings исключены. Snapshot поступает в JSON/SSE
и Vue, включая ошибки. Unknown остаётся null; повторные вызовы суммируются,
но при неизвестном слагаемом итог неизвестен. Новых зависимостей и миграций нет.
Подробная семантика: [API](../api/rag.md#токены-llm).
