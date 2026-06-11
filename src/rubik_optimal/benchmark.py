"""Benchmark orchestration for reproducible thesis results."""

from __future__ import annotations

import csv
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path

from .cube import CubeState
from .distance import recognize_distance
from .results import read_jsonl, write_json, write_jsonl
from .scramble import deterministic_scramble
from .search.bfs import exact_distance_bfs
from .solvers.kociemba import solve_kociemba_adapter, solve_kociemba_native_scoped
from .solvers.korf import solve_korf_ida
from .solvers.thistlethwaite import solve_thistlethwaite_native_scoped


def _cases(seed: int, profile: str) -> list[dict[str, object]]:
    quick = profile == "quick"
    if profile == "quick":
        depths = range(1, 6)
        random_depths = (10,)
    elif profile == "stress":
        depths = range(1, 10)
        random_depths = (10, 15, 20, 25)
    else:
        depths = range(1, 9)
        random_depths = (5, 10, 15, 20)

    cases: list[dict[str, object]] = [
        {
            "case_id": "solved",
            "profile": profile,
            "seed": seed,
            "scramble": [],
            "scramble_depth": 0,
            "dataset": "A",
        }
    ]
    for depth in depths:
        cases.append({
            "case_id": f"shallow_{depth}",
            "profile": profile,
            "seed": seed,
            "scramble": deterministic_scramble(depth, seed, offset=depth),
            "scramble_depth": depth,
            "dataset": "B",
        })
    for idx, depth in enumerate(random_depths):
        cases.append({
            "case_id": f"random_{idx}_{depth}",
            "profile": profile,
            "seed": seed,
            "scramble": deterministic_scramble(depth, seed, offset=100 + idx),
            "scramble_depth": depth,
            "dataset": "C",
        })
    return cases


