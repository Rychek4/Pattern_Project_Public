# Contributing to Pattern Project

Thank you for your interest in contributing to Pattern Project! This document provides guidelines for contributing.

## Getting Started

### Prerequisites

- Python 3.10+
- An Anthropic API key

### Setup

1. Fork and clone the repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/macOS
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy `.env.example` or create a `.env` file with your API key:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
5. Run the project:
   ```bash
   python main.py
   ```

## How to Contribute

### Reporting Bugs

- Open an issue with a clear description of the bug
- Include steps to reproduce, expected behavior, and actual behavior
- Include Python version and OS information

### Suggesting Features

- Open an issue describing the feature and its use case
- Explain how it fits into the existing architecture

### Submitting Changes

1. Create a feature branch from `main`
2. Make your changes with clear, descriptive commits
3. Ensure your code follows the existing style (no linter is enforced yet, but match the surrounding code)
4. Test your changes manually
5. Open a pull request with a description of what changed and why

## Architecture Overview

Before contributing, review these docs to understand the system:

- [Architecture](docs/ARCHITECTURE.md) — System design
- [Data Flow](docs/DATA_FLOW.md) — How context flows through the system
- [Prompt System](docs/prompts/PROMPT_SYSTEM_OVERVIEW.md) — Prompt assembly

### Key Principles

- **Memory lives in the database, not the context** — Don't accumulate state in the context window
- **Pluggable architecture** — New context sources, tools, and gateways should be self-contained modules
- **AI agency with boundaries** — Autonomous features must respect user-controlled limits
- **Graceful degradation** — Optional features (TTS, Telegram, webcam) should fail silently when unavailable

## Code Style

- Follow existing patterns in the codebase
- Use docstrings for public functions and classes
- Keep modules focused — one responsibility per file where practical

## Questions?

Open an issue for any questions about contributing.
