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
retrieval_mode — vector (default) или keyword; top_k — 1..8 (default 5).
Keyword ищет слова ('simple', AND): используйте короткие термины, если полный
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

Модель может ошибаться даже при корректных номерах ссылок. Это baseline без reranking,
hybrid и измеренной faithfulness. Подробности: [ADR 0013](../adr/0013-rag-search-answering.md).
