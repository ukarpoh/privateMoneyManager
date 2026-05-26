.PHONY: run dev lint fmt check

run:
	python main.py

dev:
	docker compose up --build

lint:
	ruff check bot/ main.py

fmt:
	ruff format bot/ main.py

check: lint
	ruff check --select I bot/ main.py
