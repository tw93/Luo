.PHONY: install fetch build font-audit print-proof release-check all clean

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

all: build font-audit print-proof

clean:
	rm -f dist/Luo-Regular.otf dist/Luo-Regular.ttf dist/Luo-Regular.woff2 proof/*.pdf proof/*.png proof/*.json proof/*.txt proof/*-preview.html
