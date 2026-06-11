# Research Notes

Access dates for web-verified sources: 2026-05-16 for the main bibliography expansion and 2026-05-26 for the H48/Nissy additions.

## Sources Collected

### Source ID: Korf1997Pattern

Full citation: Richard E. Korf, "Finding Optimal Solutions to Rubik's Cube Using Pattern Databases", AAAI/IAAI 1997, pp. 700-705.  
URL or DOI: https://dblp.org/rec/conf/aaai/Korf97 and https://aaai.org/Papers/AAAI/1997/AAAI97-109.pdf  
Source type: conference paper metadata and AAAI paper PDF.  
Main claims: IDA* with pattern database lower bounds was used to find optimal solutions for random Rubik's Cube instances.  
How it will be used in thesis: background for Korf/IDA* and pattern database motivation.  
BibTeX key: `korf1997pattern`  
Verification status: Verified from DBLP metadata and AAAI PDF search result.

### Source ID: Korf1985IDA

Full citation: Richard E. Korf, "Depth-First Iterative-Deepening: An Optimal Admissible Tree Search", Artificial Intelligence 27(1), 97-109, 1985.  
URL or DOI: https://doi.org/10.1016/0004-3702(85)90084-0  
Source type: journal article metadata.  
Main claims: depth-first iterative deepening is an optimal admissible tree search framework.  
How it will be used in thesis: formal background for iterative-deepening/IDA-style exact search.  
BibTeX key: `korf1985iddfs`  
Verification status: Verified from ScienceDirect/DBLP search metadata.

### Source ID: CulbersonSchaeffer1996

Full citation: Joseph C. Culberson and Jonathan Schaeffer, "Searching with Pattern Databases", Advances in Artificial Intelligence, LNCS 1081, Springer, 1996, pp. 402-416.  
URL or DOI: https://bibbase.org/network/publication/culberson-schaeffer-searchingwithpatterndatabases-1996  
Source type: bibliographic metadata.  
Main claims: pattern databases store exact distances for abstractions and can provide heuristic guidance.  
How it will be used in thesis: background for admissible pattern database heuristics.  
BibTeX key: `culberson1996pdb`  
Verification status: Verified from bibliographic metadata.

### Source ID: KociembaTwoPhase

Full citation: Herbert Kociemba, "The Two-Phase Algorithm" and "Two-Phase Algorithm Details".  
URL or DOI: https://kociemba.org/math/twophase.htm and https://kociemba.org/math/imptwophase.htm  
Source type: official technical author documentation.  
Main claims: phase 1 reaches the subgroup with oriented corners/edges and UD-slice constraints; phase 2 solves inside the reduced subgroup; the method is inspired by Thistlethwaite and uses coordinates/pruning tables.  
How it will be used in thesis: Kociemba and Thistlethwaite algorithm descriptions and optimality caveats.  
BibTeX keys: `kociembaTwoPhase`, `kociembaImplementationDetails`  
Verification status: Verified from Kociemba official pages.

### Source ID: GodsNumber20

Full citation: Tomas Rokicki, Herbert Kociemba, Morley Davidson, and John Dethridge, "God's Number is 20", 2010.  
URL or DOI: https://www.cube20.org/  
Source type: project/announcement page by the result authors.  
Main claims: every reachable 3x3 Rubik's Cube position can be solved in at most 20 HTM moves; the proof used large-scale computation and does not require optimally solving every individual position.  
How it will be used in thesis: external citation for God's Number, with no claim that this repository reproduces the proof.  
BibTeX key: `rokicki2010godsnumber`  
Verification status: Verified from the project page.

### Source ID: KalliposProlog

Full citation: Κυριάκος Σγάρμπας, "Εργαστηριακές Ασκήσεις Τεχνητής Νοημοσύνης με τη Γλώσσα Prolog", Κάλλιπος, 2024.  
URL or DOI: https://dx.doi.org/10.57713/kallipos-378  
Source type: Kallipos open textbook metadata.  
Main claims: Prolog/AI laboratory guide referenced by the topic brief.  
How it will be used in thesis: acknowledged as the Prolog/Kallipos source from the brief, without building a Prolog implementation in this repository.  
BibTeX key: `sgarbas2024prolog`  
Verification status: Verified from Kallipos search result metadata.

### Source ID: HartNilssonRaphael1968

Full citation: Peter E. Hart, Nils J. Nilsson, and Bertram Raphael, "A Formal Basis for the Heuristic Determination of Minimum Cost Paths", IEEE Transactions on Systems Science and Cybernetics 4(2), 100-107, 1968.  
URL or DOI: https://doi.org/10.1109/TSSC.1968.300136  
Source type: journal article metadata.  
Main claims: A* is a formal heuristic shortest-path search method when the heuristic conditions support optimality.  
How it will be used in thesis: general background for admissible heuristic search before IDA*.  
BibTeX key: `hart1968astar`  
Verification status: Verified from DOI metadata/search result.

