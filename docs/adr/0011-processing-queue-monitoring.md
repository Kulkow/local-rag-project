# ADR 0011: Последовательная очередь обработки и Grafana

## Решение

Пользователь запросил очередь обработки документов, Grafana и один поток для теста.
Используем существующие Redis/Celery, PostgreSQL и обработчик PDF. Дополнительные
сервисы Prometheus, Grafana и небольшой exporter включаются профилем monitoring.
Новых Python/npm-зависимостей нет. Это очередь извлечения текста; чанкинг,
эмбеддинги и RAG-индексация пока не добавлены.

Состояние задания хранится в document_processing_jobs (миграция 0007). Запись
queued создаётся в одной транзакции с переходом PDF-оригинала в uploaded.
В Redis не передаются байты, имена, JWT или пользовательские аргументы задачи.
Celery beat раз в пять секунд публикует сигнал documents.process_next, worker
читает одно готовое задание из PostgreSQL. Потеря сигнала не теряет задание:
следующий tick снова проверит БД. Redis не является источником состояния ingestion.

Worker запускается с prefork и concurrency=1, prefetch=1. Это один обработчик задач,
а не threads-pool. PDF parser может создавать свой изолированный subprocess.
Дополнительно глобальный PostgreSQL advisory transaction lock не допускает двух
параллельных потребителей этой очереди даже при ошибочном запуске второго worker.
Embedded beat предназначен для локального теста: одну реплику worker, без scale.
Согласно [Celery](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html),
periodic tasks могут пересекаться, поэтому одной настройки расписания недостаточно.

Синхронная Celery task создаёт asyncio.Runner; engine, MinIO и Redis закрываются
до закрытия loop. Никакого глобального async engine между event loops нет.
Права пользователя перечитываются перед обработкой: активность, роль, семья и
видимость документа проверяются существующим ExtractDocument. Отмена прав не
маскируется под системного администратора.

## Надёжность

Claim использует блокировку строки и SKIP LOCKED, увеличивает attempts и меняет
generation. Lease задания — 10 минут, попыток максимум три. Ошибки хранения,
перегрузки и неизвестные ошибки повторяются с задержкой 10/20 секунд. Conflict
извлечения ждёт 310 секунд, чтобы не обогнать пятиминутный extraction lease.
Ошибки документа и доступа завершаются без автоматического повтора.

После падения worker processing можно забрать заново по истечении lease.
Исчерпание трёх попыток фиксирует failed/worker_lost. failed — сохраняемая в БД
dead-letter область; отдельного Redis DLQ нет. Generation защищает от записи
устаревшего результата. Внешние операции остаются at-least-once; завершённое
извлечение повторно не выполняется существующим extraction use case.

Внешний processing timeout — 150 секунд; Celery soft/hard limits — 165/180 секунд.
Scheduler ticks истекают через 10 секунд, Redis visibility_timeout — 600 секунд.
Остановка worker оставляет задания в БД. Автовозобновление uploading-оригиналов
и атомарность PostgreSQL/MinIO этой очередью не решаются.

POST /documents/{id}/process (202) идемпотентен для active/succeeded, failed
позволяет явно запустить новый цикл попыток. GET /documents/{id}/processing
показывает статус только после проверки доступа. История всех попыток не хранится.
Старые документы автоматически не backfill: для uploaded PDF вызовите process.
DOCX/HTML сохраняются без задания, поскольку для них нет extractor.

Старый синхронный POST /extract сохранён для диагностики/совместимости и не идёт
через очередь; он не должен использоваться для теста однопоточной очереди.
Web Admin использует /process, чтение текста остаётся отдельным действием.

## Мониторинг

Внутренний exporter на 9100 читает агрегаты PostgreSQL и Redis. Prometheus
сохраняет их семь дней. Grafana автоматически получает datasource и dashboard
через [provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/).
В метриках нет document/user/tenant IDs, имён, текста, промптов или секретов.

Метрики — gauges: число текущих заданий по статусу, возраст старейшего ожидающего,
среднее время последней попытки terminal jobs, длина Redis-list (включая ticks),
heartbeat tick worker в последние 240 секунд. Это не накопительные счётчики попыток
и не p95. При удалении/повторе заданий агрегаты меняются. up=0 означает ошибку
scrape, а не нулевую очередь. Heartbeat не гарантирует доступность parser/MinIO.
Размер очереди документов — queued/retry_wait в PostgreSQL, не Redis-list.

Grafana доступна только на localhost:3001 с обязательной аутентификацией;
Prometheus/exporter не публикуются на хост. Пароль задаётся явно через окружение
(локальный fallback — уже заданные ADMIN_USERNAME/ADMIN_PASSWORD). Никаких admin/admin.
Provisioned dashboard редактируется в репозитории. Имена images закреплены для
воспроизводимости; это не утверждение об их текущей безопасности.

## Результаты локальной проверки

- Миграция 0007 применена; schema changes добавочные, существующие volumes сохранены.
- Ruff lint/format и strict mypy (69 source files) прошли.
- Полный pytest с TEST_OBJECT_STORAGE=1: 94 passed, 1 skipped (Compose CLI внутри
  checks-образа отсутствует). Оба Compose packaging-теста отдельно прошли на хосте.
- Frontend: 32 passed, TypeScript и Vite production build прошли.
- Реальный smoke через запущенный API и Celery: два synthetic PDF завершены
  последовательно с проверкой timestamps и текста; повреждённый PDF завершился
  failed после одной попытки. Test records/MinIO objects удалены.
- Экспортер вернул heartbeat=1 без document IDs, Prometheus подтвердил up=1,
  Grafana API с аутентификацией вернул provisioned dashboard с семью панелями.
- API, worker, exporter, Prometheus, Grafana и обновлённый Web Admin запущены.
  Визуальный браузерный QA не выполнялся. Это функциональная проверка локального
  reference-проекта, не benchmark или результат production-эксплуатации.
