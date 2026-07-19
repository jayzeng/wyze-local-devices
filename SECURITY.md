# Security Policy

## Supported Versions

The `main` branch is the supported version.

## Reporting a Vulnerability

Please do not open a public issue for credential leaks, token handling bugs, or device-control vulnerabilities.

Report vulnerabilities privately through GitHub Security Advisories for this repository. Include reproduction steps, affected commands, expected impact, and any relevant logs with secrets redacted.

## Secret Handling

This project reads Wyze credentials and tokens from environment variables or a local `.env` file. Keep `.env` files out of git and rotate credentials immediately if they are exposed.
