// Native Korf-style optimal 3x3 solver.
//
// This executable performs IDA* over the full cubie state. Its heuristic is the
// maximum of the complete corner PDB, any supplied complete 6-edge PDBs, and
// any explicitly supplied compatible cost-partitioned 6-edge PDB sum (an
// admissible max-combination; overlapping edge sets are NOT summed). Every
// returned solution is optimal under HTM when the search completes. The
// optimality of the default build depends ONLY on these student-built,
// BFS-verified pattern databases and the canonical move pruning below — it does
// NOT depend on any third-party heuristic.
//
// PERFORMANCE NOTE (2026 optimization pass): the per-node hot path was rewritten
// to use make/undo on a single mutable cubie state, incrementally maintained
// corner permutation/orientation coordinates via small precomputed move tables
// (40320x18 and 2187x18), branch-light Lehmer ranking for the 6-edge subset
// coordinates, and an early-exit MAX over the edge PDBs. The COMPUTED HEURISTIC
// VALUE IS UNCHANGED (still the admissible MAX of corner + complete 6-edge PDBs
// + optional additive set), so every returned `exact` solution remains optimal.
// Per-node heuristic calls that already prove f > bound short-circuit; the
// returned per-node lower bound `minimum` is always recomputed from a full,
// exact heuristic so the IDA* threshold sequence stays admissible.
//
// ---------------------------------------------------------------------------
// OPTIONAL THIRD-PARTY HEURISTIC ATTRIBUTION (GPL-3.0)
// ---------------------------------------------------------------------------
// When and ONLY when this file is compiled with -DRUBIK_WITH_NISSY_BRIDGE, it
// links the optional nissy_bridge.c shim against nissy 2.0.8
// (https://github.com/sebastianotronto/nissy), which is licensed under the
// GNU General Public License, version 3.0 (GPL-3.0). nissy is used solely as
// an *optional* extra admissible lower bound (a cross-check / acceleration);
// the default build never references it.
//
// Statically or dynamically linking the GPL-3.0 nissy code into this program
// produces a COMBINED / DERIVATIVE WORK, which means the resulting
// `optimal_solver_nissy` binary, if distributed, is itself subject to the
// terms of the GPL-3.0. The student's own optimal engine (the default
// `optimal_solver` binary, built WITHOUT this flag) carries no such obligation.
// The full third-party notice for nissy is maintained in THIRD_PARTY_NOTICES.md.
// ---------------------------------------------------------------------------

#include <array>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <tuple>
#include <unordered_map>
#include <vector>

#ifdef RUBIK_WITH_NISSY_BRIDGE
#include "nissy_bridge.h"
#endif

namespace {

constexpr std::uint32_t kCornerPermutationCount = 40320;
constexpr std::uint32_t kCornerOrientationCount = 2187;
constexpr std::uint32_t kCornerStateCount = kCornerPermutationCount * kCornerOrientationCount;
constexpr std::uint32_t kEdgePdbStateCount = 42577920;
constexpr std::uint32_t kSubsetSize = 6;
constexpr std::uint32_t kCombinationCount = 924;
constexpr std::uint32_t kPermutationCount6 = 720;
constexpr std::uint32_t kOrientationCount6 = 64;
// Optional 7-edge PDBs (WORSTCASE Path 1): C(12,7) * 7! * 2^7 = 510,935,040.
constexpr std::uint32_t kSubsetSize7 = 7;
constexpr std::uint32_t kEdgePdbStateCount7 = 510935040;
constexpr std::uint32_t kCombinationCount7 = 792;
constexpr std::uint32_t kPermutationCount7 = 5040;
constexpr std::uint32_t kOrientationCount7 = 128;
constexpr std::uint8_t kUnvisited = 0xff;
constexpr int kFound = -1;
constexpr int kTimeout = -2;
constexpr int kNodeLimit = -3;
constexpr int kStopped = -4;

enum class ChildOrder {
    HeuristicDescending,
    HeuristicAscending,
    MoveIndex,
};

enum class UpperBoundProofStrategy {
    Iterative,
    SingleBound,
};

constexpr std::array<const char*, 18> kMoveNames = {
    "U", "U'", "U2", "R", "R'", "R2", "F", "F'", "F2",
    "D", "D'", "D2", "L", "L'", "L2", "B", "B'", "B2",
};

struct State {
    std::array<std::uint8_t, 8> cp;
    std::array<std::uint8_t, 8> co;
    std::array<std::uint8_t, 12> ep;
    std::array<std::uint8_t, 12> eo;
#ifdef RUBIK_WITH_NISSY_BRIDGE
    NissyBridgeCube nissy{};
    bool has_nissy = false;
#endif
};

struct BaseMove {
    std::array<std::uint8_t, 8> cp;
    std::array<std::uint8_t, 8> co;
    std::array<std::uint8_t, 12> ep;
    std::array<std::uint8_t, 12> eo;
};

constexpr std::array<BaseMove, 6> kBaseMoves = {{
    {{{3, 0, 1, 2, 4, 5, 6, 7}}, {{0, 0, 0, 0, 0, 0, 0, 0}}, {{3, 0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11}}, {{0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}}}, // U
    {{{4, 1, 2, 0, 7, 5, 6, 3}}, {{2, 0, 0, 1, 1, 0, 0, 2}}, {{8, 1, 2, 3, 11, 5, 6, 7, 4, 9, 10, 0}}, {{0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}}}, // R
    {{{1, 5, 2, 3, 0, 4, 6, 7}}, {{1, 2, 0, 0, 2, 1, 0, 0}}, {{0, 9, 2, 3, 4, 8, 6, 7, 1, 5, 10, 11}}, {{0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 0}}}, // F
    {{{0, 1, 2, 3, 5, 6, 7, 4}}, {{0, 0, 0, 0, 0, 0, 0, 0}}, {{0, 1, 2, 3, 5, 6, 7, 4, 8, 9, 10, 11}}, {{0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}}}, // D
    {{{0, 2, 6, 3, 4, 1, 5, 7}}, {{0, 1, 2, 0, 0, 2, 1, 0}}, {{0, 1, 10, 3, 4, 5, 9, 7, 8, 2, 6, 11}}, {{0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}}}, // L
    {{{0, 1, 3, 7, 4, 5, 2, 6}}, {{0, 0, 1, 2, 0, 0, 2, 1}}, {{0, 1, 2, 11, 4, 5, 6, 10, 8, 9, 3, 7}}, {{0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1}}}, // B
}};

#pragma pack(push, 1)
struct CornerHeader {
    char magic[8];
    std::uint32_t version;
    std::uint32_t state_count;
    std::uint32_t corner_permutation_count;
    std::uint32_t corner_orientation_count;
    std::uint32_t max_distance;
    std::uint32_t complete;
    std::uint32_t depth_limit;
    std::uint32_t header_bytes;
    std::uint64_t expanded_nodes;
    std::uint64_t generated_nodes;
};

struct EdgeHeader {
    char magic[8];
    std::uint32_t version;
    std::uint32_t subset_size;
    std::uint32_t state_count;
    std::uint32_t combination_count;
    std::uint32_t permutation_count;
    std::uint32_t orientation_count;
    std::uint8_t subset_edges[6];
    std::uint8_t reserved[2];
    std::uint32_t max_distance;
    std::uint32_t complete;
    std::uint32_t depth_limit;
    std::uint32_t header_bytes;
    std::uint64_t expanded_nodes;
    std::uint64_t generated_nodes;
};
#pragma pack(pop)

struct EdgePdb {
    EdgeHeader header;
    std::uint32_t subset_size;  // 6 or 7; selects the coordinate ranking path
    std::array<int, 12> edge_to_subset;
    std::vector<std::uint8_t> distances;
};

const char* child_order_name(ChildOrder order) {
    switch (order) {
        case ChildOrder::HeuristicDescending:
            return "heuristic-desc";
        case ChildOrder::HeuristicAscending:
            return "heuristic-asc";
        case ChildOrder::MoveIndex:
            return "move";
    }
    return "heuristic-desc";
}

const char* upper_bound_proof_strategy_name(UpperBoundProofStrategy strategy) {
    switch (strategy) {
        case UpperBoundProofStrategy::Iterative:
            return "iterative";
        case UpperBoundProofStrategy::SingleBound:
            return "single-bound";
    }
    return "single-bound";
}

ChildOrder parse_child_order(const std::string& value) {
    if (value == "heuristic-desc") {
        return ChildOrder::HeuristicDescending;
    }
    if (value == "heuristic-asc") {
        return ChildOrder::HeuristicAscending;
    }
    if (value == "move") {
        return ChildOrder::MoveIndex;
    }
    throw std::runtime_error("--child-order must be one of: heuristic-desc, heuristic-asc, move");
}

UpperBoundProofStrategy parse_upper_bound_proof_strategy(const std::string& value) {
    if (value == "iterative") {
        return UpperBoundProofStrategy::Iterative;
    }
    if (value == "single-bound") {
        return UpperBoundProofStrategy::SingleBound;
    }
    throw std::runtime_error("--upper-bound-proof-strategy must be one of: iterative, single-bound");
}

struct SearchTask {
    State state;
    std::vector<int> path;
    int last_face;
    int depth;
    int heuristic;
};

struct SplitBuildResult {
    bool found = false;
    bool timed_out = false;
    bool node_limited = false;
    std::vector<int> solution;
    int minimum = std::numeric_limits<int>::max();
};

struct TranspositionKey {
    std::array<std::uint8_t, 8> cp;
    std::array<std::uint8_t, 8> co;
    std::array<std::uint8_t, 12> ep;
    std::array<std::uint8_t, 12> eo;
    std::int8_t last_face;

    bool operator==(const TranspositionKey& other) const {
        return last_face == other.last_face && cp == other.cp && co == other.co && ep == other.ep && eo == other.eo;
    }
};

struct TranspositionKeyHash {
    std::size_t operator()(const TranspositionKey& key) const {
        std::uint64_t hash = 1469598103934665603ULL;
        auto mix = [&hash](std::uint8_t value) {
            hash ^= value;
            hash *= 1099511628211ULL;
        };
        for (const auto value : key.cp) {
            mix(value);
        }
        for (const auto value : key.co) {
            mix(value);
        }
        for (const auto value : key.ep) {
            mix(value);
        }
        for (const auto value : key.eo) {
            mix(value);
        }
        mix(static_cast<std::uint8_t>(key.last_face + 1));
        return static_cast<std::size_t>(hash);
    }
};

struct PackedTranspositionKey {
    std::uint64_t lo = 0;
    std::uint32_t hi = 0;