def run_benchmarks(
    seed: int = 2026,
    quick: bool = False,
    root: Path | None = None,
    profile: str | None = None,
    progress: Callable[[str], None] | None = None,
    resume: bool = False,
) -> dict[str, Path]:
    root = root or Path.cwd()
    profile = profile or ("quick" if quick else "thesis")
    quick = profile == "quick"
    suffix = f"seed_{seed}_{profile}"
    raw_path = root / "results" / "raw" / f"benchmarks_{suffix}.jsonl"
    summary_path = root / "results" / "processed" / f"summary_{suffix}.json"
    csv_path = root / "results" / "processed" / f"benchmarks_{suffix}.csv"
    rows: list[dict[str, object]] = []
    completed_keys: set[tuple[str, str]] = set()
    if resume and raw_path.exists():
        rows = read_jsonl(raw_path)
        for row in rows:
            if row.get("profile") != profile or int(row.get("seed", -1)) != seed:
                raise ValueError(
                    f"Cannot resume from rows with a different seed/profile: {raw_path}"
                )
            completed_keys.add((str(row["case_id"]), str(row["solver"])))

    for case in _cases(seed, profile):
        cube = CubeState.solved().apply_sequence(case["scramble"])  # type: ignore[arg-type]
        depth = int(case["scramble_depth"])
        shallow_bfs_depth = 5 if depth <= 5 else 0
        if quick:
            search_timeout = 0.25 if depth > 5 else 2.5
        elif profile == "stress":
            search_timeout = 8.0
        else:
            search_timeout = 5.0
        bfs_distance = None
        if depth <= 5:
            bfs_distance, _ = exact_distance_bfs(cube, max_depth=5)
        distance = recognize_distance(
            cube,
            bfs_depth=shallow_bfs_depth,
            ida_depth=7 if quick else 10,
            timeout_seconds=search_timeout,
        )
        if quick:
            thistle_timeout = search_timeout
        elif profile == "stress":
            thistle_timeout = search_timeout * 4
        else:
            thistle_timeout = 180.0
        solver_specs = [
            (
                "korf_ida_star_scoped",
                lambda: solve_korf_ida(
                    cube,
                    max_depth=7 if quick else 10,
                    timeout_seconds=search_timeout if quick else search_timeout * 4,
                ),
            ),
            (
                "kociemba_native_scoped",
                lambda: solve_kociemba_native_scoped(
                    cube,
                    phase1_max_depth=6 if quick else 10,
                    phase2_max_depth=6 if quick else 14,
                    timeout_seconds=search_timeout if quick else search_timeout * 10,
                ),
            ),
            ("kociemba_two_phase_adapter", lambda: solve_kociemba_adapter(cube)),
            (
                "thistlethwaite_native_scoped",
                lambda: solve_thistlethwaite_native_scoped(
                    cube,
                    stage1_max_depth=6 if quick else 7,
                    stage2_max_depth=6 if quick else 8,
                    stage3_max_depth=6 if quick else 13,
                    stage4_max_depth=6 if quick else 15,
                    stage2_candidate_limit=16 if quick else 8,
                    stage3_candidate_limit=1 if quick else (8 if profile == "stress" else 16),
                    stage4_candidate_limit=1 if quick else 8,
                    timeout_seconds=thistle_timeout,
                    node_limit=100_000 if quick else 500_000,
                ),
            ),
        ]
        for solver_name, solve in solver_specs:
            row_key = (str(case["case_id"]), solver_name)
            if row_key in completed_keys:
                if progress is not None:
                    progress(
                        f"benchmark skip case={case['case_id']} depth={depth} solver={solver_name}"
                    )
                continue
            if progress is not None:
                progress(
                    f"benchmark case={case['case_id']} depth={depth} solver={solver_name}"
                )
            solver = solve()
            row = {
                **case,
                "scramble": " ".join(case["scramble"]),  # type: ignore[arg-type]
                "state": cube.to_facelets(),
                "known_exact_distance": bfs_distance,
                "distance_kind": distance.kind,
                "distance_value": distance.distance_value,
                "distance_method": distance.method,
                "solver": solver.solver_name,
                "solution": " ".join(solver.solution_moves),
                "solution_length": solver.solution_length,
                "metric": solver.metric,
                "runtime_seconds": solver.runtime_seconds,
                "expanded_nodes": solver.expanded_nodes,
                "generated_nodes": solver.generated_nodes,
                "table_size_bytes": solver.table_bytes,
                "status": solver.status,
                "verified": solver.is_verified,
                "notes": solver.notes,
            }
            rows.append(row)
            completed_keys.add(row_key)
            write_jsonl(raw_path, rows)

    write_jsonl(raw_path, rows)
    _write_csv(csv_path, rows)
    summary = _summarize(rows, seed=seed, profile=profile)
    write_json(summary_path, summary)
    _write_thesis_tables(root, rows, summary)
    return {"raw": raw_path, "summary": summary_path, "csv": csv_path}


def generate_benchmark_artifacts_from_saved_results(
    *,
    seed: int = 2026,
    root: Path | None = None,
    profile: str = "thesis",
) -> dict[str, Path]:
    """Regenerate derived CSV, summary, and thesis artifacts from saved raw rows."""

    root = root or Path.cwd()
    suffix = f"seed_{seed}_{profile}"
    raw_path = root / "results" / "raw" / f"benchmarks_{suffix}.jsonl"
    summary_path = root / "results" / "processed" / f"summary_{suffix}.json"
    csv_path = root / "results" / "processed" / f"benchmarks_{suffix}.csv"
    if not raw_path.exists():
        raise FileNotFoundError(
            f"Missing saved benchmark rows at {raw_path}; run `rubik-optimal benchmark` first"
        )
    rows = read_jsonl(raw_path)
    if not rows:
        raise ValueError(f"Saved benchmark rows are empty: {raw_path}")

    bad_profiles = sorted({str(row.get("profile")) for row in rows if row.get("profile") != profile})
    bad_seeds = sorted({str(row.get("seed")) for row in rows if int(row.get("seed", -1)) != seed})
    if bad_profiles or bad_seeds:
        raise ValueError(
            "Saved benchmark rows do not match requested generation context: "
            f"profiles={bad_profiles}, seeds={bad_seeds}"
        )

    _write_csv(csv_path, rows)
    summary = _summarize(rows, seed=seed, profile=profile)
    write_json(summary_path, summary)
    _write_thesis_tables(root, rows, summary)
    return {"raw": raw_path, "summary": summary_path, "csv": csv_path}


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _summarize(rows: list[dict[str, object]], *, seed: int, profile: str) -> dict[str, object]:
    by_solver: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_solver[str(row["solver"])].append(row)
    solvers = {}
    for solver, solver_rows in by_solver.items():
        solved = [r for r in solver_rows if r["verified"] is True and r["solution_length"] is not None]
        runtimes = [float(r["runtime_seconds"]) for r in solver_rows]
        solvers[solver] = {
            "cases": len(solver_rows),
            "verified_solutions": len(solved),
            "statuses": sorted({str(r["status"]) for r in solver_rows}),
            "median_runtime_seconds": statistics.median(runtimes) if runtimes else None,
            "max_solution_length": max((int(r["solution_length"]) for r in solved), default=None),
        }
    return {
        "generated_at_unix": time.time(),
        "seed": seed,
        "profile": profile,
        "quick": profile == "quick",
        "row_count": len(rows),
        "solvers": solvers,
    }


