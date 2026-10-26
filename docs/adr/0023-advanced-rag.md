# ADR 0023: Advanced RAG — FTS, Hybrid Search, RRF и reranker

## Решение и границы

Сохраняем keyword/vector baseline, добавляем retrieval_mode=hybrid. PostgreSQL FTS
(simple + russian, GIN, русский single-word prefix) и Qdrant Query API ищут
независимо в авторизованном наборе документов. API по умолчанию остаётся vector
для совместимости, Playground выбирает hybrid по умолчанию. Никаких новых
сервисов/пакетов/моделей не требуется. Миграция 0012 FTS уже введена ранее.

Hybrid собирает min(24, 3*top_k) кандидатов из каждого пути. Pure domain policy
считает reciprocal rank fusion с одинаковыми весами: score(d)=sum(1/(60+rank(d))).
Позиции начинаются с 1, повторный ID в одном списке учитывается один раз,
отсутствующий ID не получает вклад. Совпадения дедуплицируются по chunk_id,
при равных scores порядок определяется UUID. Keyword rank и cosine не складываются.
После RRF остаётся не более min(24, 3*top_k) кандидатов.

Для /rag/ask в hybrid при RAG_RERANKING=true (default) локальная Ollama chat model
переставляет кандидатов по релевантности исходному вопросу. Это LLM-reranker,
не cross-encoder. В application определён порт Reranker; инфраструктурный адаптер
можно заменить без изменения RRF/ACL. Ему передаются только уже разрешённые
кандидаты, по 600 символов, максимум 24. Результат — полная перестановка индексов:
не разрешены новые, повторные, пропущенные ID, bool вместо int. Невалидный вывод,
ошибка провайдера или таймаут 10 секунд сохраняют порядок RRF. Отмена не подавляется.

Итог ограничивается top_k и бюджетом контекста 6000 символов. Scores в hybrid
остаются RRF scores, даже когда порядок изменил reranker; они не являются оценкой
модели или вероятностью правильности. Поле reranked показывает успешное применение.
RAG_RERANKING=false позволяет сравнить hybrid RRF без reranker; keyword/vector
сохраняют отдельные baselines. /rag/search во всех режимах не вызывает chat,
rewriter/reranker и служит baseline retrieval без LLM (vector использует embeddings).

## ACL и ошибки

Оба поиска фильтруются по текущему family/owner/visibility/index generation.
Qdrant payload filter применяется до retrieval, SQL повторно проверяет candidates.
Перед передачей passages reranker проверяются все кандидаты, затем выполняются
проверки перед генератором и перед возвратом ответа. Недоступные passages не могут
попасть ни в reranker, ни в генератор. У модели нет полномочий менять scope.
ACL ошибки не маскируются fallback-логикой reranker. Контент — untrusted data,
системная инструкция и JSON формат снижают injection risk, но не доказывают
устойчивость модели. Reranker может ухудшить качество; он не создаёт evidence.

Hybrid использует FTS, даже если embeddings индекса несовместимы; несовместимые
vector candidates не возвращаются. Смена digest отбрасывает vector-ветку. Ошибка
доступности vector/embedding провайдера прерывает запрос обычной sanitized ошибкой:
тихий network fallback не реализован. При пустом hybrid /ask допускается один
Query Rewriting retry с тем же mode и повторным ACL scope (ADR 0022).

## Наблюдаемость и проверка

mode=hybrid и stages rrf/reranking включены в типизированные метрики. API timings
rrf_ms/reranking_ms — только для выполненных стадий; retrieval включает обе ветки,
fusion, reranking и context. Общий deadline 80 секунд сохраняется. Контент/ID/имена
документов не добавляются в telemetry. UI показывает hybrid, RRF/LLM reranker,
score и timings; исходники продолжают скачиваться только с серверной авторизацией.

Unit: формула RRF/дубли/пустые списки/tie-break, перестановки, fallback, ACL revocation,
search-only без LLM, injection как data. PostgreSQL/API: hybrid с подложными private,
cross-family и stale candidates. Результаты тестов — проверка корректности,
не измерение Recall@K/MRR/faithfulness. Улучшение качества и стоимости reranking
нужно измерять на versioned golden dataset; таких результатов здесь не заявляем.

## Локальная проверка реализации

- Ruff lint/format и strict mypy (89 source files): passed.
- pytest с PostgreSQL/MinIO: 195 passed, 2 skipped (Compose CLI tests внутри checks).
- Frontend: 69 tests, ESLint, vue-tsc, Vite build: passed.
- Синтетический live smoke: загрузка PDF, worker, embeddings, Qdrant Query API,
  keyword/vector/hybrid, локальные ответы с цитатами, scoped originals через Nginx,
  Prometheus scrape и Grafana PromQL: passed. Синтетические записи/объекты удалены.
- Reranker permutation/fallback/ACL проверены unit tests; live smoke допускает
  документированный fallback RRF и не доказывает смысловое качество перестановки.
- Recall/MRR/faithfulness, сравнительные задержки и визуальный browser QA не измерялись.
