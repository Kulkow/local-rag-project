# AGENTS.md — Enterprise RAG & AI Agent Platform

## 1. Mission
Build a reproducible, production-oriented **portfolio/reference project** for enterprise document question answering and agentic workflows. It must demonstrate engineering competence in Python, FastAPI, asynchronous processing, LangGraph, RAG evaluation, observability, and failure handling.

This is a learning and benchmarking project, **not evidence of commercial production deployment**. Never invent measured outcomes or describe experiments as production results.

## 2. Primary use case
An organization uploads PDF, DOCX, and HTML knowledge documents. Authorized users ask questions and receive grounded answers with document citations. An agent may choose between retrieval, clarification, and an explicit "insufficient evidence" response. Documents are indexed asynchronously and become searchable after processing.

Acceptance scenario:
1. An authenticated user uploads a document with access-control metadata.
2. The API persists document metadata and schedules ingestion.
3. A worker extracts, normalizes, chunks, embeds, and indexes the document.
4. The user queries the knowledge base; retrieval enforces document-level access restrictions **before** evidence reaches the model.
5. The API returns an answer, cited source identifiers, trace/request ID, and timing metadata.
6. Evaluation scripts compare retrieval and answer quality against a versioned golden dataset.

## 3. Technology decisions
- Python >=3.12; FastAPI; Pydantic v2; asyncio; httpx.
- LangGraph for explicit, testable agent state transitions; LangChain integrations only where they reduce boilerplate.
- PostgreSQL for users, document metadata, permissions, ingestion state, and evaluation runs; SQLAlchemy 2 async + Alembic.
- Qdrant for vector retrieval, with payload filters for tenant and authorized document IDs. PostgreSQL full-text search for keyword retrieval in the MVP; combine rankings with Reciprocal Rank Fusion (RRF). Benchmark against vector-only retrieval.
- MinIO (S3-compatible) for originals and extracted artifacts.
- Redis + Celery for background ingestion jobs. Celery tasks are synchronous entry points; call async application services through a clearly managed event loop, never through an uncontrolled nested loop. Prefer idempotent jobs with retries and dead-letter/failure handling.
- Ollama with configurable local embedding and chat models. Keep model providers behind interfaces so alternative OpenAI-compatible local endpoints can be tested.
- Langfuse for LLM traces and evaluations; Prometheus and Grafana for infrastructure and application metrics. Never put sensitive document content into telemetry by default.
- Vue 3 + Vite + TypeScript + PrimeVue 4 + Pinia for a first-party Web Admin; communicate with FastAPI over typed REST APIs (and SSE when needed).
- Docker Compose for **all** local services, including Web Admin. pytest, pytest-asyncio, Ruff, mypy, and pre-commit for quality.

Pin tested versions in a lockfile; do not assume all newest package versions are mutually compatible. Document model names, dimensions, and hardware requirements in `.env.example` and README.

## 4. Architecture and boundaries
Use a modular monolith with clear separation of concerns; avoid premature microservices.

```text
src/app/
  api/                 # FastAPI routers, dependencies, DTOs
  application/         # use cases, orchestration, ports
  domain/              # entities, value objects, policies
  infrastructure/
    db/                # SQLAlchemy repositories, migrations
    object_storage/    # S3/MinIO adapter
    vector_store/      # Qdrant adapter
    search/            # keyword + hybrid retrieval
    llm/               # chat and embedding providers
    queue/             # Celery configuration/tasks
  rag/                 # ingestion, chunking, retrieval, reranking, citations
  agents/              # LangGraph state, nodes, edges, tools
  evaluation/          # datasets, metrics, experiment runners
  observability/       # tracing, metrics, logging
  core/                # settings, errors, security
worker/
web-admin/              # Vue 3 SPA admin UI, PrimeVue, Pinia, typed API client
  src/views/
  src/components/
  src/composables/
  src/stores/
  tests/
tests/
  unit/
  integration/
  e2e/
  evaluation/
datasets/
  sample_documents/
  golden/
infra/
  compose/
docs/
  adr/
  architecture/
scripts/
```

Domain/application layers must not import FastAPI, Qdrant, Celery, LangChain, or SQLAlchemy. Infrastructure implements application ports. Keep request handlers thin. Prefer explicit use cases and dependency injection over service locators or global clients.