def _write_thesis_tables(root: Path, rows: list[dict[str, object]], summary: dict[str, object]) -> None:
    tables = root / "thesis" / "tables"
    figures = root / "thesis" / "figures"
    tables.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)

    def tex(value: object) -> str:
        return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")

    def dash(value: object) -> str:
        return "--" if value is None or value == "" else tex(value)

    def maybe_float(value: object) -> float | None:
        if value is None or value == "":
            return None
        return float(value)

    def median(values: list[float]) -> float | None:
        return statistics.median(values) if values else None

    def fmt_float(value: float | None) -> str:
        return "--" if value is None else f"{value:.6f}"

    def fmt_int(value: float | int | None) -> str:
        return "--" if value is None else str(int(value))

    def status_short(status: object) -> str:
        return {
            "exact": "E",
            "non_exact": "N",
            "lower_bound": "LB",
            "timeout": "T",
            "not_applicable": "NA",
            "failed": "F",
        }.get(str(status), tex(status))

    def solver_short(solver: object) -> str:
        return {
            "korf_ida_star_scoped": "Korf",
            "kociemba_native_scoped": "Koc. native",
            "kociemba_two_phase_adapter": "Koc. adapter",
            "thistlethwaite_native_scoped": "Thistle.",
        }.get(str(solver), tex(solver))

    def timeout_note_short(row: dict[str, object]) -> str:
        note = str(row["notes"])
        if str(row["solver"]) == "korf_ida_star_scoped":
            if "table_lower_bound=" in note:
                return note.split(";")[0]
            return "IDA* timeout"
        if "Native phase 1" in note:
            return "phase 1 subgroup timeout"
        if "Stage 2" in note:
            return "stage 2 subgroup timeout"
        if "Stage 3" in note:
            if "best_stage3_lower_bound=" in note:
                part = note.split("best_stage3_lower_bound=", 1)[1].split(";", 1)[0]
                return f"stage 3 timeout, lb={part}"
            return "stage 3 restricted timeout"
        if "Four-phase Thistlethwaite chain failed" in note:
            if "stage4_note=" in note and "Stage 4" in note:
                return "stage 4 half-turn timeout"
            if "stage3_note=" in note:
                return "stage 3 HTR timeout"
            return "four-phase timeout"
        return note[:48]

    case_rows_by_id: dict[str, dict[str, object]] = {}
    for row in rows:
        case_rows_by_id.setdefault(str(row["case_id"]), row)
    case_rows = sorted(
        case_rows_by_id.values(),
        key=lambda row: (str(row["dataset"]), int(row["scramble_depth"]), str(row["case_id"])),
    )
    preferred_solver_order = (
        "korf_ida_star_scoped",
        "kociemba_native_scoped",
        "kociemba_two_phase_adapter",
        "thistlethwaite_native_scoped",
    )
    summary_solver_names = list(summary["solvers"].keys())  # type: ignore[union-attr]
    solver_names = [name for name in preferred_solver_order if name in summary_solver_names]
    solver_names.extend(name for name in sorted(summary_solver_names) if name not in solver_names)

    table_rows = []
    for solver, data in summary["solvers"].items():  # type: ignore[index,union-attr]
        statuses = ", ".join(data["statuses"])  # type: ignore[index]
        table_rows.append(
            f"{solver_short(solver)} & {data['cases']} & {data['verified_solutions']} & "
            f"{data['median_runtime_seconds']:.6f} & {tex(statuses)} \\\\"
        )
    (tables / "benchmark_summary.tex").write_text(
        "{\\small\n\\begin{tabular}{L{0.28\\textwidth}rrrL{0.16\\textwidth}}\n"
        "\\hline\n"
        "Solver & Cases & Verified & Median runtime (s) & Statuses \\\\\n"
        "\\hline\n"
        + "\n".join(table_rows)
        + "\n\\hline\n\\end{tabular}\n}\n",
        encoding="utf-8",
    )
    (tables / "algorithm_status.tex").write_text(
        "{\\small\n\\begin{tabular}{L{0.17\\textwidth}L{0.29\\textwidth}L{0.25\\textwidth}L{0.17\\textwidth}}\n"
        "\\hline\n"
        "Algorithm & Implementation status & Optimality status & Evidence \\\\\n"
        "\\hline\n"
        "BFS & Shallow exhaustive search & exact within configured depth & tests/results \\\\\n"
        "Korf/IDA* & Scoped Python IDA* with projection tables and native corner/edge PDB lower bounds & exact when completed & tests + PDB \\\\\n"
        "Korf native optimal & C++ full-cube IDA* with complete corner and 6-edge PDBs & exact when completed & optimal evidence \\\\\n"
        "Kociemba native & Scoped two-phase: exact sym-reduced phase-1 heuristic plus phase-2 projection pruning & non-exact verified when completed & tests + tables \\\\\n"
        "Kociemba adapter & Optional external two-phase adapter & non-exact verified solution & verifier/results \\\\\n"
        "Thistlethwaite native & Four-phase greedy descent over exact BFS stage-distance tables & non-exact verified, guaranteed termination & tests + tables \\\\\n"
        "\\hline\n\\end{tabular}\n}\n",
        encoding="utf-8",
    )
    depth_rows = [
        f"{row['scramble_depth']} & {solver_short(row['solver'])} & {row['runtime_seconds']:.6f} & {row['expanded_nodes']} \\\\"
        for row in rows
        if row["dataset"] == "B" and row["solver"] == "korf_ida_star_scoped"
    ]
    (figures / "runtime_depth_data.tex").write_text(
        "\\begin{tabular}{rp{0.34\\textwidth}rr}\n"
        "\\hline\n"
        "Depth & Solver & Runtime (s) & Expanded nodes \\\\\n"
        "\\hline\n"
        + "\n".join(depth_rows)
        + "\n\\hline\n\\end{tabular}\n",
        encoding="utf-8",
    )

    dataset_rows = []
    for dataset in sorted({str(row["dataset"]) for row in case_rows}):
        subset = [row for row in case_rows if row["dataset"] == dataset]
        depths = [int(row["scramble_depth"]) for row in subset]
        dataset_rows.append(
            f"{tex(dataset)} & {len(subset)} & {min(depths)} & {max(depths)} \\\\"
        )
    (tables / "benchmark_dataset_summary.tex").write_text(
        "\\begin{tabular}{lrrr}\n"
        "\\hline\n"
        "Dataset & Cases & Min depth & Max depth \\\\\n"
        "\\hline\n"
        + "\n".join(dataset_rows)
        + "\n\\hline\n\\end{tabular}\n",
        encoding="utf-8",
    )

    catalog_rows = [
        f"{tex(row['case_id'])} & {tex(row['dataset'])} & {row['scramble_depth']} & {dash(row['scramble'])} \\\\"
        for row in case_rows
    ]
    (tables / "benchmark_case_catalog.tex").write_text(
        "\\begin{tabular}{p{0.22\\textwidth}lrp{0.42\\textwidth}}\n"
        "\\hline\n"
        "Case & Dataset & Depth & Scramble \\\\\n"
        "\\hline\n"
        + "\n".join(catalog_rows)
        + "\n\\hline\n\\end{tabular}\n",
        encoding="utf-8",
    )

    distance_counts = Counter(
        (str(row["distance_kind"]), str(row["distance_method"])) for row in case_rows
    )
    distance_rows = [
        f"{tex(kind)} & {tex(method)} & {count} \\\\"
        for (kind, method), count in sorted(distance_counts.items())
    ]
    (tables / "distance_recognition_summary.tex").write_text(
        "\\begin{tabular}{p{0.24\\textwidth}p{0.36\\textwidth}r}\n"
        "\\hline\n"
        "Distance kind & Method & Cases \\\\\n"
        "\\hline\n"
        + "\n".join(distance_rows)
        + "\n\\hline\n\\end{tabular}\n",
        encoding="utf-8",
    )

    statuses = ("exact", "non_exact", "lower_bound", "timeout", "not_applicable", "failed")
    status_rows = []
    for solver in solver_names:
        counts = Counter(str(row["status"]) for row in rows if row["solver"] == solver)
        status_rows.append(
            f"{solver_short(solver)} & " + " & ".join(str(counts[status]) for status in statuses) + " \\\\"
        )
    (tables / "solver_status_counts.tex").write_text(
        "\\begin{tabular}{p{0.24\\textwidth}rrrrrr}\n"
        "\\hline\n"
        "Solver & Exact & Non-exact & Lower bound & Timeout & N/A & Failed \\\\\n"
        "\\hline\n"
        + "\n".join(status_rows)
        + "\n\\hline\n\\end{tabular}\n",
        encoding="utf-8",
    )

    runtime_rows = []
    for solver in solver_names:
        runtimes = [float(row["runtime_seconds"]) for row in rows if row["solver"] == solver]
        runtime_rows.append(
            f"{solver_short(solver)} & {fmt_float(min(runtimes))} & {fmt_float(median(runtimes))} & {fmt_float(max(runtimes))} \\\\"
        )
    (tables / "solver_runtime_summary.tex").write_text(
        "\\begin{tabular}{p{0.30\\textwidth}rrr}\n"
        "\\hline\n"
        "Solver & Min (s) & Median (s) & Max (s) \\\\\n"
        "\\hline\n"
        + "\n".join(runtime_rows)
        + "\n\\hline\n\\end{tabular}\n",
        encoding="utf-8",
    )

    length_rows = []
    for solver in solver_names:
        lengths = [
            int(row["solution_length"])
            for row in rows
            if row["solver"] == solver and row["verified"] is True and row["solution_length"] is not None
        ]
        length_rows.append(
            f"{solver_short(solver)} & {len(lengths)} & {fmt_int(min(lengths) if lengths else None)} & "
            f"{fmt_float(median([float(value) for value in lengths]))} & {fmt_int(max(lengths) if lengths else None)} \\\\"
        )
    (tables / "solver_solution_length_summary.tex").write_text(
        "\\begin{tabular}{p{0.28\\textwidth}rrrr}\n"
        "\\hline\n"
        "Solver & Verified & Min & Median & Max \\\\\n"
        "\\hline\n"
        + "\n".join(length_rows)
        + "\n\\hline\n\\end{tabular}\n",
        encoding="utf-8",
    )

    node_rows = []
    for solver in solver_names:
        solver_rows = [row for row in rows if row["solver"] == solver]
        expanded = [value for value in (maybe_float(row["expanded_nodes"]) for row in solver_rows) if value is not None]
        generated = [value for value in (maybe_float(row["generated_nodes"]) for row in solver_rows) if value is not None]
        node_rows.append(
            f"{solver_short(solver)} & {fmt_int(median(expanded))} & {fmt_int(median(generated))} \\\\"
        )
    (tables / "solver_node_summary.tex").write_text(
        "\\begin{tabular}{p{0.32\\textwidth}rr}\n"
        "\\hline\n"
        "Solver & Median expanded & Median generated \\\\\n"
        "\\hline\n"
        + "\n".join(node_rows)
        + "\n\\hline\n\\end{tabular}\n",
        encoding="utf-8",
    )

    timeout_rows = []
    for row in rows:
        if row["status"] == "timeout":
            timeout_rows.append(
                f"{solver_short(row['solver'])} & {tex(row['case_id'])} & {row['scramble_depth']} & "
                f"{dash(row['expanded_nodes'])} & {tex(timeout_note_short(row))} \\\\"
            )
    if not timeout_rows:
        timeout_rows = ["-- & -- & -- & -- & No timeout rows \\\\"]
    (tables / "benchmark_timeout_cases.tex").write_text(
        "{\\small\n\\begin{tabular}{L{0.16\\textwidth}L{0.18\\textwidth}rrL{0.30\\textwidth}}\n"
        "\\hline\n"
        "Solver & Case & Depth & Expanded & Note \\\\\n"
        "\\hline\n"
        + "\n".join(timeout_rows)
        + "\n\\hline\n\\end{tabular}\n}\n",
        encoding="utf-8",
    )

    status_by_case = {(str(row["case_id"]), str(row["solver"])): row for row in rows}
    matrix_rows = []
    for case in case_rows:
        cells = []
        for solver in solver_names:
            row = status_by_case[(str(case["case_id"]), solver)]
            length = "" if row["solution_length"] is None else f"/{row['solution_length']}"
            cells.append(f"{status_short(row['status'])}{length}")
        matrix_rows.append(
            f"{tex(case['case_id'])} & {case['scramble_depth']} & " + " & ".join(cells) + " \\\\"
        )
    (tables / "benchmark_case_status_matrix.tex").write_text(
        "\\begin{tabular}{p{0.23\\textwidth}rllll}\n"
        "\\hline\n"
        "Case & Depth & Korf & Koc. native & Koc. adapter & Thistle. \\\\\n"
        "\\hline\n"
        + "\n".join(matrix_rows)
        + "\n\\hline\n\\end{tabular}\n",
        encoding="utf-8",
    )

    (figures / "runtime_by_solver_data.tex").write_text(
        "\\begin{tabular}{p{0.30\\textwidth}rrr}\n"
        "\\hline\n"
        "Solver & Min (s) & Median (s) & Max (s) \\\\\n"
        "\\hline\n"
        + "\n".join(runtime_rows)
        + "\n\\hline\n\\end{tabular}\n",
        encoding="utf-8",
    )

    grouped_lengths: dict[tuple[int, str], list[float]] = defaultdict(list)
    for row in rows:
        if row["verified"] is True and row["solution_length"] is not None:
            grouped_lengths[(int(row["scramble_depth"]), str(row["solver"]))].append(float(row["solution_length"]))
    length_depth_rows = [
        f"{depth} & {solver_short(solver)} & {fmt_float(median(values))} \\\\"
        for (depth, solver), values in sorted(grouped_lengths.items())
    ]
    (figures / "solution_length_depth_data.tex").write_text(
        "\\begin{tabular}{rp{0.32\\textwidth}r}\n"
        "\\hline\n"
        "Depth & Solver & Median solution length \\\\\n"
        "\\hline\n"
        + "\n".join(length_depth_rows)
        + "\n\\hline\n\\end{tabular}\n",
        encoding="utf-8",
    )

    status_count_rows = []
    for solver in solver_names:
        counts = Counter(str(row["status"]) for row in rows if row["solver"] == solver)
        for status in statuses:
            if counts[status]:
                status_count_rows.append(f"{solver_short(solver)} & {tex(status)} & {counts[status]} \\\\")
    (figures / "status_counts_data.tex").write_text(
        "\\begin{tabular}{p{0.30\\textwidth}p{0.18\\textwidth}r}\n"
        "\\hline\n"
        "Solver & Status & Count \\\\\n"
        "\\hline\n"
        + "\n".join(status_count_rows)
        + "\n\\hline\n\\end{tabular}\n",
        encoding="utf-8",
    )