    bool operator==(const PackedTranspositionKey& other) const {
        return lo == other.lo && hi == other.hi;
    }
};

struct CompactTranspositionEntry {
    std::uint64_t lo = 0;
    std::uint32_t hi = 0;
    std::uint8_t depth = 0;
    bool occupied = false;
};

struct CompactTranspositionTable {
    std::vector<CompactTranspositionEntry> entries;
    std::uint64_t entry_limit = 0;
    std::uint64_t used = 0;
};

struct Options {
    std::string corner_pdb_path;
    std::vector<std::string> edge_pdb_paths;
    std::vector<std::string> additive_edge_pdb_paths;
    State state;
    int max_depth = 20;
    double timeout_seconds = 300.0;
    std::uint64_t node_limit = 0;
    std::uint64_t tt_entries = 0;
    int threads = 1;
    int split_depth = 1;
    bool dual_heuristic = false;
    bool nissy_heuristic = false;
    bool nissy_axis_transforms = false;
    bool emit_edge_coords = false;  // debug: print per-PDB coords/distances and exit
    UpperBoundProofStrategy upper_bound_proof_strategy = UpperBoundProofStrategy::SingleBound;
    ChildOrder child_order = ChildOrder::HeuristicDescending;
    std::string nissy_data_dir;
    std::string nissy_sequence;
    std::vector<int> upper_solution;
    std::array<bool, 18> root_move_allowed{};
    bool root_move_mask_enabled = false;
    bool symmetry_transpositions = false;
    bool full_symmetry_transpositions = false;
    bool compact_transpositions = false;
};

// ---------------------------------------------------------------------------
// Coordinate move tables (built once at startup, shared read-only).
//
// Corner permutation/orientation transitions are pure functions of the
// permutation (resp. orientation) coordinate alone, so a 40320x18 / 2187x18
// table fully describes them. Maintaining these coordinates incrementally with
// make/undo removes the per-node combinatorial ranking from the hot path.
// ---------------------------------------------------------------------------
struct CoordTables {
    // corner_perm_move[rank][move] -> new permutation rank (0..40319)
    std::vector<std::uint16_t> corner_perm_move;
    // corner_ori_move[coord][move] -> new orientation coord (0..2186)
    std::vector<std::uint16_t> corner_ori_move;
};

struct Solver {
    std::vector<std::uint8_t> corner_distances;
    CornerHeader corner_header{};
    std::vector<EdgePdb> edge_pdbs;
    std::vector<EdgePdb> additive_edge_pdbs;
    std::array<BaseMove, 18> moves{};
    std::vector<int> path;
    std::vector<int> solution;
    std::uint64_t expanded = 0;
    std::uint64_t generated = 0;
    int lower_bound = 0;
    bool timed_out = false;
    bool node_limited = false;
    std::chrono::steady_clock::time_point deadline;
    std::uint64_t node_limit = 0;
    std::uint64_t tt_entry_limit = 0;
    std::uint64_t tt_hits = 0;
    std::uint64_t tt_inserts = 0;
    std::uint64_t tt_updates = 0;
    std::uint64_t tt_capacity_skips = 0;
    std::uint64_t tt_current_entries = 0;
    std::uint64_t split_tasks = 0;
    bool dual_heuristic = false;
    bool nissy_heuristic = false;
    bool nissy_axis_transforms = false;
    ChildOrder child_order = ChildOrder::HeuristicDescending;
    bool upper_solution_verified = false;
    bool exact_certified_by_upper_bound = false;
    bool upper_bound_proof_active = false;
    bool upper_bound_proof_exhaustive = false;
    bool upper_bound_shorter_solution_found = false;
    std::array<bool, 18> root_move_allowed{};
    bool root_move_mask_enabled = false;
    bool symmetry_transpositions = false;
    bool full_symmetry_transpositions = false;
    bool compact_transpositions = false;
    UpperBoundProofStrategy upper_bound_proof_strategy = UpperBoundProofStrategy::SingleBound;
    int upper_bound_solution_length = 0;
    int upper_bound_proof_search_bound = -1;
    std::unordered_map<TranspositionKey, std::uint8_t, TranspositionKeyHash> transpositions;
    CompactTranspositionTable compact_transpositions_table;
    const CoordTables* coords = nullptr;
};

struct WorkerContext {
    std::vector<int> path;
    std::vector<int> solution;
    std::uint64_t expanded = 0;
    std::uint64_t generated = 0;
    bool timed_out = false;
    bool node_limited = false;
    std::chrono::steady_clock::time_point deadline;
    std::uint64_t node_limit = 0;
    std::uint64_t tt_entry_limit = 0;
    std::uint64_t tt_hits = 0;
    std::uint64_t tt_inserts = 0;
    std::uint64_t tt_updates = 0;
    std::uint64_t tt_capacity_skips = 0;
    bool symmetry_transpositions = false;
    bool full_symmetry_transpositions = false;
    bool compact_transpositions = false;
    std::unordered_map<TranspositionKey, std::uint8_t, TranspositionKeyHash> transpositions;
    CompactTranspositionTable compact_transpositions_table;
    std::atomic<bool>* stop_requested = nullptr;
};

constexpr std::array<std::uint32_t, 13> factorials12() {
    std::array<std::uint32_t, 13> values{};
    values[0] = 1;
    for (std::uint32_t i = 1; i < values.size(); ++i) {
        values[i] = values[i - 1] * i;
    }
    return values;
}

constexpr auto kFactorial12 = factorials12();

std::array<std::array<std::uint32_t, kSubsetSize + 1>, 13> build_combinations() {
    std::array<std::array<std::uint32_t, kSubsetSize + 1>, 13> values{};
    for (std::uint32_t n = 0; n <= 12; ++n) {
        values[n][0] = 1;
        for (std::uint32_t k = 1; k <= kSubsetSize; ++k) {
            if (k > n) {
                values[n][k] = 0;
            } else if (k == n) {
                values[n][k] = 1;
            } else {
                values[n][k] = values[n - 1][k - 1] + values[n - 1][k];
            }
        }
    }
    return values;
}

const auto kChoose = build_combinations();

inline int popcount32(std::uint32_t value) {
    return __builtin_popcount(value);
}

State solved_state() {
    return {{{0, 1, 2, 3, 4, 5, 6, 7}}, {{0, 0, 0, 0, 0, 0, 0, 0}},
            {{0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11}}, {{0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}}};
}

State apply_base(const State& state, const BaseMove& move) {
    State out;
    for (std::uint32_t i = 0; i < 8; ++i) {
        out.cp[i] = state.cp[move.cp[i]];
        out.co[i] = static_cast<std::uint8_t>((state.co[move.cp[i]] + move.co[i]) % 3);
    }
    for (std::uint32_t i = 0; i < 12; ++i) {
        out.ep[i] = state.ep[move.ep[i]];
        out.eo[i] = static_cast<std::uint8_t>((state.eo[move.ep[i]] + move.eo[i]) & 1U);
    }
    return out;
}

State apply_move(const State& state, const BaseMove& move, int move_index) {
    State out = apply_base(state, move);
#ifdef RUBIK_WITH_NISSY_BRIDGE
    if (state.has_nissy) {
        out.nissy = nissy_bridge_apply_move(state.nissy, move_index);
        out.has_nissy = true;
    }
#else
    (void)move_index;
#endif
    return out;
}

std::array<BaseMove, 18> build_moves() {
    std::array<BaseMove, 18> result{};
    for (std::uint32_t face = 0; face < 6; ++face) {
        State state = solved_state();
        for (std::uint32_t turns = 1; turns <= 3; ++turns) {
            state = apply_base(state, kBaseMoves[face]);
            const std::uint32_t slot = turns == 1 ? 0 : turns == 3 ? 1 : 2;
            result[face * 3 + slot] = {state.cp, state.co, state.ep, state.eo};
        }
    }
    return result;
}

bool is_solved(const State& state) {
    for (std::uint32_t i = 0; i < 8; ++i) {
        if (state.cp[i] != i || state.co[i] != 0) {
            return false;
        }
    }
    for (std::uint32_t i = 0; i < 12; ++i) {
        if (state.ep[i] != i || state.eo[i] != 0) {
            return false;
        }
    }
    return true;
}

struct RotationTransform {
    std::array<std::uint8_t, 8> corner_pos{};
    std::array<std::uint8_t, 8> corner_cubie{};
    std::array<std::uint8_t, 8 * 8 * 3> corner_ori{};
    std::array<std::uint8_t, 12> edge_pos{};
    std::array<std::uint8_t, 12> edge_cubie{};
    std::array<std::uint8_t, 12 * 12 * 2> edge_ori{};
    std::array<std::uint8_t, 6> face_map{};
};

using Vec3 = std::array<int, 3>;
using Matrix3 = std::array<Vec3, 3>;

constexpr std::array<Vec3, 6> kFaceNormals = {{
    {{0, 1, 0}},   // U
    {{1, 0, 0}},   // R
    {{0, 0, 1}},   // F
    {{0, -1, 0}},  // D
    {{-1, 0, 0}},  // L
    {{0, 0, -1}},  // B
}};

constexpr std::array<std::array<int, 3>, 8> kCornerFacelets = {{
    {{8, 9, 20}}, {{6, 18, 38}}, {{0, 36, 47}}, {{2, 45, 11}},
    {{29, 26, 15}}, {{27, 44, 24}}, {{33, 53, 42}}, {{35, 17, 51}},
}};

constexpr std::array<std::array<int, 2>, 12> kEdgeFacelets = {{
    {{5, 10}}, {{7, 19}}, {{3, 37}}, {{1, 46}}, {{32, 16}}, {{28, 25}},
    {{30, 43}}, {{34, 52}}, {{23, 12}}, {{21, 41}}, {{50, 39}}, {{48, 14}},
}};

constexpr std::array<std::array<int, 3>, 8> kCornerColors = {{
    {{0, 1, 2}}, {{0, 2, 4}}, {{0, 4, 5}}, {{0, 5, 1}},
    {{3, 2, 1}}, {{3, 4, 2}}, {{3, 5, 4}}, {{3, 1, 5}},
}};

constexpr std::array<std::array<int, 2>, 12> kEdgeColors = {{
    {{0, 1}}, {{0, 2}}, {{0, 4}}, {{0, 5}}, {{3, 1}}, {{3, 2}},
    {{3, 4}}, {{3, 5}}, {{2, 1}}, {{2, 4}}, {{5, 4}}, {{5, 1}},
}};

Vec3 apply_matrix(const Matrix3& matrix, const Vec3& vector) {
    return {{
        matrix[0][0] * vector[0] + matrix[0][1] * vector[1] + matrix[0][2] * vector[2],
        matrix[1][0] * vector[0] + matrix[1][1] * vector[1] + matrix[1][2] * vector[2],
        matrix[2][0] * vector[0] + matrix[2][1] * vector[1] + matrix[2][2] * vector[2],
    }};
}

int determinant(const Matrix3& matrix) {
    return (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    );
}

std::vector<Matrix3> build_symmetry_matrices(bool proper_only) {
    std::vector<Matrix3> matrices;
    const std::array<std::array<int, 3>, 6> perms = {{
        {{0, 1, 2}}, {{0, 2, 1}}, {{1, 0, 2}}, {{1, 2, 0}}, {{2, 0, 1}}, {{2, 1, 0}},
    }};
    for (const auto& perm : perms) {
        for (int sx : {-1, 1}) {
            for (int sy : {-1, 1}) {
                for (int sz : {-1, 1}) {
                    const std::array<int, 3> signs = {{sx, sy, sz}};
                    Matrix3 matrix = {{{{0, 0, 0}}, {{0, 0, 0}}, {{0, 0, 0}}}};
                    for (int row = 0; row < 3; ++row) {
                        matrix[row][perm[row]] = signs[row];
                    }
                    if (!proper_only || determinant(matrix) == 1) {
                        matrices.push_back(matrix);
                    }
                }
            }
        }
    }
    const Matrix3 identity = {{{{1, 0, 0}}, {{0, 1, 0}}, {{0, 0, 1}}}};
    std::sort(matrices.begin(), matrices.end(), [&identity](const Matrix3& a, const Matrix3& b) {
        const bool a_identity = a == identity;
        const bool b_identity = b == identity;
        if (a_identity != b_identity) {
            return a_identity;
        }
        return a < b;
    });
    const std::size_t expected = proper_only ? 24 : 48;
    if (matrices.size() != expected || matrices.front() != identity) {
        throw std::runtime_error("native symmetry table has the wrong size or identity order");
    }
    return matrices;
}

std::vector<Matrix3> build_rotation_matrices() {
    return build_symmetry_matrices(true);
}

std::vector<Matrix3> build_full_symmetry_matrices() {
    return build_symmetry_matrices(false);
}

int face_from_normal(const Vec3& normal) {
    for (int face = 0; face < 6; ++face) {
        if (kFaceNormals[face] == normal) {
            return face;
        }
    }
    throw std::runtime_error("invalid transformed face normal");
}

void add_facelet_grid(
    std::array<Vec3, 54>& positions,
    std::array<Vec3, 54>& normals,
    int start,
    const Vec3& normal,
    const std::array<int, 3>& rows,
    const std::array<int, 3>& cols,
    int constant_axis,
    int row_axis,
    int col_axis,
    int constant_value
) {
    for (int row = 0; row < 3; ++row) {
        for (int col = 0; col < 3; ++col) {
            Vec3 position = {{0, 0, 0}};
            position[constant_axis] = constant_value;
            position[row_axis] = rows[row];
            position[col_axis] = cols[col];
            const int index = start + row * 3 + col;
            positions[index] = position;
            normals[index] = normal;
        }
    }
}

void build_facelet_geometry(std::array<Vec3, 54>& positions, std::array<Vec3, 54>& normals) {
    add_facelet_grid(positions, normals, 0, kFaceNormals[0], {{-1, 0, 1}}, {{-1, 0, 1}}, 1, 2, 0, 1);
    add_facelet_grid(positions, normals, 9, kFaceNormals[1], {{1, 0, -1}}, {{1, 0, -1}}, 0, 1, 2, 1);
    add_facelet_grid(positions, normals, 18, kFaceNormals[2], {{1, 0, -1}}, {{-1, 0, 1}}, 2, 1, 0, 1);
    add_facelet_grid(positions, normals, 27, kFaceNormals[3], {{1, 0, -1}}, {{-1, 0, 1}}, 1, 2, 0, -1);
    add_facelet_grid(positions, normals, 36, kFaceNormals[4], {{1, 0, -1}}, {{-1, 0, 1}}, 0, 1, 2, -1);
    add_facelet_grid(positions, normals, 45, kFaceNormals[5], {{1, 0, -1}}, {{1, 0, -1}}, 2, 1, 0, -1);
}

int find_facelet_index(
    const std::array<Vec3, 54>& positions,
    const std::array<Vec3, 54>& normals,
    const Vec3& position,
    const Vec3& normal
) {
    for (int index = 0; index < 54; ++index) {
        if (positions[index] == position && normals[index] == normal) {
            return index;
        }
    }
    throw std::runtime_error("could not locate transformed facelet");
}

std::array<int, 54> build_position_to_corner() {
    std::array<int, 54> values{};
    values.fill(-1);
    for (int pos = 0; pos < 8; ++pos) {
        for (int slot = 0; slot < 3; ++slot) {
            values[kCornerFacelets[pos][slot]] = pos;
        }
    }
    return values;
}

std::array<int, 54> build_position_to_edge() {
    std::array<int, 54> values{};
    values.fill(-1);
    for (int pos = 0; pos < 12; ++pos) {
        for (int slot = 0; slot < 2; ++slot) {
            values[kEdgeFacelets[pos][slot]] = pos;
        }
    }
    return values;
}

std::tuple<int, int, int> decode_corner_stickers(
    const std::array<int, 3>& sticker_indices,
    const std::array<int, 3>& sticker_colors,
    const std::array<int, 54>& position_to_corner
) {
    const int pos = position_to_corner[sticker_indices[0]];
    if (pos < 0 || position_to_corner[sticker_indices[1]] != pos || position_to_corner[sticker_indices[2]] != pos) {
        throw std::runtime_error("rotated corner stickers do not land in one corner position");
    }
    std::array<int, 3> colors_at_pos = {{-1, -1, -1}};
    for (int i = 0; i < 3; ++i) {
        bool placed = false;
        for (int slot = 0; slot < 3; ++slot) {
            if (kCornerFacelets[pos][slot] == sticker_indices[i]) {
                colors_at_pos[slot] = sticker_colors[i];
                placed = true;
                break;
            }
        }
        if (!placed) {
            throw std::runtime_error("rotated corner sticker index is not in decoded corner position");
        }
    }
    int ori = -1;
    for (int slot = 0; slot < 3; ++slot) {
        if (colors_at_pos[slot] == 0 || colors_at_pos[slot] == 3) {
            ori = slot;
            break;
        }
    }
    if (ori < 0) {
        throw std::runtime_error("rotated corner has no U/D color");
    }
    const int col1 = colors_at_pos[(ori + 1) % 3];
    const int col2 = colors_at_pos[(ori + 2) % 3];
    for (int cubie = 0; cubie < 8; ++cubie) {
        if (kCornerColors[cubie][1] == col1 && kCornerColors[cubie][2] == col2) {
            return {pos, cubie, ori % 3};
        }
    }
    throw std::runtime_error("rotated corner colors do not identify a legal cubie");
}

std::tuple<int, int, int> decode_edge_stickers(
    const std::array<int, 2>& sticker_indices,
    const std::array<int, 2>& sticker_colors,
    const std::array<int, 54>& position_to_edge
) {
    const int pos = position_to_edge[sticker_indices[0]];
    if (pos < 0 || position_to_edge[sticker_indices[1]] != pos) {
        throw std::runtime_error("rotated edge stickers do not land in one edge position");
    }
    std::array<int, 2> colors_at_pos = {{-1, -1}};
    for (int i = 0; i < 2; ++i) {
        bool placed = false;
        for (int slot = 0; slot < 2; ++slot) {
            if (kEdgeFacelets[pos][slot] == sticker_indices[i]) {
                colors_at_pos[slot] = sticker_colors[i];
                placed = true;
                break;
            }
        }
        if (!placed) {
            throw std::runtime_error("rotated edge sticker index is not in decoded edge position");
        }
    }
    for (int cubie = 0; cubie < 12; ++cubie) {
        if (kEdgeColors[cubie][0] == colors_at_pos[0] && kEdgeColors[cubie][1] == colors_at_pos[1]) {
            return {pos, cubie, 0};
        }
        if (kEdgeColors[cubie][1] == colors_at_pos[0] && kEdgeColors[cubie][0] == colors_at_pos[1]) {
            return {pos, cubie, 1};
        }
    }
    throw std::runtime_error("rotated edge colors do not identify a legal cubie");
}

std::vector<RotationTransform> build_transforms(const std::vector<Matrix3>& matrices) {
    std::array<Vec3, 54> facelet_positions{};
    std::array<Vec3, 54> facelet_normals{};
    build_facelet_geometry(facelet_positions, facelet_normals);
    const auto position_to_corner = build_position_to_corner();
    const auto position_to_edge = build_position_to_edge();
    std::vector<RotationTransform> rotations(matrices.size());

    for (std::size_t rot_index = 0; rot_index < matrices.size(); ++rot_index) {
        const auto& matrix = matrices[rot_index];
        std::array<int, 54> index_map{};
        for (int old_index = 0; old_index < 54; ++old_index) {
            index_map[old_index] = find_facelet_index(
                facelet_positions,
                facelet_normals,
                apply_matrix(matrix, facelet_positions[old_index]),
                apply_matrix(matrix, facelet_normals[old_index])
            );
        }
        RotationTransform transform;
        for (int face = 0; face < 6; ++face) {
            transform.face_map[face] = static_cast<std::uint8_t>(face_from_normal(apply_matrix(matrix, kFaceNormals[face])));
        }
        for (int pos = 0; pos < 8; ++pos) {
            for (int cubie = 0; cubie < 8; ++cubie) {
                for (int ori = 0; ori < 3; ++ori) {
                    std::array<int, 3> sticker_indices{};
                    std::array<int, 3> sticker_colors{};
                    for (int slot = 0; slot < 3; ++slot) {
                        sticker_indices[slot] = index_map[kCornerFacelets[pos][(slot + ori) % 3]];
                        sticker_colors[slot] = transform.face_map[kCornerColors[cubie][slot]];
                    }
                    auto [new_pos, new_cubie, new_ori] = decode_corner_stickers(
                        sticker_indices,
                        sticker_colors,
                        position_to_corner
                    );
                    if (cubie == 0 && ori == 0) {
                        transform.corner_pos[pos] = static_cast<std::uint8_t>(new_pos);
                    }
                    if (pos == 0 && ori == 0) {
                        transform.corner_cubie[cubie] = static_cast<std::uint8_t>(new_cubie);
                    }
                    transform.corner_ori[(pos * 8 + cubie) * 3 + ori] = static_cast<std::uint8_t>(new_ori);
                }
            }
        }
        for (int pos = 0; pos < 12; ++pos) {
            for (int cubie = 0; cubie < 12; ++cubie) {
                for (int ori = 0; ori < 2; ++ori) {
                    std::array<int, 2> sticker_indices{};
                    std::array<int, 2> sticker_colors{};
                    for (int slot = 0; slot < 2; ++slot) {
                        sticker_indices[slot] = index_map[kEdgeFacelets[pos][(slot + ori) % 2]];
                        sticker_colors[slot] = transform.face_map[kEdgeColors[cubie][slot]];
                    }
                    auto [new_pos, new_cubie, new_ori] = decode_edge_stickers(
                        sticker_indices,
                        sticker_colors,
                        position_to_edge
                    );
                    if (cubie == 0 && ori == 0) {
                        transform.edge_pos[pos] = static_cast<std::uint8_t>(new_pos);
                    }
                    if (pos == 0 && ori == 0) {
                        transform.edge_cubie[cubie] = static_cast<std::uint8_t>(new_cubie);
                    }
                    transform.edge_ori[(pos * 12 + cubie) * 2 + ori] = static_cast<std::uint8_t>(new_ori);
                }
            }
        }
        rotations[rot_index] = transform;
    }
    return rotations;
}

const std::vector<RotationTransform>& rotation_transforms() {
    static const auto transforms = build_transforms(build_rotation_matrices());
    return transforms;
}

const std::vector<RotationTransform>& full_symmetry_transforms() {
    static const auto transforms = build_transforms(build_full_symmetry_matrices());
    return transforms;
}

State rotate_state(const State& state, const RotationTransform& transform) {
    State out = solved_state();
    for (int pos = 0; pos < 8; ++pos) {
        const int new_pos = transform.corner_pos[pos];
        const int cubie = state.cp[pos];
        const int ori = state.co[pos];
        out.cp[new_pos] = transform.corner_cubie[cubie];
        out.co[new_pos] = transform.corner_ori[(pos * 8 + cubie) * 3 + ori];
    }
    for (int pos = 0; pos < 12; ++pos) {
        const int new_pos = transform.edge_pos[pos];
        const int cubie = state.ep[pos];
        const int ori = state.eo[pos];
        out.ep[new_pos] = transform.edge_cubie[cubie];
        out.eo[new_pos] = transform.edge_ori[(pos * 12 + cubie) * 2 + ori];
    }
    return out;
}

bool transposition_key_less(const TranspositionKey& a, const TranspositionKey& b) {
    if (a.last_face != b.last_face) {
        return a.last_face < b.last_face;
    }
    if (a.cp != b.cp) {
        return a.cp < b.cp;
    }
    if (a.co != b.co) {
        return a.co < b.co;
    }
    if (a.ep != b.ep) {
        return a.ep < b.ep;
    }
    return a.eo < b.eo;
}

TranspositionKey exact_transposition_key(const State& state, int last_face) {
    return TranspositionKey{state.cp, state.co, state.ep, state.eo, static_cast<std::int8_t>(last_face)};
}

TranspositionKey canonical_symmetry_transposition_key(
    const State& state,
    int last_face,
    const std::vector<RotationTransform>& transforms
) {
    TranspositionKey best = exact_transposition_key(state, last_face);
    for (std::size_t index = 1; index < transforms.size(); ++index) {
        const auto& transform = transforms[index];
        const State rotated = rotate_state(state, transform);
        const int rotated_last_face = last_face < 0 ? -1 : static_cast<int>(transform.face_map[last_face]);
        const TranspositionKey candidate = exact_transposition_key(rotated, rotated_last_face);
        if (transposition_key_less(candidate, best)) {
            best = candidate;
        }
    }
    return best;
}

TranspositionKey make_transposition_key(
    bool symmetry_transpositions,
    bool full_symmetry_transpositions,
    const State& state,
    int last_face
) {
    if (!symmetry_transpositions) {
        return exact_transposition_key(state, last_face);
    }
    return canonical_symmetry_transposition_key(
        state,
        last_face,
        full_symmetry_transpositions ? full_symmetry_transforms() : rotation_transforms()
    );
}

std::uint32_t rank_permutation8(const std::array<std::uint8_t, 8>& values) {
    std::uint32_t rank = 0;
    std::uint32_t used_mask = 0;
    for (std::uint32_t index = 0; index < 8; ++index) {
        const std::uint32_t value = values[index];
        const std::uint32_t lower_mask = value == 0 ? 0 : ((1U << value) - 1U);
        const std::uint32_t digit = value - static_cast<std::uint32_t>(popcount32(used_mask & lower_mask));
        rank += digit * kFactorial12[7 - index];
        used_mask |= 1U << value;
    }
    return rank;
}

std::uint32_t rank_permutation12(const std::array<std::uint8_t, 12>& values) {
    std::uint32_t rank = 0;
    std::uint32_t used_mask = 0;
    for (std::uint32_t index = 0; index < 12; ++index) {
        const std::uint32_t value = values[index];
        const std::uint32_t lower_mask = value == 0 ? 0 : ((1U << value) - 1U);
        const std::uint32_t digit = value - static_cast<std::uint32_t>(popcount32(used_mask & lower_mask));
        rank += digit * kFactorial12[11 - index];
        used_mask |= 1U << value;
    }
    return rank;
}

void unrank_permutation8(std::uint32_t rank, std::array<std::uint8_t, 8>& values) {
    std::array<std::uint8_t, 8> elements = {0, 1, 2, 3, 4, 5, 6, 7};
    int remaining = 8;
    for (std::uint32_t index = 0; index < 8; ++index) {
        const std::uint32_t fact = kFactorial12[7 - index];
        std::uint32_t digit = rank / fact;
        rank %= fact;
        values[index] = elements[digit];
        for (int j = static_cast<int>(digit); j + 1 < remaining; ++j) {
            elements[j] = elements[j + 1];
        }
        --remaining;
    }
}

std::uint32_t rank_orientation3(const std::array<std::uint8_t, 8>& values) {
    std::uint32_t coord = 0;
    for (std::uint32_t index = 0; index < 7; ++index) {
        coord = coord * 3 + values[index];
    }
    return coord;
}

std::uint32_t rank_orientation2_all12(const std::array<std::uint8_t, 12>& values) {
    std::uint32_t coord = 0;
    for (std::uint32_t index = 0; index < 12; ++index) {
        coord |= static_cast<std::uint32_t>(values[index] & 1U) << index;
    }
    return coord;
}

void unrank_orientation3(std::uint32_t coord, std::array<std::uint8_t, 8>& values) {
    std::uint32_t sum = 0;
    for (int index = 6; index >= 0; --index) {
        values[index] = static_cast<std::uint8_t>(coord % 3);
        sum += values[index];
        coord /= 3;
    }
    values[7] = static_cast<std::uint8_t>((3 - (sum % 3)) % 3);
}

std::uint32_t corner_coord(const State& state) {
    return rank_permutation8(state.cp) * kCornerOrientationCount + rank_orientation3(state.co);
}

PackedTranspositionKey exact_packed_transposition_key(const State& state, int last_face) {
    const std::uint64_t edge_perm = rank_permutation12(state.ep);  // < 2^29
    const std::uint64_t edge_ori = rank_orientation2_all12(state.eo);  // 12 bits
    const std::uint64_t last_code = static_cast<std::uint64_t>(last_face + 1);  // 0..6
    return PackedTranspositionKey{
        edge_perm | (edge_ori << 29) | (last_code << 41),
        corner_coord(state),
    };
}

bool packed_transposition_key_less(const PackedTranspositionKey& a, const PackedTranspositionKey& b) {
    if (a.hi != b.hi) {
        return a.hi < b.hi;
    }
    return a.lo < b.lo;
}

PackedTranspositionKey canonical_packed_symmetry_transposition_key(
    const State& state,
    int last_face,
    const std::vector<RotationTransform>& transforms
) {
    PackedTranspositionKey best = exact_packed_transposition_key(state, last_face);
    for (std::size_t index = 1; index < transforms.size(); ++index) {
        const auto& transform = transforms[index];
        const State rotated = rotate_state(state, transform);
        const int rotated_last_face = last_face < 0 ? -1 : static_cast<int>(transform.face_map[last_face]);
        const PackedTranspositionKey candidate = exact_packed_transposition_key(rotated, rotated_last_face);
        if (packed_transposition_key_less(candidate, best)) {
            best = candidate;
        }
    }
    return best;
}

PackedTranspositionKey make_packed_transposition_key(
    bool symmetry_transpositions,
    bool full_symmetry_transpositions,
    const State& state,
    int last_face
) {
    if (!symmetry_transpositions) {
        return exact_packed_transposition_key(state, last_face);
    }
    return canonical_packed_symmetry_transposition_key(
        state,
        last_face,
        full_symmetry_transpositions ? full_symmetry_transforms() : rotation_transforms()
    );
}

std::uint64_t next_power_of_two(std::uint64_t value) {
    std::uint64_t power = 1;
    while (power < value) {
        power <<= 1;
    }
    return power;
}

void reset_compact_transposition_table(CompactTranspositionTable& table, std::uint64_t entry_limit) {
    table.entry_limit = entry_limit;
    table.used = 0;
    table.entries.clear();
    if (entry_limit == 0) {
        return;
    }
    // Keep load factor <= 0.5. The table is exact open addressing, not a Bloom
    // filter: every occupied slot stores the complete packed state key.
    table.entries.resize(static_cast<std::size_t>(next_power_of_two(entry_limit * 2)));
}

std::uint64_t packed_key_hash(const PackedTranspositionKey& key) {
    std::uint64_t x = key.lo ^ (static_cast<std::uint64_t>(key.hi) * 0x9e3779b97f4a7c15ULL);
    x ^= x >> 30;
    x *= 0xbf58476d1ce4e5b9ULL;
    x ^= x >> 27;
    x *= 0x94d049bb133111ebULL;
    x ^= x >> 31;
    return x;
}

bool compact_transposition_should_prune(
    CompactTranspositionTable& table,
    const PackedTranspositionKey& key,
    int g,
    std::uint64_t& hits,
    std::uint64_t& inserts,
    std::uint64_t& updates,
    std::uint64_t& capacity_skips
) {
    if (table.entry_limit == 0 || table.entries.empty()) {
        return false;
    }
    const std::size_t mask = table.entries.size() - 1;
    std::size_t index = static_cast<std::size_t>(packed_key_hash(key)) & mask;
    const std::uint8_t depth = static_cast<std::uint8_t>(g);
    while (true) {
        CompactTranspositionEntry& entry = table.entries[index];
        if (!entry.occupied) {
            if (table.used < table.entry_limit) {
                entry.lo = key.lo;
                entry.hi = key.hi;
                entry.depth = depth;
                entry.occupied = true;
                ++table.used;
                ++inserts;
            } else {
                ++capacity_skips;
            }
            return false;
        }
        if (entry.lo == key.lo && entry.hi == key.hi) {
            if (entry.depth <= depth) {
                ++hits;
                return true;
            }
            entry.depth = depth;
            ++updates;
            return false;
        }
        index = (index + 1) & mask;
    }
}

// Build the corner permutation/orientation move tables. The orientation table
// uses the 8-vector orientation (with the dependent 8th corner) so the result
// matches rank_orientation3 exactly.
CoordTables build_coord_tables(const std::array<BaseMove, 18>& moves) {
    CoordTables tables;
    tables.corner_perm_move.assign(static_cast<std::size_t>(kCornerPermutationCount) * 18, 0);
    tables.corner_ori_move.assign(static_cast<std::size_t>(kCornerOrientationCount) * 18, 0);

    for (std::uint32_t rank = 0; rank < kCornerPermutationCount; ++rank) {
        std::array<std::uint8_t, 8> cp{};
        unrank_permutation8(rank, cp);
        for (int move_index = 0; move_index < 18; ++move_index) {
            const auto& move = moves[move_index];
            std::array<std::uint8_t, 8> out{};
            for (std::uint32_t i = 0; i < 8; ++i) {
                out[i] = cp[move.cp[i]];
            }
            tables.corner_perm_move[static_cast<std::size_t>(rank) * 18 + move_index] =
                static_cast<std::uint16_t>(rank_permutation8(out));
        }
    }

    for (std::uint32_t coord = 0; coord < kCornerOrientationCount; ++coord) {
        std::array<std::uint8_t, 8> co{};
        unrank_orientation3(coord, co);
        for (int move_index = 0; move_index < 18; ++move_index) {
            const auto& move = moves[move_index];
            std::array<std::uint8_t, 8> out{};
            for (std::uint32_t i = 0; i < 8; ++i) {
                out[i] = static_cast<std::uint8_t>((co[move.cp[i]] + move.co[i]) % 3);
            }
            tables.corner_ori_move[static_cast<std::size_t>(coord) * 18 + move_index] =
                static_cast<std::uint16_t>(rank_orientation3(out));
        }
    }
    return tables;
}

// Branch-light Lehmer ranking of an N-element subset permutation.
template <std::uint32_t N>
inline std::uint32_t rank_permutation_subset(const std::array<std::uint8_t, N>& values) {
    std::uint32_t rank = 0;
    std::uint32_t seen = 0;
    for (std::uint32_t index = 0; index < N; ++index) {
        const std::uint32_t value = values[index];
        const std::uint32_t below = static_cast<std::uint32_t>(popcount32(seen & ((1U << value) - 1U)));
        rank = rank * (N - index) + (value - below);
        seen |= 1U << value;
    }
    return rank;
}

inline std::uint32_t rank_permutation6(const std::array<std::uint8_t, 6>& values) {
    return rank_permutation_subset<6>(values);
}

inline std::uint32_t rank_permutation7(const std::array<std::uint8_t, 7>& values) {
    return rank_permutation_subset<7>(values);
}

// C(n, k) for the small (n <= 11, k <= 7) ranges used by combination ranking.
// kChoose only carries columns up to kSubsetSize (6); compute the rest directly.
std::uint32_t choose_small(std::uint32_t n, std::uint32_t k) {
    if (k > n) {
        return 0;
    }
    if (k <= kSubsetSize) {
        return kChoose[n][k];
    }
    std::uint64_t result = 1;
    const std::uint32_t kk = std::min(k, n - k);
    for (std::uint32_t i = 0; i < kk; ++i) {
        result = result * (n - i) / (i + 1);
    }
    return static_cast<std::uint32_t>(result);
}

template <std::uint32_t N>
std::uint32_t rank_combination_subset(const std::array<std::uint8_t, N>& positions) {
    std::uint32_t rank = 0;
    std::uint32_t next = 0;
    for (std::uint32_t i = 0; i < N; ++i) {
        for (std::uint32_t value = next; value < positions[i]; ++value) {
            rank += choose_small(12 - value - 1, N - i - 1);
        }
        next = positions[i] + 1;
    }
    return rank;
}

template <std::uint32_t N>
std::array<std::uint16_t, 4096> build_combination_rank_by_mask() {
    std::array<std::uint16_t, 4096> ranks{};
    ranks.fill(std::numeric_limits<std::uint16_t>::max());
    for (std::uint32_t mask = 0; mask < ranks.size(); ++mask) {
        if (popcount32(mask) != static_cast<int>(N)) {
            continue;
        }
        std::array<std::uint8_t, N> positions{};
        std::uint32_t index = 0;
        for (std::uint32_t position = 0; position < 12; ++position) {
            if ((mask & (1U << position)) != 0) {
                positions[index++] = static_cast<std::uint8_t>(position);
            }
        }
        ranks[mask] = static_cast<std::uint16_t>(rank_combination_subset<N>(positions));
    }
    return ranks;
}

// Eagerly-initialised globals so the hot path avoids the per-call
// function-local static guard check. The 7-edge table is built unconditionally
// (negligible 8 KiB) so it is ready whenever a 7-edge PDB is loaded.
const std::array<std::uint16_t, 4096> kCombinationRankByMask = build_combination_rank_by_mask<6>();
const std::array<std::uint16_t, 4096> kCombinationRankByMask7 = build_combination_rank_by_mask<7>();

inline std::uint32_t edge_subset_coord6(const State& state, const EdgePdb& pdb) {
    const auto& comb_rank = kCombinationRankByMask;
    std::array<std::uint8_t, 6> permutation{};
    std::uint32_t orientation = 0;
    std::uint32_t index = 0;
    std::uint32_t position_mask = 0;
    const int* e2s = pdb.edge_to_subset.data();
    for (std::uint32_t position = 0; position < 12; ++position) {
        const int subset_index = e2s[state.ep[position]];
        if (subset_index < 0) {
            continue;
        }
        position_mask |= 1U << position;
        permutation[index] = static_cast<std::uint8_t>(subset_index);
        orientation |= static_cast<std::uint32_t>(state.eo[position] & 1U) << index;
        ++index;
    }
    return (comb_rank[position_mask] * kPermutationCount6 + rank_permutation6(permutation)) *
        kOrientationCount6 + orientation;
}

inline std::uint32_t edge_subset_coord7(const State& state, const EdgePdb& pdb) {
    const auto& comb_rank = kCombinationRankByMask7;
    std::array<std::uint8_t, 7> permutation{};
    std::uint32_t orientation = 0;
    std::uint32_t index = 0;
    std::uint32_t position_mask = 0;
    const int* e2s = pdb.edge_to_subset.data();
    for (std::uint32_t position = 0; position < 12; ++position) {
        const int subset_index = e2s[state.ep[position]];
        if (subset_index < 0) {
            continue;
        }
        position_mask |= 1U << position;
        permutation[index] = static_cast<std::uint8_t>(subset_index);
        orientation |= static_cast<std::uint32_t>(state.eo[position] & 1U) << index;
        ++index;
    }
    return (comb_rank[position_mask] * kPermutationCount7 + rank_permutation7(permutation)) *
        kOrientationCount7 + orientation;
}

// Dispatch on the PDB's subset size. The branch is on a per-PDB constant, so it
// is perfectly predicted within any single-PDB loop.
inline std::uint32_t edge_subset_coord(const State& state, const EdgePdb& pdb) {
    return pdb.subset_size == kSubsetSize7 ? edge_subset_coord7(state, pdb) : edge_subset_coord6(state, pdb);
}

State inverse_state(const State& state) {
    State inverse{};
    for (std::uint32_t position = 0; position < 8; ++position) {
        const std::uint8_t cubie = state.cp[position];
        inverse.cp[cubie] = static_cast<std::uint8_t>(position);
        inverse.co[cubie] = static_cast<std::uint8_t>((3 - state.co[position]) % 3);
    }
    for (std::uint32_t position = 0; position < 12; ++position) {
        const std::uint8_t cubie = state.ep[position];
        inverse.ep[cubie] = static_cast<std::uint8_t>(position);
        inverse.eo[cubie] = state.eo[position];
    }
    return inverse;
}

std::vector<std::uint8_t> read_table_payload(const std::string& path, std::uint32_t header_bytes, std::uint32_t state_count) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        throw std::runtime_error("failed to open PDB file: " + path);
    }
    in.seekg(0, std::ios::end);
    const auto size = in.tellg();
    if (size != static_cast<std::streamoff>(header_bytes + state_count)) {
        throw std::runtime_error("unexpected PDB file size: " + path);
    }
    std::vector<std::uint8_t> distances(state_count);
    in.seekg(header_bytes, std::ios::beg);
    in.read(reinterpret_cast<char*>(distances.data()), static_cast<std::streamsize>(distances.size()));
    if (!in) {
        throw std::runtime_error("failed to read PDB payload: " + path);
    }
    return distances;
}