## 5. Implementation phases
**Phase 1 — runnable foundation**
- Docker Compose with **web-admin**, API, PostgreSQL, Qdrant, Redis, MinIO, Ollama, and worker; Langfuse/Grafana optional via profiles.
- Web Admin must be a working Vue 3 + Vite SPA with PrimeVue 4, responsive layout, navigation, an API health/status dashboard, and clear loading/error states. Not a static mockup.
- Health/readiness endpoints; typed configuration; structured JSON logs; migrations; CI for lint, type checks, and tests.
- README with reproducible setup, sample curl commands, and a smoke test.

**Phase 2 — document ingestion**
- Web Admin: authenticated document list, upload form, ingestion status, errors, and retry/delete controls with confirmation.
- Upload PDF/DOCX/HTML with size/type validation, checksum, tenant ID, owner, ACL, and status.
- Extract and normalize text; deterministic chunking with document/page/section metadata.
- Store originals in MinIO, metadata in PostgreSQL, vectors in Qdrant, searchable text in PostgreSQL.
- Idempotent ingestion; retryable failure states; document replacement/deletion; index cleanup.

**Phase 3 — retrieval and answering**
- Web Admin: RAG Playground with question input, grounded answer, clickable citations, retrieved chunks, scores, timings, and retrieval-mode selection.
- Baselines: keyword-only and vector-only; then hybrid RRF.
- Tenant/ACL filtering on every retrieval path; defense-in-depth authorization on returned candidates.
- Configurable top_k, chunk size/overlap, embedding model, and optional reranking.
- Grounded answers with source citations; explicit abstention if evidence is insufficient.
- Stream responses via SSE only after the non-streaming path is correct.

**Phase 4 — LangGraph agents**
- Web Admin: agent run list and per-run step timeline, tool invocations, retries, and errors; do not expose secrets or unrestricted chain-of-thought.
- Implement a small deterministic graph: classify request -> retrieve -> assess evidence -> answer or abstain.
- Add a bounded query-rewrite retry if initial retrieval is weak; enforce max steps and timeouts.
- Tools must have typed schemas, allowlists, permission checks, and auditable outputs.
- Do not build a generic autonomous multi-agent platform until baseline metrics justify it.

**Phase 5 — evaluation and observability**
- Web Admin: evaluation dataset/run management, comparative metrics and charts, model configuration, and links to Langfuse/Grafana.
- Versioned golden dataset with questions, expected evidence document/chunk IDs, answer criteria, and unanswerable questions.
- Measure Recall@K, MRR, citation correctness, answer faithfulness, abstention behavior, p50/p95 latency, indexing throughput, and failure rates.
- Establish a baseline before adding hybrid search, reranking, or agents. Record configuration, dataset version, model IDs, sample sizes, hardware, and results for every experiment.
- Use automated regression gates with explicitly justified thresholds; include a human-reviewed sample.

**Phase 6 — hardening**
- Web Admin: users/roles/tenants, queue/job monitoring, controlled retry actions, audit logs, and hardened session management.
- Load tests, concurrency limits, cancellation, retry/backoff, idempotency, queue recovery, and degraded-mode behavior.
- ACL leakage tests, prompt-injection tests, malicious document tests, tenant isolation tests.
- Produce an architecture diagram, ADRs, benchmark report, and limitations section.

## 6. Docker and Web Admin requirements
- **Docker-first:** the entire application must run through a root-level `compose.yaml` and `.env`; no host Python, Node.js, PostgreSQL, or Ollama installation required. The only host prerequisites are Docker Engine/Compose and sufficient memory/disk. Document CPU-only operation and optional GPU acceleration; Ollama model downloads are an explicit initialization step, not assumed to be preloaded.
- Default local URLs: Web Admin `http://localhost:3000`, FastAPI/OpenAPI `http://localhost:8000/docs`, MinIO Console `http://localhost:9001`. Use named volumes for PostgreSQL, Qdrant, MinIO, Redis as appropriate, and Ollama model data. Avoid exposing databases to the host unless needed for development.
- Use healthchecks, `depends_on` with health conditions where supported, restart policies, bounded resource usage where feasible, and an explicit migration/init command. Do not rely on startup ordering alone for readiness.
- Supply multi-stage Dockerfiles for Python API/worker and Vue SPA Web Admin; development hot reload can use an opt-in Compose override/profile, while the default build is reproducible.
- Browser traffic must reach FastAPI through a documented API base URL or an Nginx reverse proxy (`/api` to FastAPI); avoid `localhost` confusion inside containers. Configure CORS explicitly if using cross-origin browser requests.
- Web Admin is an operational tool, not a marketing site. Use a client-side Vue 3 SPA (no Nuxt, no SSR), Vite, Vue Router, TypeScript, PrimeVue 4, Pinia, and a typed API client generated from or checked against FastAPI OpenAPI schemas.
- Admin pages: Dashboard, Documents, RAG Playground, Agents, Evaluation, Models, Jobs, Users/Roles, Settings. Implement incrementally as corresponding backend capabilities become real. Never present dummy metrics or placeholder actions as working functionality.
- RAG Playground must show answer, citations, retrieved chunks, ranking scores, timing, trace ID, and retrieval mode; Evaluation must compare actual recorded runs and configurations.
- Provide authenticated admin access with server-side authorization; do not rely on hiding frontend controls. Do not ship shared default production credentials. For local bootstrap, require explicit initial-admin credentials via environment or an interactive bootstrap command, and document safe rotation.
- Use accessible, responsive UI components, form validation, empty/loading/error states, pagination, and confirmation for destructive actions. Frontend tests should cover key views and API error states.

