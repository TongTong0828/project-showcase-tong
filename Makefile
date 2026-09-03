# Makefile — unified entry points for paper_rag.

PY ?= python3
PYTHONPATH := src:tests
DSH_DIR := integrations/deepseek-harness
DSH_PORT ?= 3080
DSH_RUNTIME_ROOT := data/runtime/deepseek-harness

.PHONY: help install install-dev lint format test test-pytest smoke secret-scan mineru-doctor mineru-download-layout rebuild-index validate-metadata \
        qdrant-up qdrant-down init-store ingest ask eval clean clean-data \
        docker-build docker-build-bake docker-up-proactive docker-cli docker-shell \
        calibrate-abstain hard-cases eval-golden eval-golden-qa eval-report eval-citation-audit eval-ablation eval-claims eval-claims-report eval-claims-judge eval-llm-recall verify-p0 \
        dsh-install dsh-doctor dsh-start dsh-smoke dsh-test dsh-clean-runtime workbench

help:
	@echo "Targets:"
	@echo "  dsh-install   Install DeepSeek Harness dependencies"
	@echo "  dsh-doctor    Audit DeepSeek Harness config and paper-research preset"
	@echo "  dsh-start     Start DeepSeek Harness Paper RAG UI on 127.0.0.1:$(DSH_PORT)"
	@echo "  dsh-smoke     Run DeepSeek Harness smoke checks"
	@echo "  dsh-test      Run DeepSeek Harness deterministic tests"
	@echo "  dsh-clean-runtime  Remove DSH versioned sessions/storages/presets, preserving credentials"
	@echo "  workbench     Start Paper RAG Workbench on 127.0.0.1:3090 and API on 127.0.0.1:3091"
	@echo "  install        Install runtime deps (editable)"
	@echo "  install-dev    Install dev + mineru extras"
	@echo "  lint           Run ruff check"
	@echo "  format         Run ruff format"
	@echo "  test           Run pure-logic tests (no qdrant / no llm) via _run_tests.py"
	@echo "  test-pytest    Run tests via pytest (richer output, fixtures)"
	@echo "  smoke          Walk all modules and assert importable count"
	@echo "  secret-scan    Scan source/config/docs for accidental API keys"
	@echo "  mineru-doctor  Diagnose local MinerU/magic-pdf readiness"
	@echo "  mineru-download-layout  Download MinerU doclayout_yolo weight"
	@echo "  rebuild-index  Rebuild SQLite/Qdrant from existing data/parsed files"
	@echo "  validate-metadata  Check SQLite/Qdrant payloads and local asset paths"
	@echo "  qdrant-up      Start Qdrant docker container"
	@echo "  qdrant-down    Stop & remove Qdrant container"
	@echo "  init-store     Build SQLite tables + Qdrant collections"
	@echo "  ingest ID=...  Ingest one (e.g. make ingest ID=2310.12345)"
	@echo "  ask Q=...      Ask a question (e.g. make ask Q='What is X?')"
	@echo "  eval           Run retrieval-only eval on example set"
	@echo "  eval-golden    Run retrieval-only eval on the strict golden set"
	@echo "  eval-golden-qa Run full QA no-judge eval on the strict golden set"
	@echo "  eval-report    Run golden retrieval eval and write Markdown report"
	@echo "  eval-citation-audit Run QA eval and write citation audit Markdown"
	@echo "  eval-ablation  Compare retrieval strategies on the golden set"
	@echo "  eval-claims    Run claim-level QA no-judge eval"
	@echo "  eval-claims-report Run claim eval and write Markdown report"
	@echo "  eval-claims-judge  Run optional claim eval with LLM judge"
	@echo "  eval-llm-recall Compare no/local/LLM rewrite retrieval recall"
	@echo "  verify-p0      Run lint, focused tests, smoke, secret scan, golden retrieval"
	@echo "  calibrate-abstain  Re-run threshold calibration (offline mode)"
	@echo "  hard-cases     Collect hard cases from feedback events"
	@echo "  docker-build   Build paper_rag image (lean, ~600MB)"
	@echo "  docker-build-bake  Build with bge-m3 pre-warmed (~3GB)"
	@echo "  docker-up-proactive  Start proactive cron sidecar (compose)"
	@echo "  docker-cli CMD='...'  Run one-shot command in fresh container"
	@echo "  docker-shell   Drop into bash inside fresh container"
	@echo "  clean          Remove pycache & build artifacts"
	@echo "  clean-data     DELETE data/ (DANGEROUS)"

