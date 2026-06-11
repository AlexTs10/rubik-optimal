# Research Plan

The purpose of this file is to guide verified literature and formatting research for a delivered thesis.

## Research goals

The thesis needs verified sources for:

1. Rubik's Cube mathematical model.
2. Face-turn / half-turn metric.
3. State space size and constraints.
4. Group-theoretic view of permutations and orientations.
5. God's Number = 20.
6. Thistlethwaite's algorithm.
7. Kociemba's two-phase algorithm.
8. Korf's IDA* optimal solver and pattern databases.
9. A* / IDA* and admissible heuristics.
10. Pattern databases and disjoint pattern databases.
11. Coordinate/pruning-table implementation concepts.
12. Pocket Cube / 2x2x2 state-space material, if used.
13. University of Patras / ECE thesis formatting or deposit rules.
14. Prolog/Kallipos material mentioned in the topic brief, if used.

## Bibliography scale

Target:

- at least 20 verified sources for the final thesis;
- preferably 20-30 if the final body is near the 90-120 page target;
- fewer only if the supervisor explicitly approves a smaller bibliography.

The final bibliography should mix:

- peer-reviewed search/heuristic papers;
- algorithm-author technical pages;
- reputable cube mathematics references;
- official university/department rules;
- implementation/library documentation only where directly relevant.

## Source quality priority

Prefer sources in this order:

1. peer-reviewed papers;
2. books or official university course notes;
3. official technical pages by algorithm authors;
4. official University of Patras / ECE pages;
5. reputable technical documentation;
6. broad encyclopedic pages only for general background.

## Primary source targets

### Korf

Richard E. Korf, "Finding Optimal Solutions to Rubik's Cube Using Pattern Databases", AAAI 1997.

Research tasks:

- verify title;
- verify venue;
- verify year;
- obtain bibliographic entry;
- summarize contribution;
- explain IDA* and pattern database use.

### A* and IDA*

Research tasks:

- verify foundational A* and IDA* references;
- distinguish graph search, tree search, admissibility, consistency, and memory tradeoffs;
- cite the definitions used by the thesis.

### Kociemba

Herbert Kociemba's two-phase algorithm materials.

Research tasks:

- verify author and algorithm description;
- identify official documentation;
- explain phase 1 and phase 2;
- explain pruning tables;
- clarify that standard two-phase is practical and usually near-optimal, not automatically globally optimal.

### Thistlethwaite

Thistlethwaite subgroup algorithm sources.

Research tasks:

- verify historical details;
- identify subgroup chain;
- explain how solving proceeds through increasingly restricted groups;
- clarify optimality limitations.

### God's Number

Rokicki, Kociemba, Davidson, and Dethridge sources on God's Number = 20.

Research tasks:

- verify authors;
- verify result;
- explain that the thesis cites this result but does not reproduce the full proof unless actually implemented.

### Pattern databases

Culberson and Schaeffer pattern database sources.

Research tasks:

- verify paper metadata;
- explain admissibility;
- explain disjoint pattern databases where relevant;
- connect pattern databases to the implemented table heuristic.

### Cube mathematics and state constraints

Research tasks:

- verify reachable-state count;
- verify orientation and parity constraints;
- cite a source suitable for the cubie model explanation.

### Pocket Cube / 2x2x2

Research tasks:

- verify state count and distance-distribution facts if cited;
- distinguish the 2x2 case study from claims about full 3x3 optimality.

### University rules

Research current official guidance for:

- thesis formatting;
- cover page;
- deposit process;
- language rules;
- declarations;
- committee/supervisor requirements;
- template availability.

Only use official `upatras.gr` or `ece.upatras.gr` sources for requirements. If no official template is found, document the fallback format.

## Research notes format

For every source, add an entry to `docs/research_notes.md`:

```text
Source ID:
Full citation:
URL or DOI:
Access date:
Source type:
Main claims:
How it will be used in thesis:
BibTeX key:
Verification status:
```

## Bibliography policy

- Add verified sources to `thesis/references.bib`.
- Remove sources that are not cited.
- Do not include unverified bibliography entries in the final thesis.
- If a source cannot be verified, add it to `docs/SOURCES_TO_FETCH.md`.

