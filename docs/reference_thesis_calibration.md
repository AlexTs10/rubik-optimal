# Reference Thesis Calibration

Calibration date: 2026-05-16

Reference file:

```text
/Users/alextoska/Downloads/ΔΙΠΛΩΜΑΤΙΚΗ ΚΟΝΤΟΥΛΗΣ.pdf
```

## Measured properties

Commands used:

```bash
pdfinfo "/Users/alextoska/Downloads/ΔΙΠΛΩΜΑΤΙΚΗ ΚΟΝΤΟΥΛΗΣ.pdf"
pdftotext "/Users/alextoska/Downloads/ΔΙΠΛΩΜΑΤΙΚΗ ΚΟΝΤΟΥΛΗΣ.pdf" /tmp/kontoulis_thesis.txt
wc -w /tmp/kontoulis_thesis.txt
pdfimages -list "/Users/alextoska/Downloads/ΔΙΠΛΩΜΑΤΙΚΗ ΚΟΝΤΟΥΛΗΣ.pdf"
pdftoppm -png -f 1 -l 1 "/Users/alextoska/Downloads/ΔΙΠΛΩΜΑΤΙΚΗ ΚΟΝΤΟΥΛΗΣ.pdf" /tmp/kontoulis_page
```

Observed:

- 106 pages;
- about 24,141 extracted words;
- about 22 embedded images;
- formal University of Patras cover/front matter;
- Greek abstract and English abstract;
- full table of contents;
- dense chapter body;
- implementation screenshots and experiment/result figures;
- bibliography near the end.

## Structural pattern

The delivered example has this broad shape:

1. front matter, declarations/certification, abstracts, contents;
2. introduction;
3. theoretical background;
4. analysis and design;
5. implementation;
6. experiment and evaluation;
7. conclusions, limitations, and future extensions;
8. bibliography.

The most important lesson is not the exact topic or page count. The important lesson is that the thesis reads as a complete engineering/research artifact, not as a short implementation note.

## Target for this Rubik thesis

The Rubik thesis should therefore target:

- 90-120 pages unless supervisor-approved otherwise;
- 22,000-30,000 words of thesis text;
- at least 20 generated or source-documented figures/tables;
- full front matter;
- a substantial theory chapter covering cube mathematics and search;
- a substantial design chapter explaining the solver architecture;
- a substantial implementation chapter showing coordinates, tables, solvers, CLI, and verification;
- an experiment chapter with generated data and interpretation;
- a conclusion chapter that separates achieved work, limitations, and future work.

## Consequence for current repository

The current 21-page build is a useful prototype and reproducibility scaffold, but it is not the delivered thesis target.

The following cannot remain final limitations:

- native Kociemba tables left as future work;
- full Thistlethwaite implementation left as future work;
- all pattern-database work left as future work;
- only an external Kociemba adapter for practical general solving;
- a thesis PDF at short-report length.

Any future limitation must be backed by evidence, and it must not remove all substantial algorithmic contribution from the thesis.