void load_corner_pdb(Solver& solver, const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        throw std::runtime_error("failed to open corner PDB: " + path);
    }
    in.read(reinterpret_cast<char*>(&solver.corner_header), sizeof(CornerHeader));
    if (!in || std::string(solver.corner_header.magic, solver.corner_header.magic + 7) != "R3CPDB1" ||
        solver.corner_header.version != 1 || solver.corner_header.state_count != kCornerStateCount ||
        solver.corner_header.complete != 1) {
        throw std::runtime_error("invalid or incomplete corner PDB: " + path);
    }
    solver.corner_distances = read_table_payload(path, solver.corner_header.header_bytes, solver.corner_header.state_count);
}

void load_edge_pdb(Solver& solver, const std::string& path, bool additive) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        throw std::runtime_error("failed to open edge PDB: " + path);
    }
    EdgeHeader header{};
    in.read(reinterpret_cast<char*>(&header), sizeof(EdgeHeader));
    const std::string expected_magic = additive ? "R3ECPD1" : "R3EPDB1";
    const std::uint32_t subset_size = header.subset_size;
    const bool size_ok = subset_size == kSubsetSize || subset_size == kSubsetSize7;
    const std::uint32_t expected_state_count = subset_size == kSubsetSize7 ? kEdgePdbStateCount7 : kEdgePdbStateCount;
    const std::uint32_t expected_combination = subset_size == kSubsetSize7 ? kCombinationCount7 : kCombinationCount;
    const std::uint32_t expected_permutation = subset_size == kSubsetSize7 ? kPermutationCount7 : kPermutationCount6;
    const std::uint32_t expected_orientation = subset_size == kSubsetSize7 ? kOrientationCount7 : kOrientationCount6;
    if (!in || std::string(header.magic, header.magic + 7) != expected_magic || header.version != 1 || !size_ok ||
        header.state_count != expected_state_count || header.combination_count != expected_combination ||
        header.permutation_count != expected_permutation || header.orientation_count != expected_orientation ||
        header.complete != 1) {
        throw std::runtime_error("invalid or incomplete edge PDB for expected magic " + expected_magic + ": " + path);
    }
    // subset_edges[6] and reserved[2] are contiguous packed bytes; ids beyond
    // index 5 (only the 7th, for a 7-edge PDB) live in reserved[0]. Validate the
    // ids exactly as the Python reader does (in range, distinct) BEFORE indexing
    // edge_to_subset, so a corrupt header cannot cause an out-of-bounds write or
    // a popcount-mismatched coordinate that reads garbage as an admissible bound.
    const std::uint8_t* subset_bytes = reinterpret_cast<const std::uint8_t*>(&header.subset_edges[0]);
    std::array<int, 12> edge_to_subset{};
    edge_to_subset.fill(-1);
    std::uint32_t seen_edges = 0;
    for (std::uint32_t index = 0; index < subset_size; ++index) {
        const std::uint8_t edge = subset_bytes[index];
        if (edge >= 12 || (seen_edges & (1U << edge)) != 0) {
            throw std::runtime_error("edge PDB has out-of-range or duplicate subset edge id: " + path);
        }
        seen_edges |= 1U << edge;
        edge_to_subset[edge] = static_cast<int>(index);
    }
    EdgePdb pdb{header, subset_size, edge_to_subset, read_table_payload(path, header.header_bytes, header.state_count)};
    if (additive) {
        solver.additive_edge_pdbs.push_back(std::move(pdb));
    } else {
        solver.edge_pdbs.push_back(std::move(pdb));
    }
}

