# Every target is also runnable without make: `python -m iplwp.cli <stage>`.
ifeq ($(OS),Windows_NT)
PY ?= .venv/Scripts/python.exe
else
PY ?= .venv/bin/python
endif
CLI = $(PY) -m iplwp.cli

.PHONY: profile data features baseline tune final edgecases export test all

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

edgecases:
	$(CLI) edgecases

export:
	$(CLI) export

test:
	$(PY) -m pytest -q
	node docs/tests/parity.test.mjs
	node docs/tests/teams.test.mjs
	node docs/tests/result_text.test.mjs

all: profile data features baseline tune final edgecases export
