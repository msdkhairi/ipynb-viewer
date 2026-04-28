# Security Policy

## Supported Versions

Security fixes are provided for the latest released version of `ipynb-viewer`.

## Reporting A Vulnerability

Please report security issues privately by email:

```text
pypi@masoudka.com
```

Include enough detail to reproduce the issue, including the package version,
Python version, operating system, and a minimal notebook when possible.

## Security Model

`ipynb-viewer` is a local reader for saved notebooks.

- It does not execute notebook code.
- It restricts notebook file access to the configured `--root`.
- It sanitizes markdown-rendered HTML and rich HTML outputs.
- It streams decoded media assets from a local cache directory.

Avoid binding the server to public interfaces unless you intentionally want
other machines to access it. Use `--host 127.0.0.1` for loopback-only access.
