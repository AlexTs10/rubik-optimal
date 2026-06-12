# Sources to Fetch or Verify

Prototype, thesis-scale bibliography sources, current official ECE diploma-thesis/deposit rules, official ECE front-matter template links, and supervisor division/laboratory metadata were verified on 2026-05-16/2026-05-17 and added to `docs/research_notes.md` plus `thesis/references.bib` where citation was appropriate. `scripts/thesis_audit.py` now machine-checks that every BibTeX entry is cited and has a research-note key, and the LaTeX front matter now uses the extracted Greek template wording for the originality/copyright and certification pages. Bibliography/front-matter completion is still not claimed until the supervisor confirms style expectations, provides final personal/committee metadata, and supplies approval evidence for the scoped solver claims.

## Remaining Source / Policy Items

| Topic | Status | Notes |
|---|---|---|
| Thesis-scale bibliography | Machine consistency passed; style review pending | `docs/research_notes.md` records 26 source keys, and `scripts/thesis_audit.py` reports 26 BibTeX entries, 26 cited keys, no uncited BibTeX entries, and no missing research-note keys. Style/coverage still needs supervisor review before final submission. |
| Reference-thesis-level front matter | Needs supervisor confirmation | `docs/reference_thesis_calibration.md` shows the delivered example includes formal certification/declaration-style front matter; exact required wording for this thesis still needs confirmation. |
| University of Patras / ECE thesis and deposit rules | Verified current official sources | Official ECE sources were verified: 2023 diploma-thesis regulation PDF, 2025-2026 study guide PDF, Greek graduation/deposit page, and Greek diploma-theses page. They document Greek writing with extended English abstract, public presentation timing, committee/exam flow, Secretariat/Nemertes deposit, and unified cover/internal format requirement. |
| Actual ECE thesis template files (`υπόδειγμα`) | Verified, archived, and text applied | The current Greek diploma-theses page links to official Greek and English Word templates. They were downloaded and stored as `specs/ece_diploma_template_el.doc` and `specs/ece_diploma_template_en.doc`; the page snapshot is stored as `specs/ece_diploma_theses_page_2026-05-17.html`. The LaTeX first pages now follow the archived template structure and use the extracted Greek originality/copyright and certification wording; remaining work is final metadata and style/scoped-claim approval, not source discovery. |
| Legacy English diploma-thesis URL | Unavailable but no longer blocking | The older English URL `https://www.ece.upatras.gr/en/education/undergraduate/diploma-theses.html` returned 404, but the Greek current page is reachable and contains the official template links. |
| Committee names and examination metadata | Needs student/supervisor input | The current thesis source uses non-final student and committee fields. Supervisor laboratory is filled from `specs/topic_brief.pdf`, and supervisor division is filled from `specs/sgarbas_faculty_page_2026-05-17.html`. `docs/final_metadata_packet.md` lists the exact fields still needed: committee members, exam date, signatures, copyright year, student registration/name format, style/scoped-claim approval, and final approval record. |
| Native solver implementation references | Partially expanded | Added verified references for heuristic search, additive pattern databases, subgroup descriptions, computational algebra tooling, and Pocket Cube background. |
| 2x2x2 God's Number (HTM) and distance distribution | Independently computed; primary citation pending | The exhaustive BFS in `src/rubik_optimal/pocket/` reproduces the full half-turn-metric distance distribution of the normalized 2x2x2 model, with maximum distance 11 and 2,644 antipodal states; `scripts/verify_results.py` and `tests/test_pocket_cube.py` now lock these exact values in, and an independent cubie-vs-table cross-check validates the move-table decomposition. This maximum coincides with the commonly reported 2x2x2 HTM God's Number, but a primary/authoritative citation for that value has not yet been verified in this session. The thesis presents the figure as the computed maximum that coincides with the commonly reported value; a verified primary source should be attached before final submission. |

## Official ECE Sources Verified on 2026-05-16

