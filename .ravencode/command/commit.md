# Commit Command

Generate a conventional commit message based on staged changes.

## Usage
```
/commit
```

## Behavior
- Reads `git diff --cached`
- Generates a commit message following Conventional Commits spec
- Allows editing before committing

## Format
```
<type>(<scope>): <description>

<body>

<footer>
```

Types: feat, fix, chore, docs, style, refactor, perf, test, ci, security
