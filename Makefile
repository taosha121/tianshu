.PHONY: run serve install

run:
	.venv/bin/ts

serve:
	.venv/bin/ts-server $(PROJECT)

install:
	@if [ -d .venv ]; then echo ".venv already exists, skipping. Run 'rm -rf .venv && make install' to reinstall."; else python -m venv .venv && .venv/bin/pip install -e .; fi

dev:
	.venv/bin/python -m tianshu.main
