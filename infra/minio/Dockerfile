FROM golang:1.23.4-alpine3.21 AS builder
RUN apk add --no-cache git ca-certificates
WORKDIR /src
# RELEASE.2024-12-18T13-15-44Z: pin the source commit, not a moving branch.
RUN git init . \
    && git remote add origin https://github.com/minio/minio.git \
    && git fetch --depth=1 origin 16f8cf1c52f0a77eeb8f7565aaf7f7df12454583 \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = 16f8cf1c52f0a77eeb8f7565aaf7f7df12454583
ENV CGO_ENABLED=0 GOTOOLCHAIN=local
RUN go mod download && go mod verify
RUN go build -mod=readonly -trimpath -o /out/minio .

FROM alpine:3.21.0 AS runtime
RUN apk add --no-cache ca-certificates \
    && addgroup -g 10001 minio \
    && adduser -D -u 10001 -G minio minio \
    && mkdir -p /data /licenses \
    && chown minio:minio /data
COPY --from=builder /out/minio /usr/local/bin/minio
COPY --from=builder /src/LICENSE /licenses/MinIO-LICENSE
LABEL org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.revision="16f8cf1c52f0a77eeb8f7565aaf7f7df12454583" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
USER 10001:10001
EXPOSE 9000 9001
ENTRYPOINT ["/usr/local/bin/minio"]
CMD ["server", "/data", "--console-address", ":9001"]
