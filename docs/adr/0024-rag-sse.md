# ADR 0024: SSE для этапов RAG в Playground

POST /rag/ask/stream и /rag/search/stream принимают прежний QuestionInput и JWT
в Authorization. Существующие JSON endpoints сохраняются. Frontend читает SSE через
fetch/ReadableStream, поскольку нужны POST и Bearer header без токена в URL.
Новых зависимостей, моделей и сервисов нет.

События progress, result и error несут JSON RagStreamEvent (схема в OpenAPI).
Progress отправляется сразу и примерно раз в 250 мс: trace_id, elapsed_ms,
waiting, active_stages, timings. Snapshot включает время выполняющихся этапов;
завершённые/повторные этапы сохраняют прежнюю семантику. Быстрые этапы могут не
попасть в active_stages, но их измерения остаются в timings. Это поток состояния,
а не журнал каждого перехода. Регулярный progress также поддерживает соединение.
Буферизация Nginx отключена; сервер выставляет X-Accel-Buffering: no и no-store.

Текст вопроса, evidence и необработанный вывод модели не идут в progress. Result
отправляется единожды после существующих проверок citations и финального ACL;
внутри result находится обычный AnswerView. Токены модели не транслируются до
валидации. Это позволяет не выдавать промежуточные ответы при отзыве доступа.
Ошибки до открытия потока имеют обычный HTTP status; после открытия — event:error
с sanitized detail/code и частичными timings при HTTP 200. Клиент не переподключается
автоматически: повтор POST мог бы запустить лишнюю генерацию.

На закреплённой FastAPI 0.115.6 yield-зависимости освобождаются до отправки тела
StreamingResponse. Поэтому HTTP client/use case создаются внутри задачи потока
и закрываются там же, включая отмену. Задача использует прежние semaphore/deadline
(3 секунды ожидания, 80 секунд RAG). Disconnect/кнопка «Остановить»/уход со страницы
отменяют задачу и освобождают слот; отмена HTTP не гарантирует мгновенную остановку
внутренних вычислений сервера Ollama. Источники остаются за прежней авторизацией.

Клиент разбирает частичные UTF-8/CRLF кадры, проверяет content-type, ограничивает
буфер 1 MB, обрабатывает premature EOF и deadline 85 секунд. Отмена/сбой сохраняет
последний полученный snapshot. Смена сессии очищает состояние. На экране видно,
какие измерения ещё обновляются. Server-Timing HTTP описывает подготовку заголовков;
полное время RAG нужно брать из terminal event, а не из заголовка SSE.

Основания: [FastAPI: yield dependencies и StreamingResponse](https://fastapi.tiangolo.com/advanced/advanced-dependencies/#dependencies-with-yield-and-streamingresponse-technical-details),
[формат SSE](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#event_stream_format).
