.PHONY: run install test

run:
	.venv/bin/ts

install:
	@if [ -d .venv ]; then echo ".venv already exists, skipping. Run 'rm -rf .venv && make install' to reinstall."; else python -m venv .venv && .venv/bin/pip install -e ".[dev]"; fi

test:
	.venv/bin/pytest
