# Поиск и ответы RAG

Откройте http://localhost:3000/rag после входа и индексации PDF. Доступны семьи,
разрешённые вашей учётной записи, и только их доступные indexed документы.
Для старых PDF сначала нажмите «Переиндексировать» в Documents.

## POST /rag/ask и POST /rag/search

JWT обязателен для обоих endpoint. Формат тела:

```json
{
  "family_id": "00000000-0000-0000-0000-000000000001",
  "question": "Каков срок хранения документов проекта?",
  "retrieval_mode": "vector",
  "top_k": 5
}
```

family_id — реальная доступная семья; question — 1..2000 символов, не whitespace;
retrieval_mode — vector (API default), keyword или hybrid; top_k — 1..8 (default 5).
Keyword использует PostgreSQL FTS ('simple' + 'russian', AND): используйте короткие термины, если полный
естественный вопрос не совпадает. Vector требует установленную embedding-модель
и индекс с тем же digest/размерностью. Chat используется только в /ask при evidence.

```sh
curl -fsS http://localhost:8000/rag/ask \
  -H 'Authorization: Bearer YOUR_JWT' \
  -H 'Content-Type: application/json' \
  -d '{"family_id":"YOUR_FAMILY_UUID","question":"Каков срок хранения?","retrieval_mode":"vector","top_k":5}'
```

Ответ 200 содержит:

| Поле | Назначение |
| --- | --- |
| answer | Текст ответа с [n] или фиксированный отказ. |
| abstained / reason | Причина отказа, например no_evidence, incompatible_index, insufficient_evidence, invalid_citations. Для /search с результатами reason=search_only, answer не является сгенерированным ответом. |
| citations | Использованные источники с source_id, document_id, chunk_id, filename, page_number, text, score. |
| retrieved_chunks | Все разрешённые выдержки текущего запроса, переданные модели (до 6000 символов). |
| retrieval_mode / chat_model | Фактический режим и configured chat model либо null, если генератор не вызывался. |
| trace_id | UUID корреляции; совпадает с X-Request-ID. |
| timings | retrieval_ms, generation_ms (если был chat), total_ms. |

Score vector — cosine similarity, score keyword — ts_rank_cd. Их нельзя сравнивать
напрямую. Citations в Playground ведут к выданной выдержке, не к скачиванию PDF.

Ошибки: 401 — JWT отозван/неверен, 404 — недоступная семья, 409 — evidence изменилось
во время запроса, 422 — неверный ввод/конфигурация модели, 429 — занятый слот или
слишком большой scope, 503 — сервис/модель недоступны либо timeout. Не возвращаем
сырой provider response. При отказе не вызывайте модель с широким неавторизованным
контекстом: смените режим, уточните вопрос или проверьте индексацию.

Модель может ошибаться даже при корректных номерах ссылок. Hybrid/RRF и локальный
LLM-reranker реализованы; faithfulness пока не измерена. Подробности: [ADR 0013](../adr/0013-rag-search-answering.md).

Ответ timings дополнен длительностями выполненных этапов *_ms: scope,
embedding_identity, query_embedding, keyword_search, vector_search, candidate_read,
context, acl_revalidation, citation_validation. retrieval_ms/generation_ms/total_ms
сохранены; пропущенные этапы отсутствуют. Повторные этапы суммируются. Эти же вызовы
попадают в histogram Prometheus; Grafana: `/d/rag-performance` на localhost:3001.
Подробнее: [ADR 0021](../adr/0021-rag-stage-prometheus-metrics.md).

При отказе от генерации `answer` содержит конкретное объяснение и следующий шаг,
а `reason` сохраняет машинный код. `no_evidence` различает в тексте отсутствие
доступных готовых индексов и отсутствие подходящих результатов поиска.
`invalid_model_output` перечисляет нарушенные требования к answer/citations/
insufficient_evidence без вывода сырого ответа модели. В Web Admin код причины
показывается под объяснением. Недоступные документы, внутренние исключения и
содержимое отклонённого ответа в диагностику не включаются.

Keyword-поиск учитывает русские словоформы через PostgreSQL russian stemming
(например, «лейкоцит» и «лейкоциты»), сохраняя literal simple-поиск.
Требуется миграция 0012; существующие фрагменты обновляются автоматически.

Для одного русского слова от четырёх букв дополнительно допускается префикс
нормализованной основы: это компенсирует различия стемминга единственного
и множественного числа, но может вернуть дополнительные слова с общим корнем.

Query Rewriting: при `RAG_QUERY_REWRITING=true` (по умолчанию) `/rag/ask`
после пустого поиска выполняет одну переформулировку и повторяет поиск в том же
режиме с повторной проверкой доступа. Генерация отвечает на исходный вопрос.
`/rag/search` остаётся без LLM. Лимит rewrite — 10 секунд, общий запрос — 80 секунд.
При ошибке rewrite сохраняется безопасный отказ. Выполненные этапы отражаются в
`timings.query_rewriting_ms`, `timings.query_retry_ms` и Prometheus stage histogram.

## Advanced RAG

`retrieval_mode=hybrid`: PostgreSQL FTS + Qdrant → RRF (k=60) → optional local
LLM reranker → top_k → context → answer/citations. ACL фильтрует обе ветки
до попадания evidence в модель. Playground выбирает hybrid по умолчанию.
В hybrid поле score — RRF, а не cosine. `reranked=true` означает успешное
переранжирование; scores сохраняются от RRF. При невалидном ответе/таймауте
reranker сохраняется RRF. `RAG_RERANKING=false` отключает reranker. `/rag/search`
не вызывает rewriter/reranker/chat; `/rag/ask` использует их по необходимости.
Новые timings: `rrf_ms`, `reranking_ms`. Подробнее: [ADR 0023](../adr/0023-advanced-rag.md).