| Source | Evidence captured | Repository use |
|---|---|---|
| 2023 ECE regulation for diploma theses: `https://www.ece.upatras.gr/images/Attachments/diplomatikes/%CE%9A%CE%B1%CE%BD%CE%BF%CE%BD%CE%B9%CF%83%CE%BC%CF%8C%CF%82_%CE%94%CE%B9%CF%80%CE%BB%CF%89%CE%BC%CE%B1%CF%84%CE%B9%CE%BA%CF%8E%CE%BD_%CE%95%CF%81%CE%B3%CE%B1%CF%83%CE%B9%CF%8E%CE%BD_3_2023.pdf` | Downloaded to `/private/tmp/ece_diploma_reg_2023.pdf`; extracted text confirms supervision/committee rules, Greek thesis language plus extended English abstract, public presentation, Secretariat/Nemertes deposit, and unified cover/internal format according to template. | Cited as `eceDiplomaRegulation2023`; used for institutional context only. |
| ECE undergraduate study guide 2025-2026: `https://www.ece.upatras.gr/images/Attachments/odigos_spoudwn/%CE%9F%CE%94%CE%97%CE%93%CE%9F%CE%A3_%CE%A3%CE%A0%CE%9F%CE%A5%CE%94%CE%A9%CE%9D_2025_2026_ver1.3_5_9_2025.pdf` | Downloaded to `/private/tmp/ece_study_guide_2025_2026.pdf`; extracted text repeats and updates the thesis rules and template-reference requirement. | Cited as `eceStudyGuide2025`; current-year cross-check. |
| ECE graduation/deposit page: `https://www.ece.upatras.gr/index.php/el/information/links/useful-links/orkomosia` | Downloaded to `/private/tmp/ece_orkomosia.html`; HTML confirms post-presentation grade-sheet handling, final thesis CD in PDF/Word, Nemertes protocol number, and no printed thesis copy. | Cited as `eceOrkomosiaPage2026`; deposit checklist support. |
| ECE diploma-theses page and template links: `https://www.ece.upatras.gr/index.php/el/undergraduate/diploma-theses.html` | Downloaded to `/private/tmp/ece_diploma_theses_el.html`; HTML links the 2023 regulation and official Word templates `ΠΡΟΤΥΠΟ_ΠΡΩΤΕΣ_ΣΕΛΙΔΕΣ.doc` and `ΠΡΟΤΥΠΟ_ΠΡΩΤΕΣ_ΣΕΛΙΔΕΣ_ΑΓΓΛΙΚΑ_ΤΕΛΙΚΟ.doc`. | Cited as `eceDiplomaThesesPage2026`; template artifacts archived under `specs/`. |
| Official ECE faculty page for Κυριάκος Σγάρμπας: `https://www.ece.upatras.gr/index.php/el/faculty/sgarmpas.html` | Downloaded to `specs/sgarbas_faculty_page_2026-05-17.html`; HTML states `Σγάρμπας Κυριάκος`, `Αναπληρωτής Καθηγητής`, and `Τομέας Τηλεπικοινωνιών και Τεχνολογίας Πληροφορίας`. | Used as source-backed front-matter metadata for supervisor division. |

## Prototype Completed Source Checklist

| Topic | Source | Status |
|---|---|---|
| Korf IDA* and pattern databases | Korf AAAI 1997 via DBLP/AAAI | Verified |
| A* / IDA* | Korf Artificial Intelligence 1985 | Verified |
| Pattern databases | Culberson and Schaeffer 1996 | Verified |
| Kociemba two-phase algorithm | Kociemba official pages | Verified |
| Thistlethwaite subgroup context | Kociemba details and cube20 history | Verified for limited background |
| God's Number = 20 | cube20.org by Rokicki/Kociemba/Davidson/Dethridge | Verified |
| Kallipos Prolog reference | DOI 10.57713/kallipos-378 | Verified |
