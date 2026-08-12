.PHONY: run install

run:
	.venv/bin/ts

install:
	@if [ -d .venv ]; then echo ".venv already exists, skipping. Run 'rm -rf .venv && make install' to reinstall."; else python -m venv .venv && .venv/bin/pip install -e .; fi

dev:
	.venv/bin/python -m tianshu.main
