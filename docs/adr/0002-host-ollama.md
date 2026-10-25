# ADR 0002: Use the existing host Ollama installation

The user selected the host-installed Ollama rather than a containerized instance.
This supersedes the all-services-in-Compose requirement for the model provider.
The rest of the stack remains Docker-first. Rename compose.yaml to
docker-compose.yaml for discoverability; Docker Compose auto-discovers either name.

API and worker receive OLLAMA_URL, CHAT_MODEL and EMBEDDING_MODEL explicitly.
Docker Desktop uses host.docker.internal; a host-gateway entry supports Linux.
Readiness still probes the actual Ollama HTTP API with a bounded timeout. Compose
cannot manage host process readiness, so the host service must be started separately.

Local manifests identify qwen3:4b and embeddinggemma:latest. These become defaults;
no models are downloaded or deleted. File presence does not establish successful
inference or measured model quality. Embedding dimensions remain unverified.
