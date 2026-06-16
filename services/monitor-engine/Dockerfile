FROM golang:1.26-alpine AS builder
WORKDIR /build
RUN apk add --no-cache gcc musl-dev
COPY services/monitor-engine services/monitor-engine
WORKDIR /build/services/monitor-engine
RUN go mod tidy && \
    CGO_ENABLED=1 GOOS=linux go build -ldflags="-s -w -linkmode external -extldflags -static" -o /monitor-engine .

FROM alpine:3.20
RUN adduser -D -g '' -u 1001 nonroot && \
    apk add --no-cache wget ca-certificates
COPY --from=builder /monitor-engine /monitor-engine
USER nonroot
EXPOSE 8003
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:8003/health || exit 1
ENTRYPOINT ["/monitor-engine"]