// Exact forward heuristic (full MAX). Used for the root, for the IDA*
// threshold bookkeeping, and as the dual-heuristic inverse evaluation.
int forward_heuristic(const Solver& solver, const State& state) {
    int lower = solver.corner_distances[corner_coord(state)];
    for (const auto& pdb : solver.edge_pdbs) {
        const auto value = pdb.distances[edge_subset_coord(state, pdb)];
        if (value != kUnvisited && static_cast<int>(value) > lower) {
            lower = value;
        }
    }
    if (!solver.additive_edge_pdbs.empty()) {
        int additive_lower = 0;
        bool additive_complete = true;
        for (const auto& pdb : solver.additive_edge_pdbs) {
            const auto value = pdb.distances[edge_subset_coord(state, pdb)];
            if (value == kUnvisited) {
                additive_complete = false;
                break;
            }
            additive_lower += static_cast<int>(value);
        }
        if (additive_complete && additive_lower > lower) {
            lower = additive_lower;
        }
    }
#ifdef RUBIK_WITH_NISSY_BRIDGE
    if (solver.nissy_heuristic && state.has_nissy) {
        const int nissy_lower = nissy_bridge_light_lower_bound(state.nissy, 1, solver.nissy_axis_transforms ? 1 : 0);
        if (nissy_lower > lower) {
            lower = nissy_lower;
        }
    }
#endif
    return lower;
}

