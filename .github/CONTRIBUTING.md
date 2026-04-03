# Contributing to Susu Cloud

Thank you for your interest in contributing! This guide covers how to set up a development environment, run tests, and submit changes.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/SimonD0711/susu-cloud-ai-companion-on-whatsapp.git
cd susu-cloud-ai-companion-on-whatsapp

# Install dev dependencies
pip install -r requirements.txt

# Copy environment template
copy .env.example .env
# Edit .env and fill in your API keys
```

## Running the Application

```bash
# Start the WhatsApp agent (port 9100)
python wa_agent.py

# Start the admin web server (port 9001) in a separate terminal
python susu_admin_server.py
```

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html
```

## Code Style

This project uses **Ruff** for linting and formatting.

```bash
# Check for issues
ruff check .

# Auto-fix issues
ruff check . --fix
```

Key conventions:
- Python 3.11+ syntax
- UTF-8 encoding throughout
- Docstrings for all public functions
- Type hints preferred for new code

## Branching Strategy

1. Fork the repository and create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes. Keep commits atomic and well-described:
   ```bash
   git commit -m "feat: add new search provider for weather"
   ```

3. Push to your fork and open a Pull Request against `main`.

## Pull Request Checklist

- [ ] Tests pass (`pytest tests/`)
- [ ] No lint errors (`ruff check .`)
- [ ] New features include docstrings
- [ ] Changes are documented in the PR description
- [ ] Commits follow the [Conventional Commits](https://www.conventionalcommits.org/) format (optional but encouraged)

## Project Structure

```
susu-cloud/
├── wa_agent.py              # Main WhatsApp agent (monolith)
├── susu_admin_server.py     # Admin web API server
├── susu_admin_core.py       # Admin backend core
├── susu-memory-admin.html   # Admin web UI
├── src/
│   ├── ai/                  # AI capability layer (LLM, TTS, Whisper, Search)
│   └── wa_agent/            # Modular agent components
├── tests/                   # pytest test suite
└── .github/
    └── workflows/          # CI/CD pipelines
```

## Getting Help

Open an [Issue](https://github.com/SimonD0711/susu-cloud-ai-companion-on-whatsapp/issues) if you find a bug or have a feature request.
