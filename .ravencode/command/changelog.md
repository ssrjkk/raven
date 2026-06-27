# Changelog Command

Generate a changelog entry from recent commits.

## Usage
```
/changelog <since-ref>
```

## Behavior
- Reads commits since the given ref (or last tag)
- Groups by type (feat, fix, breaking)
- Formats in Keep a Changelog style
