.PHONY: test real-run archive-baseline

test:
	python3 -m unittest discover -s tests

real-run:
	scripts/run_real_pipeline.sh

archive-baseline:
	@if [ -z "$(RUN_ID)" ]; then \
		echo "Usage: make archive-baseline RUN_ID=<run_id> [NAME=latest_real_run]"; \
		exit 2; \
	fi
	python3 scripts/archive_run_baseline.py --run-id "$(RUN_ID)" --name "$(or $(NAME),latest_real_run)" --force
