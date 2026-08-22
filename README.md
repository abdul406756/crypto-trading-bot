# Crypto Trading Bot

A Python-based crypto trading system with automated trading, a FastAPI web dashboard, PostgreSQL database, Telegram control panel, Docker deployment, and systemd deployment support.

## Main Technologies

- Python
- FastAPI
- PostgreSQL
- Binance API
- Telegram Bot API
- Docker
- Docker Compose
- Linux / Ubuntu
- systemd
- HTML / CSS / JavaScript

## Main Components

- `crypto_bot.py` - trading bot
- `api.py` - systemd dashboard backend
- `api_docker.py` - Docker dashboard backend
- `control_panel_bot.py` - systemd Telegram control panel
- `docker_control_panel_bot.py` - Docker Telegram control panel
- `database.py` - PostgreSQL integration
- `docker-compose.yml` - Docker services
- `Dockerfile` - Docker image configuration

## Security

API keys, Telegram tokens, passwords, and other secrets are stored in environment variables and are not committed to GitHub.

## Deployment

The project supports two deployment methods:

1. Docker Compose
2. Linux systemd