### Source ID: Pearl1984Heuristics

Full citation: Judea Pearl, "Heuristics: Intelligent Search Strategies for Computer Problem Solving", Addison-Wesley, 1984.  
URL or DOI: https://www.osti.gov/biblio/5127296  
Source type: book bibliographic metadata.  
Main claims: systematic treatment of heuristic search and heuristic evaluation functions.  
How it will be used in thesis: broader search-theory context for admissible and practical heuristics.  
BibTeX key: `pearl1984heuristics`  
Verification status: Verified from OSTI bibliographic metadata.

### Source ID: RussellNorvig2020AIMA

Full citation: Stuart Russell and Peter Norvig, "Artificial Intelligence: A Modern Approach", 4th edition, Pearson, 2020.  
URL or DOI: https://aima.cs.berkeley.edu/  
Source type: textbook publisher/author site metadata.  
Main claims: standard AI search vocabulary, including uninformed search, heuristic search, and problem formulation.  
How it will be used in thesis: terminology support for BFS, search frontiers, state spaces, and heuristic search.  
BibTeX key: `russellNorvig2020aima`  
Verification status: Verified from official AIMA site.

### Source ID: CLRS2022

Full citation: Thomas H. Cormen, Charles E. Leiserson, Ronald L. Rivest, and Clifford Stein, "Introduction to Algorithms", 4th edition, MIT Press, 2022.  
URL or DOI: https://mitpress.mit.edu/9780262046305/introduction-to-algorithms/  
Source type: publisher metadata.  
Main claims: graph-search and algorithm-analysis background, including asymptotic cost framing.  
How it will be used in thesis: general complexity and graph-search background, not as Rubik-specific evidence.  
BibTeX key: `cormen2022clrs`  
Verification status: Verified from MIT Press metadata.

### Source ID: FelnerKorfHanan2004

Full citation: Ariel Felner, Richard E. Korf, and Sarit Hanan, "Additive Pattern Database Heuristics", Journal of Artificial Intelligence Research 22, 279-318, 2004.  
URL or DOI: https://doi.org/10.1613/jair.1480 and https://jair.org/index.php/jair/article/view/10337  
Source type: journal article metadata.  
Main claims: additive pattern databases can combine disjoint abstractions to produce stronger admissible heuristics.  
How it will be used in thesis: explains why stronger pattern databases are future work beyond the current CO/EO/UD-slice lower bound.  
BibTeX key: `felner2004additivePDB`  
Verification status: Verified from JAIR metadata.

### Source ID: RokickiDiameter2013

Full citation: Tomas Rokicki, Herbert Kociemba, Morley Davidson, and John Dethridge, "The Diameter of the Rubik's Cube Group Is Twenty", SIAM Journal on Discrete Mathematics 27(2), 1082-1105, 2013.  
URL or DOI: https://doi.org/10.1137/120867366  
Source type: journal article metadata.  
Main claims: formal publication of the computational proof that the 3x3 Rubik's Cube group diameter is 20 in the relevant metric.  
How it will be used in thesis: authoritative external reference for the God's Number statement, with explicit limitation that this repository does not reproduce the proof.  
BibTeX key: `rokicki2013diameter`  
Verification status: Verified from DOI/search metadata.

### Source ID: DemaineRubik2011

Full citation: Erik D. Demaine, Martin L. Demaine, Sarah Eisenstat, Anna Lubiw, and Andrew Winslow, "Algorithms for Solving Rubik's Cubes", ESA 2011, LNCS 6942, 689-700.  
URL or DOI: https://doi.org/10.1007/978-3-642-23719-5_58 and https://erikdemaine.org/papers/Rubik_ESA2011/  
Source type: conference paper metadata and author page.  
Main claims: asymptotic algorithms and bounds for generalized Rubik-type puzzles.  
How it will be used in thesis: complexity context beyond the fixed physical 3x3 cube.  
BibTeX key: `demaine2011rubik`  
Verification status: Verified from DOI/author page metadata.

### Source ID: DemaineRubikNPComplete2018

Full citation: Erik D. Demaine, Sarah Eisenstat, and Mikhail Rudoy, "Solving the Rubik's Cube Optimally is NP-complete", STACS 2018, LIPIcs 96.  
URL or DOI: https://doi.org/10.4230/LIPIcs.STACS.2018.24 and https://erikdemaine.org/papers/Rubik_STACS2018/  
Source type: conference paper metadata and author page.  
Main claims: optimal solving is NP-complete for generalized Rubik's Cube variants.  
How it will be used in thesis: careful complexity context; no claim that the fixed 3x3 decision problem has this asymptotic classification.  
BibTeX key: `demaine2018npcomplete`  
Verification status: Verified from DOI/author page metadata.