install:
	$(PY) -m pip install -e .

install-dev:
	$(PY) -m pip install -e .[dev,mineru]

lint:
	ruff check src tests

format:
	ruff format src tests

test:
	@PYTHONPATH=$(PYTHONPATH) $(PY) scripts/_run_tests.py

test-pytest:
	@$(PY) -m pytest -q --ignore=tests/eval

smoke:
	@PYTHONPATH=src $(PY) scripts/_run_smoke.py

secret-scan:
	@$(PY) scripts/secret_scan.py

mineru-doctor:
	$(PY) scripts/mineru_doctor.py

mineru-download-layout:
	$(PY) scripts/download_mineru_layout_model.py

rebuild-index:
	$(PY) scripts/rebuild_index_from_parsed.py

validate-metadata:
	$(PY) scripts/validate_metadata_paths.py --strict

dsh-install:
	cd $(DSH_DIR) && pnpm install --frozen-lockfile

dsh-doctor:
	cd $(DSH_DIR) && PAPER_RAG_DSH_PORT=$(DSH_PORT) pnpm dsh:dump-config

dsh-start:
	set -a; [ ! -f .env ] || . ./.env; set +a; \
	    cd $(DSH_DIR) && PAPER_RAG_DSH_PORT=$(DSH_PORT) pnpm start

dsh-smoke:
	cd $(DSH_DIR) && PAPER_RAG_DSH_PORT=$(DSH_PORT) pnpm smoke

dsh-test:
	cd $(DSH_DIR) && pnpm test

dsh-clean-runtime:
	rm -rf $(DSH_RUNTIME_ROOT)/versions

workbench:
	.venv/bin/python scripts/start_workbench.py

qdrant-up:
	bash scripts/up_qdrant.sh

qdrant-down:
	-docker rm -f paper-rag-qdrant

init-store:
	$(PY) scripts/init_store.py

ingest:
	@if [ -z "$(ID)" ]; then echo "Usage: make ingest ID=<arxiv-id>"; exit 1; fi
	$(PY) scripts/ingest_one.py --arxiv $(ID)

ask:
	@if [ -z "$(Q)" ]; then echo "Usage: make ask Q='your question'"; exit 1; fi
	$(PY) scripts/ask.py "$(Q)"

eval:
	$(PY) tests/eval/run_eval.py --file tests/eval/qa_set.example.jsonl --retrieval-only

eval-golden:
	set -a; [ ! -f .env ] || . ./.env; set +a; \
	    PAPER_RAG_CONFIG=$${PAPER_RAG_CONFIG:-$(CURDIR)/config/local.yaml} \
	    PAPER_RAG_FORCE_LOCAL_REWRITE=1 \
	    PYTHONPATH=$(CURDIR)/src:$(CURDIR)/tests \
	    $(PY) tests/eval/run_eval.py \
	        --file tests/eval/qa_set.golden.jsonl \
	        --retrieval-only \
	        --top-k $${EVAL_TOP_K:-10} \
	        --gate tests/eval/gates.strict.json

eval-golden-qa:
	set -a; [ ! -f .env ] || . ./.env; set +a; \
	    PAPER_RAG_CONFIG=$${PAPER_RAG_CONFIG:-$(CURDIR)/config/local.yaml} \
	    PAPER_RAG_FORCE_LOCAL_REWRITE=1 \
	    PYTHONPATH=$(CURDIR)/src:$(CURDIR)/tests \
	    $(PY) tests/eval/run_eval.py \
	        --file tests/eval/qa_set.golden.jsonl \
	        --no-judge \
	        --top-k $${EVAL_TOP_K:-10} \
	        --gate tests/eval/gates.strict.json

