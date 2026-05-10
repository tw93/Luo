.PHONY: install fetch build font-audit print-proof release-check ship all clean

PY ?= python3

install:
	$(PY) -m pip install -r requirements.txt

fetch:
	$(PY) scripts/fetch_base_font.py

build:
	$(PY) scripts/build.py

font-audit:
	$(PY) scripts/catalog_chinese_fonts.py

print-proof:
	weasyprint proof/a4.html proof/a4.pdf
	magick -density 600 proof/a4.pdf -background white -alpha remove -alpha off proof/a4-600dpi.png

release-check: build font-audit print-proof
	$(PY) -m fontTools.ttx -l dist/Luo-Regular.ttf >/dev/null

# Ship: build then run the QA triad. Stops before staging so the human
# decides what to commit. Build is non-deterministic (woff2 byte order
# varies across runs), so the rule is: run `make ship`, then immediately
# `git add` + `git commit` without re-running the build, otherwise the
# cache-bust hash drifts away from the binary you measured.
ship: build
	$(PY) scripts/check_frozen_glyphs.py
	$(PY) scripts/compare_to.py
	$(PY) scripts/measure_groups.py
	@echo ""
	@echo "Build + QA done. Cache-bust hash:"
	@cat assets/asset_version.txt
	@echo ""
	@echo "Stage now (do NOT rebuild before commit):"
	@echo "  git add HANDOFF.md STYLE.md index.html assets/asset_version.txt \\\\"
	@echo "          assets/styles/luo.css assets/styles/print.css \\\\"
	@echo "          dist/Luo-Regular.ttf dist/Luo-Regular.woff2 \\\\"
	@echo "          proof/similarity_lxgw.json scripts/build.py \\\\"
	@echo "          scripts/compare_to.py scripts/measure_groups.py \\\\"
	@echo "          scripts/check_frozen_glyphs.py \\\\"
	@echo "          scripts/measure_refinement_baselines.py \\\\"
	@echo "          scripts/render_refinement_sheet.py"

all: build font-audit print-proof

clean:
	# .otf removed in v0.3 cleanup; the rule still wipes any leftover from older builds.
	# Keep only the public source similarity baseline in proof/; private
	# reference reports live under ignored local/ref/ and are wiped below.
	# Finding by name keeps the rule explicit
	# instead of relying on shell globbing.
	rm -f dist/Luo-Regular.otf dist/Luo-Regular.ttf dist/Luo-Regular.woff2 \
	      proof/*.pdf proof/*.png proof/*.txt proof/*-preview.html proof/gb2312.html
	find proof -maxdepth 1 -name '*.json' \
	    ! -name 'similarity_lxgw.json' -delete
	rm -rf proof/similarity_images
	rm -rf local/ref
