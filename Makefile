.PHONY: install seed run test lint
install:
	python -m pip install -e '.[dev]'
seed:
	python -m scripts.seed
run:
	uvicorn app.main:app --reload

test:
	pytest --cov=app --cov-report=term-missing

lint:
	ruff check app tests scripts
