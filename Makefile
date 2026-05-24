SHELL := /bin/bash

UV ?= uv
PYTHON := $(UV) run --no-sync python
PYTEST := $(UV) run python -m pytest
SKILL_PIXEL := skills/pixel-perfect-design-to-code
EVALS_PIXEL := $(SKILL_PIXEL)/evals
TESTS_PIXEL := $(EVALS_PIXEL)/tests

.PHONY: all test test-unit test-eval-fast test-eval-fixtures test-eval-integration test-eval-report test-live eval-quick eval-report eval-live-smoke eval-live-benchmark codex-run clean

all: test

test: test-unit

test-unit:
	$(PYTEST) $(TESTS_PIXEL) -m "not live"

test-eval-fast:
	$(PYTEST) $(TESTS_PIXEL) -m "eval and fast"

test-eval-fixtures: test-eval-fast

test-eval-integration:
	$(PYTEST) $(TESTS_PIXEL) -m "eval and integration"

test-eval-report:
	$(PYTHON) $(EVALS_PIXEL)/workflow.py report

test-live:
	RUN_LIVE_EVALS=1 $(PYTEST) $(TESTS_PIXEL)/evals -m "eval and live"

eval-quick:
	$(PYTHON) $(EVALS_PIXEL)/workflow.py quick

eval-report:
	$(PYTHON) $(EVALS_PIXEL)/workflow.py report

eval-live-smoke:
	$(PYTHON) $(EVALS_PIXEL)/workflow.py live-smoke

eval-live-benchmark:
	$(PYTHON) $(EVALS_PIXEL)/workflow.py live-benchmark --repeat 3

codex-run: test-live

clean:
	rm -rf .pixel-goal
	rm -rf $(EVALS_PIXEL)/__pycache__ $(EVALS_PIXEL)/mobile_grid_overlay/__pycache__ $(EVALS_PIXEL)/transcripts
	rm -rf $(EVALS_PIXEL)/codex_exec_answers.json $(EVALS_PIXEL)/grading.json $(EVALS_PIXEL)/benchmark.json
	rm -rf $(EVALS_PIXEL)/runs
	rm -rf $(TESTS_PIXEL)/__pycache__ $(TESTS_PIXEL)/evals/__pycache__ $(SKILL_PIXEL)/skills/pixel-perfect-design-to-code/scripts/__pycache__
	rm -rf *.pyc
