package main

import (
	"encoding/json"
	"net/http"
)

type ErrorCode string

const (
	ErrInvalidInput     ErrorCode = "INVALID_INPUT"
	ErrUnauthorized     ErrorCode = "UNAUTHORIZED"
	ErrForbidden        ErrorCode = "FORBIDDEN"
	ErrNotFound         ErrorCode = "NOT_FOUND"
	ErrConflict         ErrorCode = "CONFLICT"
	ErrRateLimited      ErrorCode = "RATE_LIMITED"
	ErrUpstream         ErrorCode = "UPSTREAM_ERROR"
	ErrInternal         ErrorCode = "INTERNAL_ERROR"
	ErrAuthUnavailable  ErrorCode = "AUTH_UNAVAILABLE"
)

type ErrorResponse struct {
	Error   string     `json:"error"`
	Code    ErrorCode  `json:"code,omitempty"`
	Details string     `json:"details,omitempty"`
}

func writeError(w http.ResponseWriter, status int, code ErrorCode, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(ErrorResponse{Error: msg, Code: code})
}

func httpStatusForCode(code ErrorCode) int {
	switch code {
	case ErrInvalidInput:
		return http.StatusBadRequest
	case ErrUnauthorized:
		return http.StatusUnauthorized
	case ErrForbidden:
		return http.StatusForbidden
	case ErrNotFound:
		return http.StatusNotFound
	case ErrConflict:
		return http.StatusConflict
	case ErrRateLimited:
		return http.StatusTooManyRequests
	case ErrUpstream, ErrAuthUnavailable:
		return http.StatusBadGateway
	default:
		return http.StatusInternalServerError
	}
}
