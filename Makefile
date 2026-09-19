OUT = redactions.csv
SEED = seeds/redactions.yaml
# Serving database, used only to validate that every redacted id exists.
# db.sqlite is a symlink to server-chicagocrashes/data/db.sqlite; if it's
# missing the build still runs, minus the id check.
DB ?= db.sqlite
.DEFAULT_GOAL := build

.PHONY: build check test black black-check

# Build redactions.csv from seeds/redactions.yaml. The CSV is committed at the
# repo root and consumed by server-chicagocrashes (`make db-update-redactions`)
# straight from raw.githubusercontent.com, so commit and push after a rebuild.
build:
	python scripts/build_redactions.py --seed $(SEED) --out $(OUT) --db $(DB)

# Re-validate the seed against the db without rewriting the CSV.
check:
	python scripts/build_redactions.py --seed $(SEED) --out /dev/null --db $(DB)

test:
	python -m pytest tests/ -q

black:
	black scripts tests

black-check:
	black --check scripts tests