int heuristic(const Solver& solver, const State& state) {
    int lower = forward_heuristic(solver, state);
    if (solver.dual_heuristic) {
        const int inverse_lower = forward_heuristic(solver, inverse_state(state));
        if (inverse_lower > lower) {
            lower = inverse_lower;
        }
    }
    return lower;
}

void record_solution(Solver& solver, const std::vector<int>& path) {
    if (solver.solution.empty() || path.size() < solver.solution.size()) {
        solver.solution = path;
        if (solver.upper_solution_verified) {
            solver.upper_bound_shorter_solution_found =
                path.size() < static_cast<std::size_t>(solver.upper_bound_solution_length);
        }
    }
}

void record_worker_solution(WorkerContext& worker, const std::vector<int>& path) {
    if (worker.solution.empty() || path.size() < worker.solution.size()) {
        worker.solution = path;
    }
}

int opposite_face(int face) {
    switch (face) {
        case 0: return 3;
        case 3: return 0;
        case 1: return 4;
        case 4: return 1;
        case 2: return 5;
        case 5: return 2;
        default: return -1;
    }
}

bool should_skip_face_after_last(int face, int last_face, bool rotation_invariant_tree) {
    if (face == last_face) {
        return true;
    }
    // The opposite-face ordering prune depends on numeric face order. Rotational
    // transposition keys require the remaining search tree to be invariant under
    // face renaming, so keep only the same-face prune in that mode.
    if (!rotation_invariant_tree && last_face >= 0 && opposite_face(face) == last_face && face < last_face) {
        return true;
    }
    return false;
}

bool should_prune_transposition(Solver& solver, const State& state, int last_face, int g) {
    if (solver.tt_entry_limit == 0) {
        return false;
    }
    if (solver.compact_transpositions) {
        const PackedTranspositionKey key = make_packed_transposition_key(
            solver.symmetry_transpositions,
            solver.full_symmetry_transpositions,
            state,
            last_face
        );
        return compact_transposition_should_prune(
            solver.compact_transpositions_table,
            key,
            g,
            solver.tt_hits,
            solver.tt_inserts,
            solver.tt_updates,
            solver.tt_capacity_skips
        );
    }
    const TranspositionKey key = make_transposition_key(
        solver.symmetry_transpositions,
        solver.full_symmetry_transpositions,
        state,
        last_face
    );
    const auto found = solver.transpositions.find(key);
    if (found != solver.transpositions.end()) {
        if (found->second <= static_cast<std::uint8_t>(g)) {
            ++solver.tt_hits;
            return true;
        }
        found->second = static_cast<std::uint8_t>(g);
        ++solver.tt_updates;
        return false;
    }
    if (solver.transpositions.size() < solver.tt_entry_limit) {
        solver.transpositions.emplace(key, static_cast<std::uint8_t>(g));
        ++solver.tt_inserts;
    } else {
        ++solver.tt_capacity_skips;
    }
    return false;
}

bool should_prune_worker_transposition(WorkerContext& worker, const State& state, int last_face, int g) {
    if (worker.tt_entry_limit == 0) {
        return false;
    }
    if (worker.compact_transpositions) {
        const PackedTranspositionKey key = make_packed_transposition_key(
            worker.symmetry_transpositions,
            worker.full_symmetry_transpositions,
            state,
            last_face
        );
        return compact_transposition_should_prune(
            worker.compact_transpositions_table,
            key,
            g,
            worker.tt_hits,
            worker.tt_inserts,
            worker.tt_updates,
            worker.tt_capacity_skips
        );
    }
    const TranspositionKey key = make_transposition_key(
        worker.symmetry_transpositions,
        worker.full_symmetry_transpositions,
        state,
        last_face
    );
    const auto found = worker.transpositions.find(key);
    if (found != worker.transpositions.end()) {
        if (found->second <= static_cast<std::uint8_t>(g)) {
            ++worker.tt_hits;
            return true;
        }
        found->second = static_cast<std::uint8_t>(g);
        ++worker.tt_updates;
        return false;
    }
    if (worker.transpositions.size() < worker.tt_entry_limit) {
        worker.transpositions.emplace(key, static_cast<std::uint8_t>(g));
        ++worker.tt_inserts;
    } else {
        ++worker.tt_capacity_skips;
    }
    return false;
}

// ---------------------------------------------------------------------------
// Fast IDA* engine (make/undo, incremental corner coordinates).
//
// A SearchState bundles the mutable cubie arrays with the incrementally
// maintained corner permutation/orientation coordinates. Moves are applied in
// place via make_move/undo_move; the corner coordinates are pushed/popped so
// the corner PDB lookup costs one indexed read per node instead of a fresh
// rank.
// ---------------------------------------------------------------------------
struct SearchState {
    State cube;
    std::uint32_t corner_perm;  // 0..40319
    std::uint32_t corner_ori;   // 0..2186
};

inline void apply_base_inplace(State& state, const BaseMove& move) {
    State out;
    for (std::uint32_t i = 0; i < 8; ++i) {
        out.cp[i] = state.cp[move.cp[i]];
        out.co[i] = static_cast<std::uint8_t>((state.co[move.cp[i]] + move.co[i]) % 3);
    }
    for (std::uint32_t i = 0; i < 12; ++i) {
        out.ep[i] = state.ep[move.ep[i]];
        out.eo[i] = static_cast<std::uint8_t>((state.eo[move.ep[i]] + move.eo[i]) & 1U);
    }
    state.cp = out.cp;
    state.co = out.co;
    state.ep = out.ep;
    state.eo = out.eo;
}

// Exact MAX heuristic over a SearchState whose corner coordinates are already
// known. This computes the identical admissible value as forward_heuristic.
inline int search_state_heuristic_full(const Solver& solver, const SearchState& s) {
    int lower = solver.corner_distances[s.corner_perm * kCornerOrientationCount + s.corner_ori];
    for (const auto& pdb : solver.edge_pdbs) {
        const int value = pdb.distances[edge_subset_coord(s.cube, pdb)];
        if (value > lower) {
            lower = value;
        }
    }
    if (!solver.additive_edge_pdbs.empty()) {
        int additive_lower = 0;
        for (const auto& pdb : solver.additive_edge_pdbs) {
            additive_lower += static_cast<int>(pdb.distances[edge_subset_coord(s.cube, pdb)]);
        }
        if (additive_lower > lower) {
            lower = additive_lower;
        }
    }
#ifdef RUBIK_WITH_NISSY_BRIDGE
    if (solver.nissy_heuristic && s.cube.has_nissy) {
        const int nissy_lower = nissy_bridge_light_lower_bound(s.cube.nissy, 1, solver.nissy_axis_transforms ? 1 : 0);
        if (nissy_lower > lower) {
            lower = nissy_lower;
        }
    }
#endif
    if (solver.dual_heuristic) {
        const int inverse_lower = forward_heuristic(solver, inverse_state(s.cube));
        if (inverse_lower > lower) {
            lower = inverse_lower;
        }
    }
    return lower;
}

