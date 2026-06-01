FROM golang:1.26-alpine AS builder
WORKDIR /build

COPY services/monitor-engine services/monitor-engine

WORKDIR /build/services/monitor-engine
RUN go mod tidy && CGO_ENABLED=0 GOOS=linux go build -o /monitor-engine .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata
COPY --from=builder /monitor-engine /monitor-engine
EXPOSE 8003
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD wget -qO- http://localhost:8003/health || exit 1
ENTRYPOINT ["/monitor-engine"]