## 7. Security and privacy rules
- Deny access by default; always scope reads and writes by authenticated tenant and user permissions.
- Never retrieve broadly and rely only on the LLM to hide unauthorized text.
- Treat document content and retrieved passages as **untrusted data**, not instructions.
- No arbitrary code execution, filesystem access, or external network tools exposed to the agent.
- Keep secrets in environment variables or secret stores; never commit credentials or personal documents.
- Validate upload MIME/type and size; reject unsafe paths and archive expansion attacks.
- Use synthetic/publicly redistributable fixtures. Do not log full prompts, documents, tokens, or personal data by default.
- Tests must include cross-tenant access attempts and injection attempts.

## 8. Engineering conventions
- All public functions and application interfaces must have type hints. Prefer small, composable modules.
- Use async I/O for FastAPI request paths; avoid blocking model/database calls in the event loop.
- Define bounded timeouts for external calls and explicit retry policies only for transient failures.
- Prefer database-backed state transitions and idempotency keys for ingestion.
- Database schema changes require Alembic migrations.
- API changes require OpenAPI-compatible schemas and tests.
- Every bug fix must add a regression test when feasible.
- Do not add dependencies without explaining why they are necessary.
- Document meaningful architecture tradeoffs in `docs/adr/`.

## 9. Testing strategy
- Unit: chunking, RRF, ACL policy, citation mapping, graph transitions, metric calculations.
- Integration: PostgreSQL, Qdrant, MinIO, Redis, ingestion retries, index consistency.
- E2E: upload -> ingest -> query -> cited answer; unauthorized query -> no leaked evidence.
- Evaluation: deterministic retrieval metrics; model-based judgments may be nondeterministic and must be reported separately.
- Load: k6 or Locust scenarios for query and ingestion workloads, with hardware and model settings recorded.
- Avoid requiring a running LLM for ordinary unit tests; use fakes/stubs.

## 10. Definition of done for each change
1. Functionality works end-to-end for the stated acceptance criteria.
2. Tests cover success, failure, and relevant authorization cases.
3. `ruff check`, formatting, mypy, and pytest pass (or blockers are explicitly reported).
4. README, API examples, and configuration are updated when affected.
5. No secrets, private data, unsupported benchmark claims, or dead code are introduced.
6. Agent summarizes changed files, commands executed, test results, and remaining risks.

## 11. Instructions for coding agents (Codex / Claude Code)
- Read `AGENTS.md`, `README.md`, and relevant ADRs before modifying code.
- Inspect the existing repository before proposing changes; preserve its conventions.
- For tasks spanning multiple modules, state a short plan and implement one verifiable slice at a time.
- Ask before introducing new infrastructure components, replacing major architectural decisions, or performing destructive migrations.
- Do not claim commands or tests passed unless actually executed.
- Do not fabricate evaluation datasets, benchmarks, model performance, or production experience.
- Favor the simplest working vertical slice over scaffolding many empty abstractions.
- When a request is underspecified, choose a safe, documented default and call it out.

## 12. First task for the coding agent
Implement **Phase 1** as a working vertical slice, not a skeleton: Python project structure, FastAPI `/health` and `/ready`, async PostgreSQL connection, Alembic, Docker Compose (**Vue SPA Web Admin**, API, PostgreSQL, Qdrant, Redis, MinIO, Ollama, worker), `.env.example`, Makefile, Ruff/mypy/pytest, one API integration test, GitHub Actions CI, and a README with setup and verification instructions. Implement a real Web Admin layout and service-health dashboard consuming the FastAPI endpoint. Verify `docker compose up -d --build` starts the stack and document Ollama model initialization. Keep optional observability components out of the critical startup path. Run available checks and report any services that could not be tested locally.
