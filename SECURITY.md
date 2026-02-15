# Security Policy

## Sensitive Data

Pattern Project handles several categories of sensitive data:

- **API keys** (Anthropic, ElevenLabs, Telegram) — stored in `.env`, never committed
- **Browser credentials** — stored in `credentials.toml`, never committed
- **Conversation history** — stored in local SQLite database (`data/pattern.db`)
- **Extracted memories** — stored in the same database with vector embeddings

All secrets are loaded from environment variables or local config files that are excluded from version control via `.gitignore`.

## Reporting a Vulnerability

If you discover a security vulnerability in Pattern Project, please:

1. **Do not** open a public issue
2. Email the maintainer directly (or open a private security advisory on GitHub)
3. Include a description of the vulnerability, steps to reproduce, and potential impact

We will acknowledge receipt within 72 hours and work toward a fix.

## Security Considerations

- **File operations** are sandboxed to the `data/files/` directory
- **Email sending** uses a recipient whitelist to prevent abuse
- **Web fetching** uses a domain whitelist
- **Web search** has a daily budget limit (default: 30/day)
- **Communication gateways** have rate limiting enabled by default
- **Browser credentials** are only accessed during ephemeral delegation tasks and never reach the AI's main conversation or memory

## Best Practices for Users

- Use a dedicated API key for this project, not your primary one
- Use app-specific passwords for email and browser automation
- Keep your `.env` and `credentials.toml` files secure
- Review the `data/` directory periodically — it contains your full conversation and memory history
- Run the project in a user account with minimal system privileges
