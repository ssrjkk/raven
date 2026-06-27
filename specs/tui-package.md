# TUI Package Specification

## Overview

Terminal UI for Raven AI, built with Python Textual framework.

## Features

- Chat interface with message history
- Agent session management
- Monitor status display
- Task execution tracking
- File browser and code viewer

## Key Bindings

| Key | Action |
|-----|--------|
| `Ctrl+N` | New session |
| `Ctrl+D` | Delete session |
| `Ctrl+F` | Search messages |
| `Ctrl+P` | Toggle sidebar |
| `Escape` | Close panel |
| `Tab` | Focus next widget |

## Layout

```
┌─────────────────────────────────────┐
│ Header: Raven AI v1.0.0    [status] │
├──────────┬──────────────────────────┤
│ Sessions │    Chat Area             │
│ List     │                          │
│          │                          │
│ ──────── │                          │
│ Monitors │                          │
│ Tasks    │                          │
│          ├──────────────────────────┤
│          │ Input Bar                │
└──────────┴──────────────────────────┘
```