eval-report:
	set -a; [ ! -f .env ] || . ./.env; set +a; \
	    PAPER_RAG_CONFIG=$${PAPER_RAG_CONFIG:-$(CURDIR)/config/local.yaml} \
	    PAPER_RAG_FORCE_LOCAL_REWRITE=1 \
	    PYTHONPATH=$(CURDIR)/src:$(CURDIR)/tests \
	    $(PY) tests/eval/run_eval.py \
	        --file tests/eval/qa_set.golden.jsonl \
	        --retrieval-only \
	        --top-k $${EVAL_TOP_K:-10} \
	        --gate tests/eval/gates.strict.json \
	        --report-md $${EVAL_REPORT_MD:-docs/RAG_EVAL_REPORT.md}

eval-citation-audit:
	set -a; [ ! -f .env ] || . ./.env; set +a; \
	    PAPER_RAG_CONFIG=$${PAPER_RAG_CONFIG:-$(CURDIR)/config/local.yaml} \
	    PAPER_RAG_FORCE_LOCAL_REWRITE=1 \
	    PYTHONPATH=$(CURDIR)/src:$(CURDIR)/tests \
	    $(PY) tests/eval/run_eval.py \
	        --file tests/eval/qa_set.golden.jsonl \
	        --no-judge \
	        --top-k $${EVAL_TOP_K:-10} \
	        --citation-audit-md $${EVAL_CITATION_AUDIT_MD:-docs/RAG_CITATION_AUDIT.md}

eval-ablation:
	set -a; [ ! -f .env ] || . ./.env; set +a; \
	    PAPER_RAG_CONFIG=$${PAPER_RAG_CONFIG:-$(CURDIR)/config/local.yaml} \
	    PAPER_RAG_FORCE_LOCAL_REWRITE=1 \
	    PYTHONPATH=$(CURDIR)/src:$(CURDIR)/tests \
	    $(PY) tests/eval/run_ablation.py \
	        --file tests/eval/qa_set.golden.jsonl \
	        --top-k $${EVAL_TOP_K:-10} \
	        --out $${EVAL_ABLATION_OUT:-data/index/eval_runs/ablation_latest.json}

eval-claims:
	set -a; [ ! -f .env ] || . ./.env; set +a; \
	    PAPER_RAG_CONFIG=$${PAPER_RAG_CONFIG:-$(CURDIR)/config/local.yaml} \
	    PAPER_RAG_FORCE_LOCAL_REWRITE=1 \
	    PYTHONPATH=$(CURDIR)/src:$(CURDIR)/tests \
	    $(PY) tests/eval/run_claim_eval.py \
	        --file tests/eval/qa_set.claims.jsonl \
	        --top-k $${EVAL_TOP_K:-10} \
	        --gate tests/eval/gates.claims.json

eval-claims-report:
	set -a; [ ! -f .env ] || . ./.env; set +a; \
	    PAPER_RAG_CONFIG=$${PAPER_RAG_CONFIG:-$(CURDIR)/config/local.yaml} \
	    PAPER_RAG_FORCE_LOCAL_REWRITE=1 \
	    PYTHONPATH=$(CURDIR)/src:$(CURDIR)/tests \
	    $(PY) tests/eval/run_claim_eval.py \
	        --file tests/eval/qa_set.claims.jsonl \
	        --top-k $${EVAL_TOP_K:-10} \
	        --gate tests/eval/gates.claims.json \
	        --report-md $${EVAL_CLAIM_REPORT_MD:-docs/RAG_CLAIM_EVAL_REPORT.md}

