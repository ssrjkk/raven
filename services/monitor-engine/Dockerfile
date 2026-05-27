FROM golang:1.22-alpine AS builder
WORKDIR /build
COPY . .
RUN go mod tidy
RUN CGO_ENABLED=0 GOOS=linux go build -o /monitor-engine .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata sqlite-libs
COPY --from=builder /monitor-engine /monitor-engine
EXPOSE 8003
ENTRYPOINT ["/monitor-engine"]
