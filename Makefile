# Every target is also runnable without make: `python -m iplwp.cli <stage>`.
ifeq ($(OS),Windows_NT)
PY ?= .venv/Scripts/python.exe
else
PY ?= .venv/bin/python
endif
CLI = $(PY) -m iplwp.cli

.PHONY: profile data features baseline tune final export test all

profile:
	$(CLI) profile

data:
	$(CLI) data

features:
	$(CLI) features

baseline:
	$(CLI) baseline

tune:
	$(CLI) tune

final:
	$(CLI) final

export:
	$(CLI) export

test:
	$(PY) -m pytest -q
	node docs/tests/parity.test.mjs

all: profile data features baseline tune final export