eval-claims-judge:
	set -a; [ ! -f .env ] || . ./.env; set +a; \
	    PAPER_RAG_CONFIG=$${PAPER_RAG_CONFIG:-$(CURDIR)/config/local.yaml} \
	    PAPER_RAG_FORCE_LOCAL_REWRITE=1 \
	    PYTHONPATH=$(CURDIR)/src:$(CURDIR)/tests \
	    $(PY) tests/eval/run_claim_eval.py \
	        --file tests/eval/qa_set.claims.jsonl \
	        --top-k $${EVAL_TOP_K:-10} \
	        --judge \
	        --report-md $${EVAL_CLAIM_REPORT_MD:-docs/RAG_CLAIM_EVAL_REPORT.md}

eval-llm-recall:
	set -a; [ ! -f .env ] || . ./.env; set +a; \
	    PAPER_RAG_CONFIG=$${PAPER_RAG_CONFIG:-$(CURDIR)/config/local.yaml} \
	    PYTHONPATH=$(CURDIR)/src:$(CURDIR)/tests \
	    $(PY) tests/eval/run_llm_recall.py \
	        --file tests/eval/qa_set.claims.jsonl \
	        --top-k $${EVAL_TOP_K:-10} \
	        --out $${EVAL_LLM_RECALL_OUT:-data/index/eval_runs/llm_recall_latest.json} \
	        --report-md $${EVAL_LLM_RECALL_REPORT_MD:-docs/RAG_LLM_RECALL_REPORT.md}

verify-p0:
	$(PY) -m ruff check src/paper_rag/rag/abstain.py src/paper_rag/rag/query_rewrite.py src/paper_rag/rag/evidence_select.py tests/test_abstain.py tests/test_m5_fixes.py tests/test_eval_metrics.py tests/test_eval_harness.py tests/test_evidence_selection.py tests/test_claim_eval.py tests/test_llm_recall_eval.py tests/eval/run_eval.py tests/eval/run_claim_eval.py tests/eval/run_llm_recall.py tests/eval/claim_metrics.py scripts/secret_scan.py
	$(PY) -m pytest tests/test_abstain.py tests/test_m5_fixes.py tests/test_eval_metrics.py tests/test_eval_harness.py tests/test_evidence_selection.py tests/test_claim_eval.py tests/test_llm_recall_eval.py tests/test_chaos.py::test_qa_agentic_uses_selected_evidence_for_prompt_and_trace tests/test_finalization.py::test_stream_answer_uses_selected_evidence_for_done_payload
	PYTHONPATH=src $(PY) scripts/_run_smoke.py
	$(PY) scripts/secret_scan.py
	$(MAKE) eval-golden PY=$(PY)

calibrate-abstain:
	$(PY) scripts/calibrate_abstain.py --mode offline \
	    --qa-set tests/eval/qa_set.real.jsonl \
	    --out data/index/abstain_calibration.json

hard-cases:
	$(PY) scripts/collect_hard_cases.py --since 30d \
	    --out tests/eval/hard_cases.jsonl

# ── Docker (M9.5) ────────────────────────────────────────────────────────────
DOCKER_TAG ?= paper-rag:lean

docker-build:
	docker build -t $(DOCKER_TAG) .

docker-build-bake:
	docker build -t paper-rag:bake --build-arg MODE=bake .

docker-up-proactive:
	cd .. && docker compose -f docker/docker-compose.yaml up -d paper_rag_proactive

docker-cli:
	@if [ -z "$(CMD)" ]; then echo "Usage: make docker-cli CMD='python scripts/ask.py ...'"; exit 1; fi
	docker run --rm -it -v $$PWD/data:/opt/paper_rag/data \
	    -v $$PWD/config:/opt/paper_rag/config:ro \
	    --env-file ../.env \
	    $(DOCKER_TAG) cli $(CMD)

docker-shell:
	docker run --rm -it -v $$PWD/data:/opt/paper_rag/data \
	    -v $$PWD/config:/opt/paper_rag/config:ro \
	    --env-file ../.env \
	    $(DOCKER_TAG) shell

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info

clean-data:
	@echo "About to delete data/. Press Ctrl-C in 5s to abort."
	@sleep 5
	rm -rf data/papers data/parsed data/index