// Early-exit MAX heuristic. Computes the admissible MAX exactly UNLESS it can
// prove the value already exceeds `target` (i.e. g+1+h > bound), in which case
// it returns early with a value that is >= target+1 but still a valid lower
// bound (every component is an admissible lower bound, and we only stop once a
// single component already surpasses the threshold). The returned value is
// therefore always <= the true exact heuristic when it short-circuits AND
// strictly greater than `target`, so:
//   * pruning decisions are identical to the exact heuristic (we only return a
//     short-circuit value when some admissible component already proves the
//     prune), and
//   * the value fed into the IDA* `minimum` bookkeeping stays admissible
//     (<= true distance) and strictly above the current bound, so the next
//     threshold strictly increases. Optimality is preserved.
// When the value does NOT exceed target, the full exact MAX is returned.
//
// `target` is the largest heuristic value that would still keep the child
// inside the bound (i.e. bound - g_child). Components stop being evaluated once
// `lower > target`.
inline int search_state_heuristic_bounded(const Solver& solver, const SearchState& s, int target) {
    int lower = solver.corner_distances[s.corner_perm * kCornerOrientationCount + s.corner_ori];
    if (lower > target) {
        return lower;
    }
    // The additive (cost-partitioned) sum and dual/nissy heuristics are rare in
    // the default configuration; when present fall back to the exact MAX to
    // keep the bookkeeping simple and correct.
    if (!solver.additive_edge_pdbs.empty() || solver.dual_heuristic
#ifdef RUBIK_WITH_NISSY_BRIDGE
        || (solver.nissy_heuristic && s.cube.has_nissy)
#endif
    ) {
        return search_state_heuristic_full(solver, s);
    }
    for (const auto& pdb : solver.edge_pdbs) {
        const int value = pdb.distances[edge_subset_coord(s.cube, pdb)];
        if (value > lower) {
            lower = value;
            if (lower > target) {
                return lower;
            }
        }
    }
    return lower;
}

inline void search_state_init(const Solver& solver, SearchState& s, const State& cube) {
    s.cube = cube;
    s.corner_perm = rank_permutation8(cube.cp);
    s.corner_ori = rank_orientation3(cube.co);
}

inline void search_state_make(const Solver& solver, SearchState& s, int move_index) {
    apply_base_inplace(s.cube, solver.moves[move_index]);
    const CoordTables& c = *solver.coords;
    s.corner_perm = c.corner_perm_move[static_cast<std::size_t>(s.corner_perm) * 18 + move_index];
    s.corner_ori = c.corner_ori_move[static_cast<std::size_t>(s.corner_ori) * 18 + move_index];
#ifdef RUBIK_WITH_NISSY_BRIDGE
    if (s.cube.has_nissy) {
        s.cube.nissy = nissy_bridge_apply_move(s.cube.nissy, move_index);
    }
#endif
}

int search_recurse(Solver& solver, SearchState& s, int g, int bound, int last_face, int h);

int search(Solver& solver, const State& state, int g, int bound, int last_face, int h) {
    // Translate the recursive solver entry point into the make/undo engine.
    SearchState s;
    search_state_init(solver, s, state);
    return search_recurse(solver, s, g, bound, last_face, h);
}

int search_recurse(Solver& solver, SearchState& s, int g, int bound, int last_face, int h) {
    if ((solver.expanded & 0x3fffU) == 0 && std::chrono::steady_clock::now() >= solver.deadline) {
        solver.timed_out = true;
        return kTimeout;
    }
    if (solver.node_limit != 0 && solver.expanded >= solver.node_limit) {
        solver.node_limited = true;
        return kNodeLimit;
    }
    const int f = g + h;
    if (f > bound) {
        return f;
    }
    if (is_solved(s.cube)) {
        if (solver.upper_bound_proof_active) {
            record_solution(solver, solver.path);
            return std::numeric_limits<int>::max();
        }
        record_solution(solver, solver.path);
        return kFound;
    }
    if (solver.tt_entry_limit != 0 && should_prune_transposition(solver, s.cube, last_face, g)) {
        return std::numeric_limits<int>::max();
    }
    ++solver.expanded;
    int minimum = std::numeric_limits<int>::max();

    struct ChildSlot {
        SearchState state;
        int move_index;
        int face;
        int heuristic;
    };
    std::array<ChildSlot, 18> children;
    int child_count = 0;
    const int child_target = bound - (g + 1);
    for (int move_index = 0; move_index < 18; ++move_index) {
        if (g == 0 && solver.root_move_mask_enabled && !solver.root_move_allowed[move_index]) {
            continue;
        }
        const int face = move_index / 3;
        if (should_skip_face_after_last(face, last_face, solver.symmetry_transpositions)) {
            continue;
        }
        // Apply the move once into the child's slot (no re-application later).
        SearchState& child = children[child_count].state;
        child = s;
        search_state_make(solver, child, move_index);
        ++solver.generated;
        const int child_h = search_state_heuristic_bounded(solver, child, child_target);
        if (g + 1 + child_h > bound) {
            const int child_f = g + 1 + child_h;
            if (child_f < minimum) {
                minimum = child_f;
            }
            continue;
        }
        children[child_count].move_index = move_index;
        children[child_count].face = face;
        children[child_count].heuristic = child_h;
        ++child_count;
    }
    if (solver.child_order != ChildOrder::MoveIndex) {
        std::sort(children.begin(), children.begin() + child_count, [&solver](const ChildSlot& a, const ChildSlot& b) {
            if (a.heuristic != b.heuristic) {
                if (solver.child_order == ChildOrder::HeuristicAscending) {
                    return a.heuristic < b.heuristic;
                }
                return a.heuristic > b.heuristic;
            }
            return a.move_index < b.move_index;
        });
    }
    for (int index = 0; index < child_count; ++index) {
        ChildSlot& child = children[index];
        solver.path.push_back(child.move_index);
        const int outcome = search_recurse(solver, child.state, g + 1, bound, child.face, child.heuristic);
        solver.path.pop_back();
        if (outcome == kFound || outcome == kTimeout || outcome == kNodeLimit) {
            return outcome;
        }
        if (outcome < minimum) {
            minimum = outcome;
        }
    }
    return minimum;
}

int worker_search_recurse(
    const Solver& tables,
    WorkerContext& worker,
    SearchState& s,
    int g,
    int bound,
    int last_face,
    int h
) {
    if (worker.stop_requested != nullptr && worker.stop_requested->load(std::memory_order_relaxed)) {
        return kStopped;
    }
    if ((worker.expanded & 0x3fffU) == 0 && std::chrono::steady_clock::now() >= worker.deadline) {
        worker.timed_out = true;
        if (worker.stop_requested != nullptr) {
            worker.stop_requested->store(true, std::memory_order_relaxed);
        }
        return kTimeout;
    }
    if (worker.node_limit != 0 && worker.expanded >= worker.node_limit) {
        worker.node_limited = true;
        if (worker.stop_requested != nullptr) {
            worker.stop_requested->store(true, std::memory_order_relaxed);
        }
        return kNodeLimit;
    }
    const int f = g + h;
    if (f > bound) {
        return f;
    }
    if (is_solved(s.cube)) {
        if (tables.upper_bound_proof_active) {
            record_worker_solution(worker, worker.path);
            return std::numeric_limits<int>::max();
        }
        record_worker_solution(worker, worker.path);
        if (worker.stop_requested != nullptr) {
            worker.stop_requested->store(true, std::memory_order_relaxed);
        }
        return kFound;
    }
    if (worker.tt_entry_limit != 0 && should_prune_worker_transposition(worker, s.cube, last_face, g)) {
        return std::numeric_limits<int>::max();
    }
    ++worker.expanded;
    int minimum = std::numeric_limits<int>::max();

    struct ChildSlot {
        SearchState state;
        int move_index;
        int face;
        int heuristic;
    };
    std::array<ChildSlot, 18> children;
    int child_count = 0;
    const int child_target = bound - (g + 1);
    for (int move_index = 0; move_index < 18; ++move_index) {
        if (g == 0 && tables.root_move_mask_enabled && !tables.root_move_allowed[move_index]) {
            continue;
        }
        const int face = move_index / 3;
        if (should_skip_face_after_last(face, last_face, tables.symmetry_transpositions)) {
            continue;
        }
        SearchState& child = children[child_count].state;
        child = s;
        search_state_make(tables, child, move_index);
        ++worker.generated;
        const int child_h = search_state_heuristic_bounded(tables, child, child_target);
        if (g + 1 + child_h > bound) {
            const int child_f = g + 1 + child_h;
            if (child_f < minimum) {
                minimum = child_f;
            }
            continue;
        }
        children[child_count].move_index = move_index;
        children[child_count].face = face;
        children[child_count].heuristic = child_h;
        ++child_count;
    }
    if (tables.child_order != ChildOrder::MoveIndex) {
        std::sort(children.begin(), children.begin() + child_count, [&tables](const ChildSlot& a, const ChildSlot& b) {
            if (a.heuristic != b.heuristic) {
                if (tables.child_order == ChildOrder::HeuristicAscending) {
                    return a.heuristic < b.heuristic;
                }
                return a.heuristic > b.heuristic;
            }
            return a.move_index < b.move_index;
        });
    }
    for (int index = 0; index < child_count; ++index) {
        if (worker.stop_requested != nullptr && worker.stop_requested->load(std::memory_order_relaxed)) {
            return kStopped;
        }
        ChildSlot& child = children[index];
        worker.path.push_back(child.move_index);
        const int outcome = worker_search_recurse(tables, worker, child.state, g + 1, bound, child.face, child.heuristic);
        worker.path.pop_back();
        if (outcome == kFound || outcome == kTimeout || outcome == kNodeLimit || outcome == kStopped) {
            return outcome;
        }
        if (outcome < minimum) {
            minimum = outcome;
        }
    }
    return minimum;
}

int worker_search(
    const Solver& tables,
    WorkerContext& worker,
    const State& state,
    int g,
    int bound,
    int last_face,
    int h
) {
    SearchState s;
    search_state_init(tables, s, state);
    return worker_search_recurse(tables, worker, s, g, bound, last_face, h);
}

void build_split_tasks(
    Solver& solver,
    const State& state,
    int g,
    int bound,
    int last_face,
    int h,
    int split_depth,
    std::vector<int>& path,
    std::vector<SearchTask>& tasks,
    SplitBuildResult& result
) {
    if (result.found || result.timed_out || result.node_limited) {
        return;
    }
    if ((solver.expanded & 0x3fffU) == 0 && std::chrono::steady_clock::now() >= solver.deadline) {
        solver.timed_out = true;
        result.timed_out = true;
        return;
    }
    if (solver.node_limit != 0 && solver.expanded >= solver.node_limit) {
        solver.node_limited = true;
        result.node_limited = true;
        return;
    }
    const int f = g + h;
    if (f > bound) {
        if (f < result.minimum) {
            result.minimum = f;
        }
        return;
    }
    if (is_solved(state)) {
        if (solver.upper_bound_proof_active) {
            record_solution(solver, path);
            return;
        }
        result.found = true;
        result.solution = path;
        return;
    }
    if (g >= split_depth) {
        tasks.push_back({state, path, last_face, g, h});
        return;
    }

    ++solver.expanded;
    for (int move_index = 0; move_index < 18; ++move_index) {
        if (g == 0 && solver.root_move_mask_enabled && !solver.root_move_allowed[move_index]) {
            continue;
        }
        const int face = move_index / 3;
        if (should_skip_face_after_last(face, last_face, solver.symmetry_transpositions)) {
            continue;
        }
        const State child = apply_move(state, solver.moves[move_index], move_index);
        ++solver.generated;
        const int child_h = heuristic(solver, child);
        const int child_f = g + 1 + child_h;
        if (child_f > bound) {
            if (child_f < result.minimum) {
                result.minimum = child_f;
            }
            continue;
        }
        path.push_back(move_index);
        build_split_tasks(solver, child, g + 1, bound, face, child_h, split_depth, path, tasks, result);
        path.pop_back();
        if (result.found || result.timed_out || result.node_limited) {
            return;
        }
    }
}

