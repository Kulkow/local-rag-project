# ADR 0003: Build the existing MinIO release from source

Docker Hub minio/minio pulls fail; Quay also has reported authorization failures.
Avoid depending on another upstream MinIO image registry or an unreviewed mirror.
Keep the selected MinIO release and build its source in a multi-stage Dockerfile.
Source commit 16f8cf1c52f0a77eeb8f7565aaf7f7df12454583 corresponds to
RELEASE.2024-12-18T13-15-44Z. Verify checkout identity and Go module checksums.

The runtime includes CA roots and the upstream AGPL license and runs as UID 10001.
Keep the minio-data volume, API URL, console port and explicit environment-provided
credentials. Add readiness healthchecking before API startup. This is a packaging
fix, not a new storage component or a data migration.

Costs: compiling source requires network access and additional first-build CPU/RAM.
The upstream repository is archived and this old release is not claimed to have
current security fixes. Updating the storage version is a separate compatibility
and security review. Local container execution is blocked by the sandbox.

Sources:
- https://github.com/minio/minio/releases/tag/RELEASE.2024-12-18T13-15-44Z
- https://github.com/minio/minio/commit/16f8cf1c52f0a77eeb8f7565aaf7f7df12454583
- https://access.redhat.com/solutions/7148629
