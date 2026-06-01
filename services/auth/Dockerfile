FROM golang:1.26-alpine AS builder
WORKDIR /build

COPY services/proto/go services/proto/go
COPY services/auth services/auth

WORKDIR /build/services/auth
RUN go mod tidy && CGO_ENABLED=0 GOOS=linux go build -o /auth .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata
COPY --from=builder /auth /auth
EXPOSE 8001 9001
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD wget -qO- http://localhost:8001/health || exit 1
ENTRYPOINT ["/auth"]
