.PHONY: build up down restart logs ps clean

IMAGE_NAME ?= nanobot

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

restart: down build up

logs:
	docker compose logs -f

ps:
	docker compose ps

clean: down
	docker compose down -v --remove-orphans
	docker system prune -f
