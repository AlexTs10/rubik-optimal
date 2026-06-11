# Requirements Extracted from Thesis Topic Brief

Source file:

```text
specs/topic_brief.pdf
```

This file summarizes the requirements from the official topic brief. If this summary conflicts with the PDF, the PDF is the source of truth.

## Thesis title

Greek:

```text
Αλγόριθμοι Βέλτιστης Επίλυσης για τον Κύβο του Rubik
```

English:

```text
Optimal Solution Algorithms for Rubik's Cube
```

## Institution

```text
Πανεπιστήμιο Πατρών
Τμήμα Ηλεκτρολόγων Μηχανικών και Τεχνολογίας Υπολογιστών
Εργαστήριο Ενσύρματης Τηλεπικοινωνίας
Ομάδα Τεχνητής Νοημοσύνης
```

## Supervisor

```text
Κυριάκος Σγάρμπας, Αναπληρωτής Καθηγητής
```

Contact details are in the original brief and should not be duplicated unnecessarily unless required by the official thesis template.

## Desired background

The topic brief expects familiarity with:

- Algorithms and Data Structures;
- Artificial Intelligence I and II;
- adequate programming ability.

## Problem description

The brief states that the Rubik's Cube can be solved optimally in at most 20 moves from any state.

An optimal solution is defined as a sequence of moves that solves the cube with no shorter solving sequence from the same initial state.

The metric is the face-turn / half-turn metric:

- a face rotation by ±90° counts as one move;
- a face rotation by 180° counts as one move.

## Required / desired objectives

The work should achieve as many as possible of the following:

1. Implement the algorithms:
   - Thistlethwaite;
   - Kociemba;
   - Korf.

2. Use Python and/or Prolog.

3. Run the implementations on a conventional computer.

4. Implement an algorithm that accepts a cube state and recognizes how many moves away it is from the solved state.

5. Find a suitable heuristic function for optimal cube solving with A* or a variant of A*.

For thesis wording, objectives 4 and 5 must remain distinct:

- Objective 4 is exact state-distance recognition. The repository may report an exact distance only when an exhaustive or admissible exact search completes for the specific input. Otherwise it must report a documented lower bound, an unknown/timeout status, or an invalid-state result.
- Objective 5 is the admissible-heuristic contribution for A* or a variant. In this repository that answer is the Korf/IDA* track with native-generated projection tables, corner PDB, edge PDBs, and cost-partitioned edge-PDB experiments. H48/Nissy/RubikOptimal evidence can support exact backend/oracle discussions, but it must not replace the native Korf/IDA* heuristic explanation.

## Research character

The brief describes the work as having high research character and possibly leading to publication.

This means the repository and thesis should emphasize:

- correctness;
- reproducibility;
- literature review;
- experiments;
- clear limitations;
- comparison of algorithms;
- careful use of the word "optimal".

## References listed in the brief

The brief lists references related to:

1. Rubik's Cube overview.
2. Optimal solutions for the Rubik's Cube.
3. God's Number is 20.
4. Laboratory exercises in Artificial Intelligence with Prolog, Chapter 11.

Codex must verify and replace broad web references with stronger primary/technical sources where possible, while still acknowledging the sources listed in the brief.

Current provenance handling:

- Brief references [1] and [2] are broad Wikipedia references. They are acknowledged as topic-brief context, but the thesis should cite stronger technical sources for group/state-space facts, optimal-search algorithms, and pattern databases instead of relying on Wikipedia for technical claims.
- Brief reference [3], `cube20.org`, is retained as the topic-brief source for God's Number and is paired in the bibliography/research notes with the stronger SIAM publication on the Rubik's Cube group diameter. The repository must not claim to reproduce that proof.
- Brief reference [4], the Kallipos Prolog text, is cited directly as the Prolog/AI source from the brief. The repository currently uses Python/native code, which remains compatible with the brief's "Python and/or Prolog" wording unless the supervisor requests a Prolog appendix.