### Source ID: Joyner2008GroupTheory

Full citation: David Joyner, "Adventures in Group Theory: Rubik's Cube, Merlin's Machine, and Other Mathematical Toys", 2nd edition, Johns Hopkins University Press, 2008.  
URL or DOI: https://doi.org/10.56021/9780801890123 and https://www.press.jhu.edu/books/title/9554/adventures-group-theory  
Source type: publisher metadata.  
Main claims: mathematical group-theoretic treatment of Rubik's Cube and related puzzles.  
How it will be used in thesis: background for viewing cube states and moves as a generated group.  
BibTeX key: `joyner2008adventures`  
Verification status: Verified from publisher metadata.

### Source ID: Singmaster1981Notes

Full citation: David Singmaster, "Notes on Rubik's Magic Cube", 5th edition, Enslow Publishers, 1981.  
URL or DOI: https://aadl.org/catalog/record/10168932  
Source type: library catalog metadata.  
Main claims: classic notation and early systematic treatment of the cube.  
How it will be used in thesis: historical/notation background only.  
BibTeX key: `singmaster1981notes`  
Verification status: Verified from library catalog metadata.

### Source ID: ScherphuisThistlethwaite

Full citation: Jaap Scherphuis, "Thistlethwaite's 52-move Algorithm".  
URL or DOI: https://www.jaapsch.net/puzzles/thistle.htm  
Source type: technical puzzle mathematics webpage.  
Main claims: describes the subgroup chain and 52-move framing for Thistlethwaite-style solving.  
How it will be used in thesis: implementation background for subgroup phases, clearly secondary to primary algorithm evidence.  
BibTeX key: `scherphuisThistlethwaite`  
Verification status: Verified from the webpage.

### Source ID: RandelshoferPocketCube

Full citation: Werner Randelshofer, "Virtual Cubes: Pocket Cube Instructions".  
URL or DOI: https://www.randelshofer.ch/rubik/virtual_cubes/pocket/instructions/2x_instructions_big.html  
Source type: technical puzzle instruction webpage.  
Main claims: describes the 2x2x2 Pocket Cube and its cubie-level behavior.  
How it will be used in thesis: background only; benchmark distribution values come from repository-generated result files.  
BibTeX key: `randelshoferPocketCube`  
Verification status: Verified from the webpage.

### Source ID: SageCubeGroup

Full citation: The Sage Developers, "Rubik's Cube Group Functions".  
URL or DOI: https://doc.sagemath.org/html/en/reference/groups/sage/groups/perm_gps/cubegroup.html  
Source type: official software documentation.  
Main claims: exposes Rubik's Cube group operations as computational algebra objects.  
How it will be used in thesis: independent software-context reference for group-based cube modelling.  
BibTeX key: `sageCubeGroup`  
Verification status: Verified from official Sage documentation.

### Source ID: GAPRubikExample

Full citation: Martin Schoenert, "Analyzing Rubik's Cube with GAP", GAP examples documentation, 2003.  
URL or DOI: https://www.math.rwth-aachen.de/~GAP/WWW2/Gap3/Doc3/Examples3/rubik.html  
Source type: software example documentation.  
Main claims: demonstrates permutation-group analysis of Rubik's Cube with GAP.  
How it will be used in thesis: computational-algebra context and cross-check concept, not as benchmark evidence.  
BibTeX key: `gapRubikExample`  
Verification status: Verified from GAP documentation page.

### Source ID: KociembaCubeExplorer

Full citation: Herbert Kociemba, "Cube Explorer Download and Solver Notes".  
URL or DOI: https://www.kociemba.org/download.htm  
Source type: solver author software/documentation page.  
Main claims: documents practical Cube Explorer solver tooling around Kociemba-style solving.  
How it will be used in thesis: practical implementation context for two-phase solvers; repository results still come from local scripts.  
BibTeX key: `kociembaCubeExplorer`  
Verification status: Verified from Kociemba webpage.

### Source ID: KociembaTwoPhase

Full citation: Herbert Kociemba, "The Two-Phase Algorithm".  
URL or DOI: https://kociemba.org/math/twophase.htm  
Source type: solver author technical documentation page.  
Main claims: describes the two-phase algorithm: phase 1 reduces an arbitrary state into the subgroup G1 and phase 2 finishes inside it; iterative deepening over the phase-1 length yields successively better total solutions.  
How it will be used in thesis: primary description of the two-phase design implemented by the scoped native solver and discussed in the algorithms chapter.  
BibTeX key: `kociembaTwoPhase`  
Verification status: Verified from the Kociemba official webpage on 2026-06-11.

### Source ID: KociembaImplementationDetails