int parallel_search_bound(
    Solver& solver,
    const State& state,
    int bound,
    int root_h,
    int thread_count,
    int split_depth
) {
    if (thread_count <= 1) {
        return search(solver, state, 0, bound, -1, root_h);
    }
    if (root_h > bound) {
        return root_h;
    }
    if (is_solved(state)) {
        solver.solution = solver.path;
        return kFound;
    }

    std::vector<SearchTask> tasks;
    std::vector<int> prefix_path;
    SplitBuildResult split_result;
    build_split_tasks(
        solver,
        state,
        0,
        bound,
        -1,
        root_h,
        std::max(1, split_depth),
        prefix_path,
        tasks,
        split_result
    );
    solver.split_tasks += tasks.size();
    if (split_result.found) {
        record_solution(solver, split_result.solution);
        return kFound;
    }
    if (split_result.timed_out) {
        return kTimeout;
    }
    if (split_result.node_limited) {
        return kNodeLimit;
    }
    int minimum = split_result.minimum;
    if (tasks.empty()) {
        if (!solver.solution.empty()) {
            return kFound;
        }
        return minimum;
    }

    const int workers_count = std::max(1, std::min(thread_count, static_cast<int>(tasks.size())));
    std::atomic<int> next_index{0};
    std::atomic<bool> stop_requested{false};
    std::atomic<bool> found_solution{false};
    std::atomic<bool> timed_out{false};
    std::atomic<bool> node_limited{false};
    std::mutex result_mutex;
    std::vector<int> best_solution;
    std::vector<WorkerContext> workers(static_cast<std::size_t>(workers_count));
    std::vector<std::thread> threads;
    threads.reserve(static_cast<std::size_t>(workers_count));
    const std::uint64_t remaining_node_limit =
        solver.node_limit == 0 || solver.expanded >= solver.node_limit ? 0 : solver.node_limit - solver.expanded;
    const std::uint64_t per_worker_node_limit =
        remaining_node_limit == 0 ? 0 : std::max<std::uint64_t>(1, remaining_node_limit / workers_count);
    const std::uint64_t per_worker_tt_limit =
        solver.tt_entry_limit == 0 ? 0 : std::max<std::uint64_t>(1, solver.tt_entry_limit / workers_count);

    for (int worker_index = 0; worker_index < workers_count; ++worker_index) {
        workers[worker_index].deadline = solver.deadline;
        workers[worker_index].node_limit = per_worker_node_limit;
        workers[worker_index].tt_entry_limit = per_worker_tt_limit;
        workers[worker_index].symmetry_transpositions = solver.symmetry_transpositions;
        workers[worker_index].full_symmetry_transpositions = solver.full_symmetry_transpositions;
        workers[worker_index].compact_transpositions = solver.compact_transpositions;
        if (solver.compact_transpositions) {
            reset_compact_transposition_table(workers[worker_index].compact_transpositions_table, per_worker_tt_limit);
        }
        workers[worker_index].stop_requested = &stop_requested;
        threads.emplace_back([&, worker_index]() {
            WorkerContext& worker = workers[worker_index];
            int worker_minimum = std::numeric_limits<int>::max();
            while (!stop_requested.load(std::memory_order_relaxed)) {
                const int task_index = next_index.fetch_add(1, std::memory_order_relaxed);
                if (task_index >= static_cast<int>(tasks.size())) {
                    break;
                }
                const auto& task = tasks[task_index];
                worker.path = task.path;
                const int outcome = worker_search(
                    solver,
                    worker,
                    task.state,
                    task.depth,
                    bound,
                    task.last_face,
                    task.heuristic
                );
                if (outcome == kFound) {
                    found_solution.store(true, std::memory_order_relaxed);
                    std::lock_guard<std::mutex> lock(result_mutex);
                    if (best_solution.empty() || worker.solution.size() < best_solution.size()) {
                        best_solution = worker.solution;
                    }
                    stop_requested.store(true, std::memory_order_relaxed);
                    return;
                }
                if (outcome == kTimeout) {
                    timed_out.store(true, std::memory_order_relaxed);
                    stop_requested.store(true, std::memory_order_relaxed);
                    return;
                }
                if (outcome == kNodeLimit) {
                    node_limited.store(true, std::memory_order_relaxed);
                    stop_requested.store(true, std::memory_order_relaxed);
                    return;
                }
                if (outcome != kStopped && outcome < worker_minimum) {
                    worker_minimum = outcome;
                }
            }
            std::lock_guard<std::mutex> lock(result_mutex);
            if (!worker.solution.empty() && (best_solution.empty() || worker.solution.size() < best_solution.size())) {
                best_solution = worker.solution;
                found_solution.store(true, std::memory_order_relaxed);
            }
            if (worker_minimum < minimum) {
                minimum = worker_minimum;
            }
        });
    }
    for (auto& thread : threads) {
        thread.join();
    }

    for (const auto& worker : workers) {
        solver.expanded += worker.expanded;
        solver.generated += worker.generated;
        solver.tt_hits += worker.tt_hits;
        solver.tt_inserts += worker.tt_inserts;
        solver.tt_updates += worker.tt_updates;
        solver.tt_capacity_skips += worker.tt_capacity_skips;
        solver.tt_current_entries += solver.compact_transpositions
            ? worker.compact_transpositions_table.used
            : worker.transpositions.size();
    }
    if (found_solution.load(std::memory_order_relaxed)) {
        if (!best_solution.empty()) {
            record_solution(solver, best_solution);
        }
        return kFound;
    }
    if (!solver.solution.empty()) {
        return kFound;
    }
    if (timed_out.load(std::memory_order_relaxed)) {
        solver.timed_out = true;
        return kTimeout;
    }
    if (node_limited.load(std::memory_order_relaxed)) {
        solver.node_limited = true;
        return kNodeLimit;
    }
    return minimum;
}

std::vector<std::uint8_t> parse_u8_list(const std::string& text, std::size_t expected, const std::string& label) {
    std::vector<std::uint8_t> values;
    std::stringstream stream(text);
    std::string item;
    while (std::getline(stream, item, ',')) {
        if (!item.empty()) {
            values.push_back(static_cast<std::uint8_t>(std::stoi(item)));
        }
    }
    if (values.size() != expected) {
        throw std::runtime_error(label + " expects " + std::to_string(expected) + " comma-separated values");
    }
    return values;
}

int move_index_from_token(const std::string& token) {
    for (std::size_t index = 0; index < kMoveNames.size(); ++index) {
        if (token == kMoveNames[index]) {
            return static_cast<int>(index);
        }
    }
    throw std::runtime_error("invalid move in upper solution: " + token);
}

std::vector<int> parse_move_sequence(const std::string& text) {
    std::vector<int> moves;
    std::stringstream stream(text);
    std::string token;
    while (stream >> token) {
        moves.push_back(move_index_from_token(token));
    }
    return moves;
}

std::array<bool, 18> parse_root_move_mask(const std::string& text) {
    std::array<bool, 18> allowed{};
    std::stringstream stream(text);
    std::string token;
    int count = 0;
    while (std::getline(stream, token, ',')) {
        if (token.empty()) {
            continue;
        }
        const int move_index = move_index_from_token(token);
        if (!allowed[move_index]) {
            ++count;
        }
        allowed[move_index] = true;
    }
    if (count == 0) {
        throw std::runtime_error("--root-move-mask must name at least one legal move");
    }
    return allowed;
}

bool verify_upper_solution(const Solver& solver, const State& initial, const std::vector<int>& moves) {
    State state = initial;
    for (const int move_index : moves) {
        state = apply_move(state, solver.moves[move_index], move_index);
    }
    return is_solved(state);
}

Options parse_options(int argc, char** argv) {
    Options options;
    options.state = solved_state();
    options.root_move_allowed.fill(true);
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--corner-pdb" && i + 1 < argc) {
            options.corner_pdb_path = argv[++i];
        } else if (arg == "--edge-pdb" && i + 1 < argc) {
            options.edge_pdb_paths.push_back(argv[++i]);
        } else if (arg == "--additive-edge-pdb" && i + 1 < argc) {
            options.additive_edge_pdb_paths.push_back(argv[++i]);
        } else if (arg == "--cp" && i + 1 < argc) {
            auto values = parse_u8_list(argv[++i], 8, "--cp");
            std::copy(values.begin(), values.end(), options.state.cp.begin());
        } else if (arg == "--co" && i + 1 < argc) {
            auto values = parse_u8_list(argv[++i], 8, "--co");
            std::copy(values.begin(), values.end(), options.state.co.begin());
        } else if (arg == "--ep" && i + 1 < argc) {
            auto values = parse_u8_list(argv[++i], 12, "--ep");
            std::copy(values.begin(), values.end(), options.state.ep.begin());
        } else if (arg == "--eo" && i + 1 < argc) {
            auto values = parse_u8_list(argv[++i], 12, "--eo");
            std::copy(values.begin(), values.end(), options.state.eo.begin());
        } else if (arg == "--max-depth" && i + 1 < argc) {
            options.max_depth = std::stoi(argv[++i]);
        } else if (arg == "--timeout" && i + 1 < argc) {
            options.timeout_seconds = std::stod(argv[++i]);
        } else if (arg == "--node-limit" && i + 1 < argc) {
            options.node_limit = static_cast<std::uint64_t>(std::stoull(argv[++i]));
        } else if (arg == "--tt-entries" && i + 1 < argc) {
            options.tt_entries = static_cast<std::uint64_t>(std::stoull(argv[++i]));
        } else if (arg == "--threads" && i + 1 < argc) {
            options.threads = std::max(1, std::stoi(argv[++i]));
        } else if (arg == "--split-depth" && i + 1 < argc) {
            options.split_depth = std::max(1, std::stoi(argv[++i]));
        } else if (arg == "--child-order" && i + 1 < argc) {
            options.child_order = parse_child_order(argv[++i]);
        } else if (arg == "--emit-edge-coords") {
            options.emit_edge_coords = true;
        } else if (arg == "--dual-heuristic") {
            options.dual_heuristic = true;
        } else if (arg == "--nissy-heuristic") {
            options.nissy_heuristic = true;
        } else if (arg == "--nissy-axis-transforms") {
            options.nissy_axis_transforms = true;
        } else if (arg == "--nissy-data" && i + 1 < argc) {
            options.nissy_data_dir = argv[++i];
        } else if (arg == "--nissy-sequence" && i + 1 < argc) {
            options.nissy_sequence = argv[++i];
        } else if (arg == "--upper-solution" && i + 1 < argc) {
            options.upper_solution = parse_move_sequence(argv[++i]);
        } else if (arg == "--upper-bound-proof-strategy" && i + 1 < argc) {
            options.upper_bound_proof_strategy = parse_upper_bound_proof_strategy(argv[++i]);
        } else if (arg == "--root-move-mask" && i + 1 < argc) {
            options.root_move_allowed = parse_root_move_mask(argv[++i]);
            options.root_move_mask_enabled = true;
        } else if (arg == "--symmetry-transpositions") {
            options.symmetry_transpositions = true;
        } else if (arg == "--full-symmetry-transpositions") {
            options.symmetry_transpositions = true;
            options.full_symmetry_transpositions = true;
        } else if (arg == "--compact-transpositions") {
            options.compact_transpositions = true;
        } else if (arg == "--help") {
            std::cout << "usage: optimal_solver --corner-pdb PATH --edge-pdb PATH [--edge-pdb PATH] "
                         "[--additive-edge-pdb PATH] "
                         "--cp CSV --co CSV --ep CSV --eo CSV [--max-depth 20] [--timeout SEC] "
                         "[--tt-entries COUNT] [--threads N] [--split-depth N] "
                         "[--child-order heuristic-desc|heuristic-asc|move] [--dual-heuristic] "
                         "[--nissy-heuristic --nissy-data DIR --nissy-axis-transforms --nissy-sequence SCRAMBLE] "
                         "[--upper-solution MOVES --upper-bound-proof-strategy iterative|single-bound] "
                         "[--root-move-mask MOVES_CSV] [--symmetry-transpositions] "
                         "[--full-symmetry-transpositions] [--compact-transpositions]\n";
            std::exit(0);
        } else {
            throw std::runtime_error("unknown or incomplete argument: " + arg);
        }
    }
    if (options.corner_pdb_path.empty()) {
        throw std::runtime_error("--corner-pdb is required");
    }
    return options;
}

int root_move_count(const Solver& solver) {
    if (!solver.root_move_mask_enabled) {
        return 18;
    }
    int count = 0;
    for (bool allowed : solver.root_move_allowed) {
        if (allowed) {
            ++count;
        }
    }
    return count;
}

void reset_solver_transpositions(Solver& solver) {
    solver.transpositions.clear();
    reset_compact_transposition_table(
        solver.compact_transpositions_table,
        solver.compact_transpositions ? solver.tt_entry_limit : 0
    );
    solver.tt_current_entries = 0;
}