Full citation: Herbert Kociemba, "Two-Phase Algorithm Details".  
URL or DOI: https://kociemba.org/math/imptwophase.htm  
Source type: solver author technical documentation page.  
Main claims: documents implementation-level conventions for the two-phase algorithm, including cubie-level representation, coordinates, move tables and symmetry-reduced pruning tables.  
How it will be used in thesis: source for the cubie/coordinate conventions adopted by the cube model and for the phase-1 pruning-table design.  
BibTeX key: `kociembaImplementationDetails`  
Verification status: Verified from the Kociemba official webpage on 2026-06-11.

### Source ID: KociembaOptimalSolver

Full citation: Herbert Kociemba, "The Optimal Solvers".  
URL or DOI: https://www.kociemba.org/math/optimal.htm  
Source type: solver author technical documentation page.  
Main claims: documents the optimal-solver framing, including phase-1-style pruning and multi-axis/triple-search ideas used by practical optimal cube solvers.  
How it will be used in thesis: background for why H48/DR/HTR-style native optimal solving needs strong pruning tables rather than only faster DFS code.  
BibTeX key: `kociembaOptimalSolver`  
Verification status: Verified from Kociemba official webpage on 2026-05-26.

### Source ID: RokickiNxopt

Full citation: Tomas Rokicki, "Nxopt: An Optimal Rubik's Cube Solver".  
URL or DOI: https://github.com/rokicki/cube20src/blob/master/nxopt.md  
Source type: source-repository technical documentation.  
Main claims: describes an optimal-solver architecture using compressed pruning-table data and search refinements that influenced later public solvers.  
How it will be used in thesis: reference for the compressed-table/fallback-table design lineage discussed in relation to H48.  
BibTeX key: `rokickiNxopt`  
Verification status: Verified from the public cube20 source repository on 2026-05-26.

### Source ID: ReidSuperflip1995

Full citation: Michael Reid, "superflip requires 20 face turns", Cube-Lovers mailing list, 18 January 1995.  
URL or DOI: https://www.math.rwth-aachen.de/~Martin.Schoenert/Cube-Lovers/michael_reid__superflip_requires_20_face_turns.html  
Source type: archived mailing-list posting (primary source).  
Main claims: exhaustive computation showing the superflip position requires 20 face turns in HTM, establishing the first lower bound of 20 for the diameter of the cube group.  
How it will be used in thesis: primary citation for the superflip lower bound of 20, compared against the thesis's own native exhaustive proof.  
BibTeX key: `reid1995superflip`  
Verification status: Verified from the archived Cube-Lovers posting (Schönert RWTH archive) on 2026-06-11.

### Source ID: ReidOptimal1997

Full citation: Michael Reid, "optimal cube solver", Cube-Lovers mailing list, 5 July 1997.  
URL or DOI: https://www.cube20.org/cubelovers/cube-mail-23.txt  
Source type: archived mailing-list posting (primary source).  
Main claims: describes Reid's optimal solver computing the phase-1 distance on all three axes and using the maximum as an admissible lower bound for IDA*.  
How it will be used in thesis: primary citation for the three-axis admissible bound used by the native superflip optimality proof; Reid's own cflmath.com domain is parked, so the mailing-list archive is the citable source.  
BibTeX key: `reid1997optimal`  
Verification status: Verified inside cube-mail-23.txt at the cube20.org Cube-Lovers archive on 2026-06-11.

### Source ID: MuodovKociembaPkg

Full citation: muodov, "kociemba: Python/C implementation of Herbert Kociemba's two-phase algorithm", PyPI package `kociemba`, version 1.2.1, GPLv2, 2019.  
URL or DOI: https://github.com/muodov/kociemba  
Source type: open-source package repository.  
Main claims: provides the practical external two-phase solver used as the adapter baseline.  
How it will be used in thesis: attribution of the external adapter package in the literature review, experiments and third-party notices (author handle per THIRD_PARTY_NOTICES.md).  
BibTeX key: `muodovKociembaPkg`  
Verification status: Verified against docs/THIRD_PARTY_NOTICES.md and the GitHub repository on 2026-06-11.

### Source ID: TrontoNissyCoreH48

Full citation: Sebastiano Tronto and Enrico Tenuti, "nissy-core: The H48 Optimal Solver".  
URL or DOI: https://git.tronto.net/nissy-core/file/doc/h48.md.html  
Source type: public GPL source repository and technical documentation.  
Main claims: documents an HTM-optimal H48 solver using fully symmetric pruning tables, H48 coordinates, fallback tables, inverse estimates, and parallel search; the implementation is GPL-3.0-or-later.  
How it will be used in thesis: direct source/attribution for the vendored in-repository H48 backend and its table-generation metadata.  
BibTeX key: `trontoNissyCoreH48`  
Verification status: Verified from the public nissy-core repository and vendored license on 2026-05-26.