void print_solution_json(
    const std::string& requested_status,
    const Solver& solver,
    const std::chrono::steady_clock::time_point& begin,
    int final_bound,
    int thread_count,
    int split_depth
) {
    // Under --root-move-mask the search is only exhaustive over the masked
    // root tree, so optimality is conditional on the caller's symmetry
    // argument for the mask -- something this binary cannot check.  Report a
    // machine-distinguishable status ("exact_under_root_mask") so no consumer
    // can mistake conditional exactness for unconditional exactness.
    const std::string status =
        (requested_status == "exact" && solver.root_move_mask_enabled)
            ? "exact_under_root_mask"
            : requested_status;
    const auto end = std::chrono::steady_clock::now();
    const double runtime_seconds = std::chrono::duration<double>(end - begin).count();
    std::cout << "{\n";
    std::cout << "  \"schema_version\": 1,\n";
    std::cout << "  \"solver_name\": \"korf_native_optimal\",\n";
    std::cout << "  \"status\": \"" << status << "\",\n";
    std::cout << "  \"metric\": \"HTM\",\n";
    std::cout << "  \"solution_moves\": [";
    for (std::size_t index = 0; index < solver.solution.size(); ++index) {
        if (index > 0) {
            std::cout << ", ";
        }
        std::cout << "\"" << kMoveNames[solver.solution[index]] << "\"";
    }
    std::cout << "],\n";
    if (status == "exact" || status == "exact_under_root_mask") {
        std::cout << "  \"solution_length\": " << solver.solution.size() << ",\n";
    } else {
        std::cout << "  \"solution_length\": null,\n";
    }
    std::cout << "  \"runtime_seconds\": " << runtime_seconds << ",\n";
    std::cout << "  \"expanded_nodes\": " << solver.expanded << ",\n";
    std::cout << "  \"generated_nodes\": " << solver.generated << ",\n";
    std::cout << "  \"initial_lower_bound\": " << solver.lower_bound << ",\n";
    std::cout << "  \"final_bound\": " << final_bound << ",\n";
    std::cout << "  \"corner_pdb_states\": " << solver.corner_header.state_count << ",\n";
    std::cout << "  \"edge_pdb_count\": " << solver.edge_pdbs.size() << ",\n";
    std::cout << "  \"additive_edge_pdb_count\": " << solver.additive_edge_pdbs.size() << ",\n";
    std::cout << "  \"threads\": " << thread_count << ",\n";
    std::cout << "  \"split_depth\": " << split_depth << ",\n";
    std::cout << "  \"split_tasks\": " << solver.split_tasks << ",\n";
    std::cout << "  \"child_order\": \"" << child_order_name(solver.child_order) << "\",\n";
    std::cout << "  \"dual_heuristic\": " << (solver.dual_heuristic ? "true" : "false") << ",\n";
    std::cout << "  \"nissy_heuristic\": " << (solver.nissy_heuristic ? "true" : "false") << ",\n";
    std::cout << "  \"nissy_axis_transforms\": " << (solver.nissy_axis_transforms ? "true" : "false") << ",\n";
    std::cout << "  \"upper_solution_verified\": " << (solver.upper_solution_verified ? "true" : "false") << ",\n";
    std::cout << "  \"exact_certified_by_upper_bound\": "
              << (solver.exact_certified_by_upper_bound ? "true" : "false") << ",\n";
    std::cout << "  \"upper_bound_solution_length\": " << solver.upper_bound_solution_length << ",\n";
    std::cout << "  \"upper_bound_proof_strategy\": \""
              << upper_bound_proof_strategy_name(solver.upper_bound_proof_strategy) << "\",\n";
    std::cout << "  \"upper_bound_proof_search_bound\": " << solver.upper_bound_proof_search_bound << ",\n";
    std::cout << "  \"upper_bound_proof_exhaustive\": "
              << (solver.upper_bound_proof_exhaustive ? "true" : "false") << ",\n";
    std::cout << "  \"upper_bound_shorter_solution_found\": "
              << (solver.upper_bound_shorter_solution_found ? "true" : "false") << ",\n";
    std::cout << "  \"root_move_mask_enabled\": "
              << (solver.root_move_mask_enabled ? "true" : "false") << ",\n";
    std::cout << "  \"root_move_count\": " << root_move_count(solver) << ",\n";
    std::cout << "  \"symmetry_transpositions\": " << (solver.symmetry_transpositions ? "true" : "false") << ",\n";
    std::cout << "  \"symmetry_rotation_count\": " << (solver.symmetry_transpositions ? rotation_transforms().size() : 0) << ",\n";
    std::cout << "  \"full_symmetry_transpositions\": "
              << (solver.full_symmetry_transpositions ? "true" : "false") << ",\n";
    std::cout << "  \"symmetry_transform_count\": "
              << (
                  solver.symmetry_transpositions
                      ? (solver.full_symmetry_transpositions ? full_symmetry_transforms().size() : rotation_transforms().size())
                      : 0
                  ) << ",\n";
    std::cout << "  \"compact_transpositions\": " << (solver.compact_transpositions ? "true" : "false") << ",\n";
    std::cout << "  \"tt_entry_limit\": " << solver.tt_entry_limit << ",\n";
    std::cout << "  \"tt_entries\": "
              << ((solver.compact_transpositions ? solver.compact_transpositions_table.used : solver.transpositions.size())
                  + solver.tt_current_entries) << ",\n";
    std::cout << "  \"tt_hits\": " << solver.tt_hits << ",\n";
    std::cout << "  \"tt_inserts\": " << solver.tt_inserts << ",\n";
    std::cout << "  \"tt_updates\": " << solver.tt_updates << ",\n";
    std::cout << "  \"tt_capacity_skips\": " << solver.tt_capacity_skips << "\n";
    std::cout << "}\n";
}

} // namespace

int main(int argc, char** argv) {
    try {
        auto options = parse_options(argc, argv);
        const auto begin = std::chrono::steady_clock::now();
        Solver solver;
        solver.moves = build_moves();
        static const CoordTables coord_tables = build_coord_tables(solver.moves);
        solver.coords = &coord_tables;
        solver.deadline = begin + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
            std::chrono::duration<double>(options.timeout_seconds));
        solver.node_limit = options.node_limit;
        solver.tt_entry_limit = options.tt_entries;
        solver.dual_heuristic = options.dual_heuristic;
        solver.nissy_heuristic = options.nissy_heuristic;
        solver.child_order = options.child_order;
        solver.root_move_allowed = options.root_move_allowed;
        solver.root_move_mask_enabled = options.root_move_mask_enabled;
        solver.symmetry_transpositions = options.symmetry_transpositions;
        solver.full_symmetry_transpositions = options.full_symmetry_transpositions;
        solver.compact_transpositions = options.compact_transpositions;
        solver.upper_bound_proof_strategy = options.upper_bound_proof_strategy;
#ifdef RUBIK_WITH_NISSY_BRIDGE
        if (options.nissy_heuristic) {
            char error_buffer[512] = {0};
            if (!nissy_bridge_init(options.nissy_data_dir.c_str(), options.threads, error_buffer, sizeof(error_buffer))) {
                throw std::runtime_error(std::string("failed to initialize Nissy heuristic bridge: ") + error_buffer);
            }
            if (!options.nissy_sequence.empty()) {
                options.state.nissy = nissy_bridge_from_sequence(options.nissy_sequence.c_str());
                solver.nissy_axis_transforms = true;
            } else {
                options.state.nissy = nissy_bridge_from_arrays(
                    options.state.cp.data(),
                    options.state.co.data(),
                    options.state.ep.data(),
                    options.state.eo.data()
                );
                solver.nissy_axis_transforms = options.nissy_axis_transforms;
            }
            options.state.has_nissy = true;
        }
#else
        if (options.nissy_heuristic) {
            throw std::runtime_error("binary was not compiled with the Nissy heuristic bridge");
        }
#endif
        if (!options.upper_solution.empty()) {
            solver.upper_bound_solution_length = static_cast<int>(options.upper_solution.size());
            solver.upper_solution_verified = verify_upper_solution(solver, options.state, options.upper_solution);
            if (!solver.upper_solution_verified) {
                throw std::runtime_error("provided upper solution does not solve the input state");
            }
        }
        load_corner_pdb(solver, options.corner_pdb_path);
        for (const auto& path : options.edge_pdb_paths) {
            load_edge_pdb(solver, path, false);
        }
        for (const auto& path : options.additive_edge_pdb_paths) {
            load_edge_pdb(solver, path, true);
        }
        if (options.emit_edge_coords) {
            // Debug cross-check hook: emit the coordinate and distance each loaded
            // edge PDB assigns to the input state. A pytest compares these native
            // coordinates against the validated Python encoder to prove the
            // native 6- and 7-edge ranking is identical (guards admissibility).
            std::cout << "{\n  \"corner_coord\": " << corner_coord(options.state)
                      << ",\n  \"corner_distance\": "
                      << static_cast<int>(solver.corner_distances[corner_coord(options.state)])
                      << ",\n  \"edge_pdbs\": [";
            for (std::size_t i = 0; i < solver.edge_pdbs.size(); ++i) {
                const auto& pdb = solver.edge_pdbs[i];
                const std::uint32_t coord = edge_subset_coord(options.state, pdb);
                std::cout << (i ? ", " : "") << "{\"subset_size\": " << pdb.subset_size
                          << ", \"coord\": " << coord
                          << ", \"distance\": " << static_cast<int>(pdb.distances[coord]) << "}";
            }
            std::cout << "]\n}\n";
            return 0;
        }
        int bound = heuristic(solver, options.state);
        solver.lower_bound = bound;
        if (solver.upper_solution_verified && bound >= static_cast<int>(options.upper_solution.size())) {
            solver.solution = options.upper_solution;
            solver.exact_certified_by_upper_bound = true;
            print_solution_json(
                "exact",
                solver,
                begin,
                static_cast<int>(options.upper_solution.size()),
                options.threads,
                options.split_depth
            );
            return 0;
        }
        if (
            solver.upper_solution_verified &&
            solver.upper_bound_proof_strategy == UpperBoundProofStrategy::SingleBound &&
            static_cast<int>(options.upper_solution.size()) > 0 &&
            static_cast<int>(options.upper_solution.size()) - 1 <= options.max_depth
        ) {
            const int proof_bound = static_cast<int>(options.upper_solution.size()) - 1;
            solver.upper_bound_proof_search_bound = proof_bound;
            solver.upper_bound_proof_active = true;
            solver.upper_bound_proof_exhaustive = false;
            reset_solver_transpositions(solver);
            const int outcome = parallel_search_bound(
                solver,
                options.state,
                proof_bound,
                bound,
                options.threads,
                options.split_depth
            );
            solver.upper_bound_proof_active = false;
            if (outcome == kTimeout) {
                print_solution_json("timeout", solver, begin, proof_bound, options.threads, options.split_depth);
                return 0;
            }
            if (outcome == kNodeLimit) {
                print_solution_json("timeout", solver, begin, proof_bound, options.threads, options.split_depth);
                return 0;
            }
            solver.upper_bound_proof_exhaustive = true;
            solver.exact_certified_by_upper_bound = true;
            if (solver.solution.empty()) {
                solver.solution = options.upper_solution;
                print_solution_json(
                    "exact",
                    solver,
                    begin,
                    static_cast<int>(options.upper_solution.size()),
                    options.threads,
                    options.split_depth
                );
                return 0;
            }
            print_solution_json(
                "exact",
                solver,
                begin,
                static_cast<int>(solver.solution.size()),
                options.threads,
                options.split_depth
            );
            return 0;
        }
        if (bound > options.max_depth) {
            print_solution_json("lower_bound", solver, begin, bound, options.threads, options.split_depth);
            return 0;
        }
        while (bound <= options.max_depth) {
            reset_solver_transpositions(solver);
            const int outcome = parallel_search_bound(
                solver,
                options.state,
                bound,
                bound,
                options.threads,
                options.split_depth
            );
            if (outcome == kFound) {
                print_solution_json("exact", solver, begin, bound, options.threads, options.split_depth);
                return 0;
            }
            if (outcome == kTimeout) {
                print_solution_json("timeout", solver, begin, bound, options.threads, options.split_depth);
                return 0;
            }
            if (outcome == kNodeLimit) {
                print_solution_json("timeout", solver, begin, bound, options.threads, options.split_depth);
                return 0;
            }
            if (solver.upper_solution_verified && outcome >= static_cast<int>(options.upper_solution.size())) {
                solver.solution = options.upper_solution;
                solver.exact_certified_by_upper_bound = true;
                print_solution_json(
                    "exact",
                    solver,
                    begin,
                    static_cast<int>(options.upper_solution.size()),
                    options.threads,
                    options.split_depth
                );
                return 0;
            }
            if (outcome == std::numeric_limits<int>::max()) {
                break;
            }
            bound = outcome;
        }
        print_solution_json("lower_bound", solver, begin, bound, options.threads, options.split_depth);
        return 0;
    } catch (const std::exception& exc) {
        std::cout << "{\n";
        std::cout << "  \"schema_version\": 1,\n";
        std::cout << "  \"solver_name\": \"korf_native_optimal\",\n";
        std::cout << "  \"status\": \"failed\",\n";
        std::cout << "  \"error\": \"" << exc.what() << "\"\n";
        std::cout << "}\n";
        return 1;
    }
}
