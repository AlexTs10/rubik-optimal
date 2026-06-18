// Native Kociemba phase-2 optimal-search probe.
//
// This is a measurement/bridge tool for the own-code two-phase route.  It
// solves only states already in Kociemba's G1 subgroup using the phase-2 move
// set {U,D quarter/half turns and R/L/F/B half turns}.  It does not use H48,
// Nissy, or any third-party oracle.

#include <algorithm>
#include <atomic>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <fstream>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace {

constexpr std::uint32_t kPermutation8Count = 40320;
constexpr std::uint32_t kSlicePermutationCount = 24;
constexpr std::uint32_t kCornerOrientationCount = 2187;
constexpr std::uint32_t kEdgeOrientationCount = 2048;
constexpr std::uint32_t kUDSliceCombinationCount = 495;
constexpr std::uint32_t kLabeledUDSliceCount = kUDSliceCombinationCount * kSlicePermutationCount;
constexpr std::uint32_t kLabeledUDEdgeCount = kUDSliceCombinationCount * kPermutation8Count;
constexpr std::uint32_t kCPSliceTargetCount = kPermutation8Count * kLabeledUDSliceCount;
constexpr std::uint32_t kPhase1FullCount =
    kCornerOrientationCount * kEdgeOrientationCount * kUDSliceCombinationCount;
constexpr std::uint32_t kUDSliceSolvedCoord = 494;

// Kociemba/Cube-Explorer FlipUDSlice 16-symmetry phase-1 reduction.
// The raw FlipUDSlice coordinate (EO x UD-slice combination) has
// 2048 * 495 = 1,013,760 values; quotienting by the 16 whole-cube symmetries
// that fix the UD axis yields 64,430 equivalence classes.  Combined with the
// corner-orientation (twist) coordinate this gives Kociemba's compressed
// phase-1 pruning table of 64,430 * 2,187 = 140,908,410 entries (max depth 12).
constexpr std::uint32_t kSymCount = 16;
constexpr std::uint32_t kFlipUDSliceCount =
    kEdgeOrientationCount * kUDSliceCombinationCount;
constexpr std::uint32_t kFlipUDSliceClassCount = 64430;
constexpr std::uint32_t kSymPhase1Count =
    kFlipUDSliceClassCount * kCornerOrientationCount;
constexpr int kFound = -1;
constexpr int kTimeout = -2;
constexpr int kNodeLimit = -3;

constexpr std::array<std::uint32_t, 13> kFactorial = {
    1, 1, 2, 6, 24, 120, 720, 5040, 40320, 362880, 3628800, 39916800, 479001600,
};

constexpr std::array<const char*, 18> kMoveNames = {
    "U", "U'", "U2", "R", "R'", "R2", "F", "F'", "F2",
    "D", "D'", "D2", "L", "L'", "L2", "B", "B'", "B2",
};

constexpr std::array<int, 10> kPhase2MoveIndices = {
    0, 1, 2, 9, 10, 11, 5, 14, 8, 17,
};

constexpr std::array<const char*, 10> kPhase2MoveNames = {
    "U", "U'", "U2", "D", "D'", "D2", "R2", "L2", "F2", "B2",
};

struct State {
    std::array<std::uint8_t, 8> cp;
    std::array<std::uint8_t, 8> co;
    std::array<std::uint8_t, 12> ep;
    std::array<std::uint8_t, 12> eo;
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

struct Phase2Coord {
    std::uint16_t cp = 0;
    std::uint16_t ud = 0;
    std::uint8_t slice = 0;
};

struct Phase1Coord {
    std::uint16_t cp = 0;
    std::uint16_t slice_perm = 0;
    std::uint32_t ud_edges = 0;
    std::uint16_t co = 0;
    std::uint16_t eo = 0;
    std::uint16_t slice = 0;
    // Mike Reid three-axis bound: phase-1 (CO/EO/UD-slice) coordinates of the
    // state conjugated onto the RL and FB axes, maintained incrementally via the
    // move-conjugation maps.  Only used when three-axis pruning is enabled.
    std::uint16_t co_rl = 0;
    std::uint16_t eo_rl = 0;
    std::uint16_t slice_rl = 0;
    std::uint16_t co_fb = 0;
    std::uint16_t eo_fb = 0;
    std::uint16_t slice_fb = 0;
};

struct Phase2Tables {
    std::vector<std::uint16_t> cp_move;
    std::vector<std::uint16_t> ud_move;
    std::vector<std::uint8_t> slice_move;
    std::vector<std::uint8_t> cp_dist;
    std::vector<std::uint8_t> ud_dist;
    std::vector<std::uint8_t> slice_dist;
    std::vector<std::uint8_t> cp_slice_dist;
    std::vector<std::uint8_t> ud_slice_dist;
};

struct Phase1Tables {
    std::vector<std::uint16_t> cp_move;
    std::vector<std::uint16_t> slice_perm_move;
    std::vector<std::uint32_t> ud_edge_move;
    std::vector<std::uint16_t> co_move;
    std::vector<std::uint16_t> eo_move;
    std::vector<std::uint16_t> slice_move;
    std::vector<std::uint8_t> co_dist;
    std::vector<std::uint8_t> eo_dist;
    std::vector<std::uint8_t> slice_dist;
    std::vector<std::uint8_t> co_eo_dist;
    std::vector<std::uint8_t> co_slice_dist;
    std::vector<std::uint8_t> eo_slice_dist;
    std::vector<std::uint8_t> full_dist;
    std::vector<std::uint8_t> cp_target_dist_by_cap;
    std::vector<std::uint8_t> slice_perm_target_dist_by_cap;
    std::vector<std::uint8_t> cp_slice_target_dist;
    std::vector<std::uint8_t> ud_edge_target_dist;
    // FlipUDSlice 16-symmetry phase-1 reduction (generated by
    // scripts/generate_phase1_sym_tables.py) + compressed pruning table.
    std::vector<std::uint16_t> sym_twist;           // kSymCount * kCornerOrientationCount
    std::array<std::uint8_t, kSymCount> inv_sym{};  // inverse symmetry index (reference)
    std::vector<std::uint16_t> flipudslice_classidx;  // kFlipUDSliceCount -> class index
    std::vector<std::uint8_t> flipudslice_sym;        // kFlipUDSliceCount -> sym mapping raw -> rep
    std::vector<std::uint32_t> classidx_to_rep;       // kFlipUDSliceClassCount -> rep raw coord
    std::vector<std::uint16_t> class_stab_mask;       // kFlipUDSliceClassCount -> stabilizer bitmask
    std::vector<std::uint8_t> sym_dist;               // kSymPhase1Count compressed pruning table
    int sym_dist_depth = -1;
    int sym_dist_max_distance = -1;
    bool sym_dist_complete = false;
    int cp_target_max_cap = 0;
    int slice_perm_target_max_cap = 0;
    int cp_slice_target_cap = -1;
    int cp_slice_target_depth = -1;
    int cp_slice_target_max_distance = -1;
    bool cp_slice_target_complete = false;
    int ud_edge_target_cap = -1;
    int ud_edge_target_depth = -1;
    int ud_edge_target_max_distance = -1;
    bool ud_edge_target_complete = false;
    int full_dist_depth = -1;
    int full_dist_max_distance = -1;
    bool full_dist_complete = false;
};

struct Options {
    State state;
    std::string mode = "phase2";
    int max_depth = 14;
    int phase1_start_depth = 0;
    int phase1_max_depth = 20;
    int target_bound = 20;
    double timeout_seconds = 30.0;
    std::uint64_t node_limit = 0;
    std::uint64_t phase1_node_limit = 0;
    std::uint64_t phase2_node_limit = 0;
    bool root_move_mask_enabled = false;
    bool handoff_dedup_enabled = true;
    bool cp_target_pruning_enabled = true;
    bool phase1_full_pruning_enabled = false;
    int phase1_full_pruning_min_depth = 0;
    int phase1_full_pruning_max_depth = 12;
    std::string phase1_full_pruning_cache_path;
    bool sym_phase1_pruning_enabled = false;
    int sym_phase1_pruning_max_depth = 12;
    std::string sym_tables_path = "data/generated/phase1_sym_tables.bin";
    std::string sym_phase1_cache_path;
    std::string raw_phase1_table_path;
    bool three_axis_pruning_enabled = false;
    std::array<std::uint8_t, 18> conj_rl{};  // real move -> RL-frame move index
    std::array<std::uint8_t, 18> conj_fb{};  // real move -> FB-frame move index
    State rl_state;  // root state conjugated onto the RL axis
    State fb_state;  // root state conjugated onto the FB axis
    bool cp_slice_target_pruning_enabled = false;
    int cp_slice_target_min_depth = 0;
    std::string cp_slice_target_cache_path;
    bool ud_edge_target_pruning_enabled = false;
    int ud_edge_target_min_depth = 0;
    std::string ud_edge_target_cache_path;
    int threads = 1;
    int split_depth = 0;
    std::array<bool, 18> root_move_allowed{};
};

struct Solver {
    const Phase2Tables* tables = nullptr;
    std::chrono::steady_clock::time_point deadline;
    std::uint64_t node_limit = 0;
    std::uint64_t expanded = 0;
    std::uint64_t generated = 0;
    bool timed_out = false;
    bool node_limited = false;
    std::vector<int> path;
    std::vector<int> solution;
};

struct TwoPhaseStats {
    std::uint64_t phase1_expanded = 0;
    std::uint64_t phase1_generated = 0;
    std::uint64_t phase1_cp_target_prunes = 0;
    std::uint64_t phase1_slice_perm_target_prunes = 0;
    std::uint64_t phase1_three_axis_prunes = 0;
    std::uint64_t phase1_cp_slice_target_prunes = 0;
    std::uint64_t phase1_cp_slice_target_table_builds = 0;
    std::uint64_t phase1_cp_slice_target_last_targets = 0;
    std::uint64_t phase1_cp_slice_target_last_states = 0;
    double phase1_cp_slice_target_build_seconds = 0.0;
    int phase1_cp_slice_target_last_cap = -1;
    int phase1_cp_slice_target_last_depth = -1;
    int phase1_cp_slice_target_max_distance = -1;
    bool phase1_cp_slice_target_complete = false;
    bool phase1_cp_slice_target_cache_hit = false;
    double phase1_cp_slice_target_load_seconds = 0.0;
    std::uint64_t phase1_ud_edge_target_prunes = 0;
    std::uint64_t phase1_ud_edge_target_table_builds = 0;
    std::uint64_t phase1_ud_edge_target_last_targets = 0;
    std::uint64_t phase1_ud_edge_target_last_states = 0;
    double phase1_ud_edge_target_build_seconds = 0.0;
    int phase1_ud_edge_target_last_cap = -1;
    int phase1_ud_edge_target_last_depth = -1;
    int phase1_ud_edge_target_max_distance = -1;
    bool phase1_ud_edge_target_complete = false;
    bool phase1_ud_edge_target_cache_hit = false;
    double phase1_ud_edge_target_load_seconds = 0.0;
    std::uint64_t phase1_full_pruning_table_builds = 0;
    std::uint64_t phase1_full_pruning_last_states = 0;
    double phase1_full_pruning_build_seconds = 0.0;
    int phase1_full_pruning_last_depth = -1;
    int phase1_full_pruning_max_distance = -1;
    bool phase1_full_pruning_complete = false;
    bool phase1_full_pruning_cache_hit = false;
    double phase1_full_pruning_load_seconds = 0.0;
    std::uint64_t sym_phase1_table_builds = 0;
    std::uint64_t sym_phase1_last_states = 0;
    double sym_phase1_build_seconds = 0.0;
    double sym_phase1_load_seconds = 0.0;
    int sym_phase1_last_depth = -1;
    int sym_phase1_max_distance = -1;
    bool sym_phase1_complete = false;
    bool sym_phase1_cache_hit = false;
    std::uint64_t handoff_count = 0;
    std::uint64_t duplicate_handoff_count = 0;
    std::uint64_t phase2_calls = 0;
    std::uint64_t phase2_expanded = 0;
    std::uint64_t phase2_generated = 0;
    std::uint64_t phase2_lower_bound_rows = 0;
    std::uint64_t phase2_timeout_rows = 0;
    bool timed_out = false;
    bool node_limited = false;
    bool solution_found = false;
    int solution_phase1_length = -1;
    int solution_phase2_length = -1;
    int completed_phase1_depth = -1;
    int current_phase1_depth = 0;
    std::vector<int> phase1_path;
    std::vector<int> best_phase1_solution;
    std::vector<int> best_phase2_solution;
    std::unordered_map<std::uint64_t, int> seen_g1_depths;
};

struct Phase2SearchResult {
    std::string status;
    std::vector<int> solution;
    std::uint64_t expanded = 0;
    std::uint64_t generated = 0;
    int initial_lower_bound = 0;
    int final_bound = 0;
};

struct Phase1Task {
    State state;
    Phase1Coord coord;
    int g = 0;
    int previous_face = -1;
    std::vector<int> path;
};

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

const auto kMoves = build_moves();

inline int popcount32(std::uint32_t value) {
    return __builtin_popcount(value);
}

template <std::size_t N>
std::uint32_t rank_permutation(const std::array<std::uint8_t, N>& values) {
    std::uint32_t rank = 0;
    std::uint32_t used_mask = 0;
    for (std::uint32_t index = 0; index < N; ++index) {
        const std::uint32_t value = values[index];
        const std::uint32_t lower_mask = value == 0 ? 0 : ((1U << value) - 1U);
        const std::uint32_t digit = value - static_cast<std::uint32_t>(popcount32(used_mask & lower_mask));
        rank += digit * kFactorial[N - 1 - index];
        used_mask |= 1U << value;
    }
    return rank;
}

template <std::size_t N>
std::array<std::uint8_t, N> unrank_permutation(std::uint32_t rank) {
    std::array<std::uint8_t, N> values{};
    std::array<std::uint8_t, N> elements{};
    for (std::uint32_t i = 0; i < N; ++i) {
        elements[i] = static_cast<std::uint8_t>(i);
    }
    int remaining = static_cast<int>(N);
    for (std::uint32_t index = 0; index < N; ++index) {
        const std::uint32_t fact = kFactorial[N - 1 - index];
        const std::uint32_t digit = rank / fact;
        rank %= fact;
        values[index] = elements[digit];
        for (int j = static_cast<int>(digit); j + 1 < remaining; ++j) {
            elements[j] = elements[j + 1];
        }
        --remaining;
    }
    return values;
}

std::uint16_t encode_cp(const State& state) {
    return static_cast<std::uint16_t>(rank_permutation<8>(state.cp));
}

std::uint16_t encode_ud_edges(const State& state) {
    std::array<std::uint8_t, 8> values{};
    std::array<bool, 8> seen{};
    for (std::uint32_t pos = 0; pos < 8; ++pos) {
        const std::uint8_t edge = state.ep[pos];
        if (edge >= 8 || seen[edge]) {
            throw std::runtime_error("phase-2 UD edge coordinate expected edges 0..7 in positions 0..7");
        }
        seen[edge] = true;
        values[pos] = edge;
    }
    return static_cast<std::uint16_t>(rank_permutation<8>(values));
}

std::uint8_t encode_slice_edges(const State& state) {
    std::array<std::uint8_t, 4> values{};
    std::array<bool, 4> seen{};
    for (std::uint32_t pos = 0; pos < 4; ++pos) {
        const std::uint8_t edge = state.ep[8 + pos];
        if (edge < 8 || edge >= 12 || seen[edge - 8]) {
            throw std::runtime_error("phase-2 slice coordinate expected edges 8..11 in positions 8..11");
        }
        seen[edge - 8] = true;
        values[pos] = static_cast<std::uint8_t>(edge - 8);
    }
    return static_cast<std::uint8_t>(rank_permutation<4>(values));
}

Phase2Coord encode_phase2(const State& state) {
    for (const auto value : state.co) {
        if (value != 0) {
            throw std::runtime_error("phase-2 input has nonzero corner orientation");
        }
    }
    for (const auto value : state.eo) {
        if (value != 0) {
            throw std::runtime_error("phase-2 input has nonzero edge orientation");
        }
    }
    return {encode_cp(state), encode_ud_edges(state), encode_slice_edges(state)};
}

std::uint16_t encode_corner_orientation(const State& state) {
    std::uint32_t coord = 0;
    for (std::uint32_t index = 0; index < 7; ++index) {
        if (state.co[index] > 2) {
            throw std::runtime_error("corner orientation outside 0..2");
        }
        coord = coord * 3 + state.co[index];
    }
    return static_cast<std::uint16_t>(coord);
}

std::uint16_t encode_edge_orientation(const State& state) {
    std::uint32_t coord = 0;
    for (std::uint32_t index = 0; index < 11; ++index) {
        if (state.eo[index] > 1) {
            throw std::runtime_error("edge orientation outside 0..1");
        }
        coord = (coord << 1) | state.eo[index];
    }
    return static_cast<std::uint16_t>(coord);
}

std::array<std::uint16_t, 4096> build_ud_slice_mask_to_coord() {
    std::array<std::uint16_t, 4096> result{};
    result.fill(std::numeric_limits<std::uint16_t>::max());
    std::uint16_t coord = 0;
    for (std::uint32_t a = 0; a < 9; ++a) {
        for (std::uint32_t b = a + 1; b < 10; ++b) {
            for (std::uint32_t c = b + 1; c < 11; ++c) {
                for (std::uint32_t d = c + 1; d < 12; ++d) {
                    const std::uint32_t mask = (1U << a) | (1U << b) | (1U << c) | (1U << d);
                    result[mask] = coord++;
                }
            }
        }
    }
    return result;
}

const auto kUDSliceMaskToCoord = build_ud_slice_mask_to_coord();

std::uint16_t encode_ud_slice_combination(const State& state) {
    std::uint32_t mask = 0;
    for (std::uint32_t pos = 0; pos < 12; ++pos) {
        if (state.ep[pos] >= 8 && state.ep[pos] <= 11) {
            mask |= 1U << pos;
        }
    }
    const std::uint16_t coord = kUDSliceMaskToCoord[mask];
    if (coord == std::numeric_limits<std::uint16_t>::max()) {
        throw std::runtime_error("UD-slice coordinate expected exactly four slice edges");
    }
    return coord;
}

std::uint16_t encode_labeled_ud_slice(const State& state) {
    std::uint32_t mask = 0;
    std::array<std::uint8_t, 4> values{};
    std::uint32_t count = 0;
    for (std::uint32_t pos = 0; pos < 12; ++pos) {
        if (state.ep[pos] >= 8 && state.ep[pos] <= 11) {
            mask |= 1U << pos;
            values[count++] = static_cast<std::uint8_t>(state.ep[pos] - 8);
        }
    }
    if (count != 4) {
        throw std::runtime_error("labeled UD-slice coordinate expected exactly four slice edges");
    }
    const std::uint16_t combination = kUDSliceMaskToCoord[mask];
    if (combination == std::numeric_limits<std::uint16_t>::max()) {
        throw std::runtime_error("labeled UD-slice combination outside domain");
    }
    return static_cast<std::uint16_t>(
        combination * kSlicePermutationCount + rank_permutation<4>(values)
    );
}

std::uint32_t encode_labeled_ud_edges(const State& state) {
    std::uint32_t slice_mask = 0;
    std::array<std::uint8_t, 8> values{};
    std::uint32_t count = 0;
    for (std::uint32_t pos = 0; pos < 12; ++pos) {
        if (state.ep[pos] < 8) {
            values[count++] = state.ep[pos];
        } else if (state.ep[pos] <= 11) {
            slice_mask |= 1U << pos;
        } else {
            throw std::runtime_error("edge permutation value outside 0..11");
        }
    }
    if (count != 8) {
        throw std::runtime_error("labeled UD-edge coordinate expected exactly eight UD edges");
    }
    const std::uint16_t combination = kUDSliceMaskToCoord[slice_mask];
    if (combination == std::numeric_limits<std::uint16_t>::max()) {
        throw std::runtime_error("labeled UD-edge combination outside domain");
    }
    return combination * kPermutation8Count + rank_permutation<8>(values);
}

Phase1Coord encode_phase1(const State& state) {
    return {
        encode_cp(state),
        encode_labeled_ud_slice(state),
        encode_labeled_ud_edges(state),
        encode_corner_orientation(state),
        encode_edge_orientation(state),
        encode_ud_slice_combination(state),
    };
}

State decode_corner_orientation_coord(std::uint32_t coord) {
    State state = solved_state();
    std::uint32_t remaining = coord;
    int sum = 0;
    for (int index = 6; index >= 0; --index) {
        state.co[index] = static_cast<std::uint8_t>(remaining % 3U);
        sum += state.co[index];
        remaining /= 3U;
    }
    state.co[7] = static_cast<std::uint8_t>((3 - (sum % 3)) % 3);
    return state;
}

State decode_edge_orientation_coord(std::uint32_t coord) {
    State state = solved_state();
    int sum = 0;
    for (int index = 10; index >= 0; --index) {
        state.eo[index] = static_cast<std::uint8_t>(coord & 1U);
        sum += state.eo[index];
        coord >>= 1U;
    }
    state.eo[11] = static_cast<std::uint8_t>(sum & 1);
    return state;
}

State decode_ud_slice_combination_coord(std::uint32_t coord) {
    State state = solved_state();
    std::uint32_t current = 0;
    std::array<bool, 12> selected{};
    bool found = false;
    for (std::uint32_t a = 0; a < 9 && !found; ++a) {
        for (std::uint32_t b = a + 1; b < 10 && !found; ++b) {
            for (std::uint32_t c = b + 1; c < 11 && !found; ++c) {
                for (std::uint32_t d = c + 1; d < 12; ++d) {
                    if (current == coord) {
                        selected[a] = true;
                        selected[b] = true;
                        selected[c] = true;
                        selected[d] = true;
                        found = true;
                        break;
                    }
                    ++current;
                }
            }
        }
    }
    if (!found) {
        throw std::runtime_error("UD-slice combination coordinate outside domain");
    }
    std::uint8_t slice_edge = 8;
    std::uint8_t other_edge = 0;
    for (std::uint32_t pos = 0; pos < 12; ++pos) {
        if (selected[pos]) {
            state.ep[pos] = slice_edge++;
        } else {
            state.ep[pos] = other_edge++;
        }
    }
    return state;
}

std::array<std::uint8_t, 4> ud_slice_positions_from_coord(std::uint32_t coord) {
    std::uint32_t current = 0;
    for (std::uint32_t a = 0; a < 9; ++a) {
        for (std::uint32_t b = a + 1; b < 10; ++b) {
            for (std::uint32_t c = b + 1; c < 11; ++c) {
                for (std::uint32_t d = c + 1; d < 12; ++d) {
                    if (current == coord) {
                        return {
                            static_cast<std::uint8_t>(a),
                            static_cast<std::uint8_t>(b),
                            static_cast<std::uint8_t>(c),
                            static_cast<std::uint8_t>(d),
                        };
                    }
                    ++current;
                }
            }
        }
    }
    throw std::runtime_error("UD-slice combination coordinate outside domain");
}

State decode_cp_coord(std::uint32_t coord) {
    State state = solved_state();
    state.cp = unrank_permutation<8>(coord);
    return state;
}

State decode_ud_coord(std::uint32_t coord) {
    State state = solved_state();
    const auto values = unrank_permutation<8>(coord);
    for (std::uint32_t pos = 0; pos < 8; ++pos) {
        state.ep[pos] = values[pos];
    }
    for (std::uint32_t pos = 8; pos < 12; ++pos) {
        state.ep[pos] = static_cast<std::uint8_t>(pos);
    }
    return state;
}

State decode_slice_coord(std::uint32_t coord) {
    State state = solved_state();
    const auto values = unrank_permutation<4>(coord);
    for (std::uint32_t pos = 0; pos < 4; ++pos) {
        state.ep[8 + pos] = static_cast<std::uint8_t>(8 + values[pos]);
    }
    return state;
}

State decode_labeled_ud_slice_coord(std::uint32_t coord) {
    State state = solved_state();
    const std::uint32_t combination = coord / kSlicePermutationCount;
    const std::uint32_t permutation = coord % kSlicePermutationCount;
    const auto positions = ud_slice_positions_from_coord(combination);
    const auto values = unrank_permutation<4>(permutation);
    std::array<bool, 12> selected{};
    for (std::uint32_t index = 0; index < 4; ++index) {
        selected[positions[index]] = true;
        state.ep[positions[index]] = static_cast<std::uint8_t>(8 + values[index]);
    }
    std::uint8_t other_edge = 0;
    for (std::uint32_t pos = 0; pos < 12; ++pos) {
        if (!selected[pos]) {
            state.ep[pos] = other_edge++;
        }
    }
    return state;
}

State decode_labeled_ud_edges_coord(std::uint32_t coord) {
    State state = solved_state();
    const std::uint32_t combination = coord / kPermutation8Count;
    const std::uint32_t permutation = coord % kPermutation8Count;
    const auto slice_positions = ud_slice_positions_from_coord(combination);
    std::array<bool, 12> slice_selected{};
    for (const std::uint8_t pos : slice_positions) {
        slice_selected[pos] = true;
    }
    const auto values = unrank_permutation<8>(permutation);
    std::uint32_t ud_index = 0;
    std::uint8_t slice_edge = 8;
    for (std::uint32_t pos = 0; pos < 12; ++pos) {
        if (slice_selected[pos]) {
            state.ep[pos] = slice_edge++;
        } else {
            state.ep[pos] = values[ud_index++];
        }
    }
    return state;
}

template <typename ValueT, typename CoordFn, typename DecodeFn>
std::vector<ValueT> build_move_table(std::uint32_t domain_size, CoordFn coord_fn, DecodeFn decode_fn) {
    std::vector<ValueT> table(static_cast<std::size_t>(domain_size) * kPhase2MoveIndices.size());
    for (std::uint32_t coord = 0; coord < domain_size; ++coord) {
        const State state = decode_fn(coord);
        for (std::uint32_t move = 0; move < kPhase2MoveIndices.size(); ++move) {
            const State child = apply_base(state, kMoves[kPhase2MoveIndices[move]]);
            table[coord * kPhase2MoveIndices.size() + move] = static_cast<ValueT>(coord_fn(child));
        }
    }
    return table;
}

template <typename ValueT, typename CoordFn, typename DecodeFn>
std::vector<ValueT> build_all_move_table(std::uint32_t domain_size, CoordFn coord_fn, DecodeFn decode_fn) {
    std::vector<ValueT> table(static_cast<std::size_t>(domain_size) * kMoveNames.size());
    for (std::uint32_t coord = 0; coord < domain_size; ++coord) {
        const State state = decode_fn(coord);
        for (std::uint32_t move = 0; move < kMoveNames.size(); ++move) {
            const State child = apply_base(state, kMoves[move]);
            table[coord * kMoveNames.size() + move] = static_cast<ValueT>(coord_fn(child));
        }
    }
    return table;
}

template <typename ValueT>
std::vector<std::uint8_t> build_pruning_table(const std::vector<ValueT>& move_table, std::uint32_t domain_size) {
    constexpr std::uint8_t kUnvisited = 0xff;
    std::vector<std::uint8_t> dist(domain_size, kUnvisited);
    std::deque<std::uint32_t> queue;
    dist[0] = 0;
    queue.push_back(0);
    while (!queue.empty()) {
        const std::uint32_t coord = queue.front();
        queue.pop_front();
        const std::uint8_t next_depth = static_cast<std::uint8_t>(dist[coord] + 1);
        for (std::uint32_t move = 0; move < kPhase2MoveIndices.size(); ++move) {
            const std::uint32_t child = move_table[coord * kPhase2MoveIndices.size() + move];
            if (dist[child] == kUnvisited) {
                dist[child] = next_depth;
                queue.push_back(child);
            }
        }
    }
    return dist;
}

template <typename ValueT>
std::vector<std::uint8_t> build_pruning_table_all_moves(
    const std::vector<ValueT>& move_table,
    std::uint32_t domain_size,
    std::uint32_t solved_coord
) {
    constexpr std::uint8_t kUnvisited = 0xff;
    std::vector<std::uint8_t> dist(domain_size, kUnvisited);
    std::deque<std::uint32_t> queue;
    dist[solved_coord] = 0;
    queue.push_back(solved_coord);
    while (!queue.empty()) {
        const std::uint32_t coord = queue.front();
        queue.pop_front();
        const std::uint8_t next_depth = static_cast<std::uint8_t>(dist[coord] + 1);
        for (std::uint32_t move = 0; move < kMoveNames.size(); ++move) {
            const std::uint32_t child = move_table[coord * kMoveNames.size() + move];
            if (dist[child] == kUnvisited) {
                dist[child] = next_depth;
                queue.push_back(child);
            }
        }
    }
    return dist;
}

template <typename ValueT>
std::vector<std::uint8_t> build_multisource_pruning_table(
    const std::vector<ValueT>& move_table,
    std::uint32_t domain_size,
    const std::vector<std::uint32_t>& solved_coords,
    std::uint32_t move_count
) {
    constexpr std::uint8_t kUnvisited = 0xff;
    std::vector<std::uint8_t> dist(domain_size, kUnvisited);
    std::deque<std::uint32_t> queue;
    for (const std::uint32_t coord : solved_coords) {
        if (coord >= domain_size) {
            throw std::runtime_error("multisource pruning coordinate outside domain");
        }
        if (dist[coord] == kUnvisited) {
            dist[coord] = 0;
            queue.push_back(coord);
        }
    }
    while (!queue.empty()) {
        const std::uint32_t coord = queue.front();
        queue.pop_front();
        const std::uint8_t next_depth = static_cast<std::uint8_t>(dist[coord] + 1);
        for (std::uint32_t move = 0; move < move_count; ++move) {
            const std::uint32_t child = move_table[coord * move_count + move];
            if (dist[child] == kUnvisited) {
                dist[child] = next_depth;
                queue.push_back(child);
            }
        }
    }
    return dist;
}

template <typename ValueA, typename ValueB>
std::vector<std::uint8_t> build_pair_pruning_table(
    const std::vector<ValueA>& move_a,
    std::uint32_t domain_a,
    std::uint32_t solved_a,
    const std::vector<ValueB>& move_b,
    std::uint32_t domain_b,
    std::uint32_t solved_b,
    std::uint32_t move_count
) {
    constexpr std::uint8_t kUnvisited = 0xff;
    const std::uint32_t domain_size = domain_a * domain_b;
    std::vector<std::uint8_t> dist(domain_size, kUnvisited);
    std::deque<std::uint32_t> queue;
    const std::uint32_t solved = solved_a * domain_b + solved_b;
    dist[solved] = 0;
    queue.push_back(solved);
    while (!queue.empty()) {
        const std::uint32_t coord = queue.front();
        queue.pop_front();
        const std::uint32_t a = coord / domain_b;
        const std::uint32_t b = coord % domain_b;
        const std::uint8_t next_depth = static_cast<std::uint8_t>(dist[coord] + 1);
        for (std::uint32_t move = 0; move < move_count; ++move) {
            const std::uint32_t child_a = move_a[a * move_count + move];
            const std::uint32_t child_b = move_b[b * move_count + move];
            const std::uint32_t child = child_a * domain_b + child_b;
            if (dist[child] == kUnvisited) {
                dist[child] = next_depth;
                queue.push_back(child);
            }
        }
    }
    return dist;
}

std::vector<std::uint8_t> build_cp_target_dist_by_cap(
    const std::vector<std::uint16_t>& phase1_cp_move,
    const std::vector<std::uint16_t>& phase2_cp_move,
    int max_cap
) {
    std::vector<std::uint8_t> result(
        static_cast<std::size_t>(max_cap + 1) * kPermutation8Count,
        0xff
    );
    std::vector<std::uint8_t> phase2_cp_dist = build_pruning_table(
        phase2_cp_move,
        kPermutation8Count
    );
    for (int cap = 0; cap <= max_cap; ++cap) {
        std::vector<std::uint32_t> targets;
        targets.reserve(kPermutation8Count);
        for (std::uint32_t coord = 0; coord < kPermutation8Count; ++coord) {
            if (phase2_cp_dist[coord] <= cap) {
                targets.push_back(coord);
            }
        }
        std::vector<std::uint8_t> dist = build_multisource_pruning_table(
            phase1_cp_move,
            kPermutation8Count,
            targets,
            static_cast<std::uint32_t>(kMoveNames.size())
        );
        std::copy(
            dist.begin(),
            dist.end(),
            result.begin() + static_cast<std::size_t>(cap) * kPermutation8Count
        );
    }
    return result;
}

std::vector<std::uint8_t> build_slice_perm_target_dist_by_cap(
    const std::vector<std::uint16_t>& phase1_slice_perm_move,
    const std::vector<std::uint8_t>& phase2_slice_dist,
    int max_cap
) {
    std::vector<std::uint8_t> result(
        static_cast<std::size_t>(max_cap + 1) * kLabeledUDSliceCount,
        0xff
    );
    for (int cap = 0; cap <= max_cap; ++cap) {
        std::vector<std::uint32_t> targets;
        targets.reserve(kSlicePermutationCount);
        for (std::uint32_t slice = 0; slice < kSlicePermutationCount; ++slice) {
            if (phase2_slice_dist[slice] <= cap) {
                targets.push_back(kUDSliceSolvedCoord * kSlicePermutationCount + slice);
            }
        }
        std::vector<std::uint8_t> dist = build_multisource_pruning_table(
            phase1_slice_perm_move,
            kLabeledUDSliceCount,
            targets,
            static_cast<std::uint32_t>(kMoveNames.size())
        );
        std::copy(
            dist.begin(),
            dist.end(),
            result.begin() + static_cast<std::size_t>(cap) * kLabeledUDSliceCount
        );
    }
    return result;
}

struct BoundedTargetTable {
    std::vector<std::uint8_t> dist;
    std::uint64_t target_count = 0;
    std::uint64_t visited_count = 0;
    double build_seconds = 0.0;
    bool cache_hit = false;
    double load_seconds = 0.0;
    int max_distance = -1;
    bool complete = false;
};

template <typename T>
void write_binary(std::ostream& stream, const T& value) {
    stream.write(reinterpret_cast<const char*>(&value), sizeof(T));
}

template <typename T>
bool read_binary(std::istream& stream, T& value) {
    stream.read(reinterpret_cast<char*>(&value), sizeof(T));
    return static_cast<bool>(stream);
}

void replace_all(std::string& text, const std::string& needle, const std::string& replacement) {
    std::size_t pos = 0;
    while ((pos = text.find(needle, pos)) != std::string::npos) {
        text.replace(pos, needle.size(), replacement);
        pos += replacement.size();
    }
}

std::string cp_slice_target_cache_path_for(
    const std::string& pattern,
    int suffix_cap,
    int max_depth
) {
    std::string path = pattern;
    replace_all(path, "{cap}", std::to_string(suffix_cap));
    replace_all(path, "{depth}", std::to_string(max_depth));
    return path;
}

std::string ud_edge_target_cache_path_for(
    const std::string& pattern,
    int suffix_cap,
    int max_depth
) {
    std::string path = pattern;
    replace_all(path, "{cap}", std::to_string(suffix_cap));
    replace_all(path, "{depth}", std::to_string(max_depth));
    return path;
}

std::string phase1_full_pruning_cache_path_for(
    const std::string& pattern,
    int max_depth
) {
    std::string path = pattern;
    replace_all(path, "{depth}", std::to_string(max_depth));
    return path;
}

std::uint32_t phase1_full_index(std::uint32_t co, std::uint32_t eo, std::uint32_t slice) {
    return (co * kEdgeOrientationCount + eo) * kUDSliceCombinationCount + slice;
}

bool load_bounded_cp_slice_target_dist(
    const std::string& path,
    int suffix_cap,
    int max_depth,
    BoundedTargetTable& table
) {
    if (path.empty()) {
        return false;
    }
    const auto begin = std::chrono::steady_clock::now();
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        return false;
    }
    std::array<char, 8> magic{};
    input.read(magic.data(), magic.size());
    const std::array<char, 8> expected_magic = {'C', 'P', 'S', 'L', 'T', 'G', 'T', '1'};
    if (magic != expected_magic) {
        return false;
    }
    std::uint32_t domain = 0;
    std::int32_t cap = 0;
    std::int32_t depth = 0;
    std::uint64_t target_count = 0;
    std::uint64_t visited_count = 0;
    if (
        !read_binary(input, domain)
        || !read_binary(input, cap)
        || !read_binary(input, depth)
        || !read_binary(input, target_count)
        || !read_binary(input, visited_count)
    ) {
        return false;
    }
    if (
        domain != kCPSliceTargetCount
        || cap != suffix_cap
        || depth < max_depth
    ) {
        return false;
    }
    table.dist.assign(kCPSliceTargetCount, 0xff);
    input.read(
        reinterpret_cast<char*>(table.dist.data()),
        static_cast<std::streamsize>(table.dist.size())
    );
    if (!input) {
        table.dist.clear();
        return false;
    }
    table.target_count = target_count;
    table.visited_count = visited_count;
    table.complete = visited_count == kCPSliceTargetCount;
    table.max_distance = -1;
    for (const std::uint8_t value : table.dist) {
        if (value != 0xff) {
            table.max_distance = std::max(table.max_distance, static_cast<int>(value));
        }
    }
    table.cache_hit = true;
    table.load_seconds = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - begin
    ).count();
    return true;
}

bool load_bounded_ud_edge_target_dist(
    const std::string& path,
    int suffix_cap,
    int max_depth,
    BoundedTargetTable& table
) {
    if (path.empty()) {
        return false;
    }
    const auto begin = std::chrono::steady_clock::now();
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        return false;
    }
    std::array<char, 8> magic{};
    input.read(magic.data(), magic.size());
    const std::array<char, 8> expected_magic = {'U', 'D', 'E', 'D', 'G', 'T', '1', 'A'};
    if (magic != expected_magic) {
        return false;
    }
    std::uint32_t domain = 0;
    std::int32_t cap = 0;
    std::int32_t depth = 0;
    std::uint64_t target_count = 0;
    std::uint64_t visited_count = 0;
    if (
        !read_binary(input, domain)
        || !read_binary(input, cap)
        || !read_binary(input, depth)
        || !read_binary(input, target_count)
        || !read_binary(input, visited_count)
    ) {
        return false;
    }
    if (
        domain != kLabeledUDEdgeCount
        || cap != suffix_cap
        || depth < max_depth
    ) {
        return false;
    }
    table.dist.assign(kLabeledUDEdgeCount, 0xff);
    input.read(
        reinterpret_cast<char*>(table.dist.data()),
        static_cast<std::streamsize>(table.dist.size())
    );
    if (!input) {
        table.dist.clear();
        return false;
    }
    table.target_count = target_count;
    table.visited_count = visited_count;
    table.complete = visited_count == kLabeledUDEdgeCount;
    table.max_distance = -1;
    for (const std::uint8_t value : table.dist) {
        if (value != 0xff) {
            table.max_distance = std::max(table.max_distance, static_cast<int>(value));
        }
    }
    table.cache_hit = true;
    table.load_seconds = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - begin
    ).count();
    return true;
}

bool load_phase1_full_pruning_dist(
    const std::string& path,
    int max_depth,
    BoundedTargetTable& table
) {
    if (path.empty()) {
        return false;
    }
    const auto begin = std::chrono::steady_clock::now();
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        return false;
    }
    std::array<char, 8> magic{};
    input.read(magic.data(), magic.size());
    const std::array<char, 8> expected_magic = {'P', '1', 'F', 'U', 'L', 'L', '1', 'A'};
    if (magic != expected_magic) {
        return false;
    }
    std::uint32_t domain = 0;
    std::int32_t depth = 0;
    std::uint64_t visited_count = 0;
    if (
        !read_binary(input, domain)
        || !read_binary(input, depth)
        || !read_binary(input, visited_count)
    ) {
        return false;
    }
    if (
        domain != kPhase1FullCount
        || (depth < max_depth && visited_count != kPhase1FullCount)
    ) {
        return false;
    }
    table.dist.assign(kPhase1FullCount, 0xff);
    input.read(
        reinterpret_cast<char*>(table.dist.data()),
        static_cast<std::streamsize>(table.dist.size())
    );
    if (!input) {
        table.dist.clear();
        return false;
    }
    table.target_count = 1;
    table.visited_count = visited_count;
    table.complete = visited_count == kPhase1FullCount;
    table.max_distance = -1;
    for (const std::uint8_t value : table.dist) {
        if (value != 0xff) {
            table.max_distance = std::max(table.max_distance, static_cast<int>(value));
        }
    }
    table.cache_hit = true;
    table.load_seconds = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - begin
    ).count();
    return true;
}

void save_bounded_cp_slice_target_dist(
    const std::string& path,
    int suffix_cap,
    int max_depth,
    const BoundedTargetTable& table
) {
    if (path.empty()) {
        return;
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        return;
    }
    const std::array<char, 8> magic = {'C', 'P', 'S', 'L', 'T', 'G', 'T', '1'};
    output.write(magic.data(), magic.size());
    const std::uint32_t domain = kCPSliceTargetCount;
    const std::int32_t cap = suffix_cap;
    const std::int32_t depth = max_depth;
    write_binary(output, domain);
    write_binary(output, cap);
    write_binary(output, depth);
    write_binary(output, table.target_count);
    write_binary(output, table.visited_count);
    output.write(
        reinterpret_cast<const char*>(table.dist.data()),
        static_cast<std::streamsize>(table.dist.size())
    );
}

void save_bounded_ud_edge_target_dist(
    const std::string& path,
    int suffix_cap,
    int max_depth,
    const BoundedTargetTable& table
) {
    if (path.empty()) {
        return;
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        return;
    }
    const std::array<char, 8> magic = {'U', 'D', 'E', 'D', 'G', 'T', '1', 'A'};
    output.write(magic.data(), magic.size());
    const std::uint32_t domain = kLabeledUDEdgeCount;
    const std::int32_t cap = suffix_cap;
    const std::int32_t depth = max_depth;
    write_binary(output, domain);
    write_binary(output, cap);
    write_binary(output, depth);
    write_binary(output, table.target_count);
    write_binary(output, table.visited_count);
    output.write(
        reinterpret_cast<const char*>(table.dist.data()),
        static_cast<std::streamsize>(table.dist.size())
    );
}

void save_phase1_full_pruning_dist(
    const std::string& path,
    int max_depth,
    const BoundedTargetTable& table
) {
    if (path.empty()) {
        return;
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        return;
    }
    const std::array<char, 8> magic = {'P', '1', 'F', 'U', 'L', 'L', '1', 'A'};
    output.write(magic.data(), magic.size());
    const std::uint32_t domain = kPhase1FullCount;
    const std::int32_t depth = max_depth;
    write_binary(output, domain);
    write_binary(output, depth);
    write_binary(output, table.visited_count);
    output.write(
        reinterpret_cast<const char*>(table.dist.data()),
        static_cast<std::streamsize>(table.dist.size())
    );
}

BoundedTargetTable build_bounded_cp_slice_target_dist(
    const std::vector<std::uint16_t>& phase1_cp_move,
    const std::vector<std::uint16_t>& phase1_slice_perm_move,
    const std::vector<std::uint8_t>& phase2_cp_slice_dist,
    int suffix_cap,
    int max_depth
) {
    constexpr std::uint8_t kUnvisited = 0xff;
    const auto begin = std::chrono::steady_clock::now();
    BoundedTargetTable table;
    table.dist.assign(kCPSliceTargetCount, kUnvisited);

    std::vector<std::uint32_t> frontier;
    for (std::uint32_t cp = 0; cp < kPermutation8Count; ++cp) {
        for (std::uint32_t slice = 0; slice < kSlicePermutationCount; ++slice) {
            if (phase2_cp_slice_dist[cp * kSlicePermutationCount + slice] > suffix_cap) {
                continue;
            }
            const std::uint32_t labeled_slice =
                kUDSliceSolvedCoord * kSlicePermutationCount + slice;
            const std::uint32_t coord = cp * kLabeledUDSliceCount + labeled_slice;
            if (table.dist[coord] == kUnvisited) {
                table.dist[coord] = 0;
                frontier.push_back(coord);
            }
        }
    }
    table.target_count = frontier.size();
    table.visited_count = frontier.size();
    table.max_distance = frontier.empty() ? -1 : 0;

    for (int depth = 0; depth < max_depth && !frontier.empty(); ++depth) {
        std::vector<std::uint32_t> next_frontier;
        const std::size_t remaining_domain =
            static_cast<std::size_t>(kCPSliceTargetCount - table.visited_count);
        const std::size_t reserve_hint = std::min<std::size_t>(
            remaining_domain,
            frontier.size() * static_cast<std::size_t>(8)
        );
        next_frontier.reserve(reserve_hint);
        const std::uint8_t next_depth = static_cast<std::uint8_t>(depth + 1);
        for (const std::uint32_t coord : frontier) {
            const std::uint32_t cp = coord / kLabeledUDSliceCount;
            const std::uint32_t slice_perm = coord - cp * kLabeledUDSliceCount;
            const std::uint32_t cp_base = cp * kMoveNames.size();
            const std::uint32_t slice_base = slice_perm * kMoveNames.size();
            for (std::uint32_t move = 0; move < kMoveNames.size(); ++move) {
                const std::uint32_t child_cp = phase1_cp_move[cp_base + move];
                const std::uint32_t child_slice = phase1_slice_perm_move[slice_base + move];
                const std::uint32_t child = child_cp * kLabeledUDSliceCount + child_slice;
                if (table.dist[child] == kUnvisited) {
                    table.dist[child] = next_depth;
                    next_frontier.push_back(child);
                }
            }
        }
        table.visited_count += next_frontier.size();
        if (!next_frontier.empty()) {
            table.max_distance = next_depth;
        }
        frontier.swap(next_frontier);
    }

    table.complete = table.visited_count == kCPSliceTargetCount;
    table.build_seconds = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - begin
    ).count();
    return table;
}

BoundedTargetTable build_phase1_full_pruning_dist(
    const std::vector<std::uint16_t>& co_move,
    const std::vector<std::uint16_t>& eo_move,
    const std::vector<std::uint16_t>& slice_move,
    int max_depth
) {
    constexpr std::uint8_t kUnvisited = 0xff;
    const auto begin = std::chrono::steady_clock::now();
    BoundedTargetTable table;
    table.dist.assign(kPhase1FullCount, kUnvisited);

    std::vector<std::uint32_t> frontier;
    const std::uint32_t solved = phase1_full_index(0, 0, kUDSliceSolvedCoord);
    table.dist[solved] = 0;
    frontier.push_back(solved);
    table.target_count = 1;
    table.visited_count = 1;
    table.max_distance = 0;

    for (int depth = 0; depth < max_depth && !frontier.empty(); ++depth) {
        std::vector<std::uint32_t> next_frontier;
        const std::size_t remaining_domain =
            static_cast<std::size_t>(kPhase1FullCount - table.visited_count);
        const std::size_t reserve_hint = std::min<std::size_t>(
            remaining_domain,
            std::min<std::size_t>(
                frontier.size() * static_cast<std::size_t>(8),
                static_cast<std::size_t>(100000000)
            )
        );
        next_frontier.reserve(reserve_hint);
        const std::uint8_t next_depth = static_cast<std::uint8_t>(depth + 1);
        for (const std::uint32_t coord : frontier) {
            const std::uint32_t slice = coord % kUDSliceCombinationCount;
            const std::uint32_t orientation = coord / kUDSliceCombinationCount;
            const std::uint32_t eo = orientation % kEdgeOrientationCount;
            const std::uint32_t co = orientation / kEdgeOrientationCount;
            const std::uint32_t co_base = co * kMoveNames.size();
            const std::uint32_t eo_base = eo * kMoveNames.size();
            const std::uint32_t slice_base = slice * kMoveNames.size();
            for (std::uint32_t move = 0; move < kMoveNames.size(); ++move) {
                const std::uint32_t child = phase1_full_index(
                    co_move[co_base + move],
                    eo_move[eo_base + move],
                    slice_move[slice_base + move]
                );
                if (table.dist[child] == kUnvisited) {
                    table.dist[child] = next_depth;
                    next_frontier.push_back(child);
                }
            }
        }
        table.visited_count += next_frontier.size();
        if (!next_frontier.empty()) {
            table.max_distance = next_depth;
        }
        frontier.swap(next_frontier);
    }

    table.complete = table.visited_count == kPhase1FullCount;
    table.build_seconds = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - begin
    ).count();
    return table;
}

BoundedTargetTable build_bounded_ud_edge_target_dist(
    const std::vector<std::uint32_t>& phase1_ud_edge_move,
    const std::vector<std::uint8_t>& phase2_ud_slice_dist,
    int suffix_cap,
    int max_depth
) {
    constexpr std::uint8_t kUnvisited = 0xff;
    const auto begin = std::chrono::steady_clock::now();
    BoundedTargetTable table;
    table.dist.assign(kLabeledUDEdgeCount, kUnvisited);

    std::vector<std::uint32_t> frontier;
    for (std::uint32_t ud = 0; ud < kPermutation8Count; ++ud) {
        bool reachable = false;
        for (std::uint32_t slice = 0; slice < kSlicePermutationCount; ++slice) {
            if (phase2_ud_slice_dist[ud * kSlicePermutationCount + slice] <= suffix_cap) {
                reachable = true;
                break;
            }
        }
        if (!reachable) {
            continue;
        }
        const std::uint32_t coord = kUDSliceSolvedCoord * kPermutation8Count + ud;
        table.dist[coord] = 0;
        frontier.push_back(coord);
    }
    table.target_count = frontier.size();
    table.visited_count = frontier.size();
    table.max_distance = frontier.empty() ? -1 : 0;

    for (int depth = 0; depth < max_depth && !frontier.empty(); ++depth) {
        std::vector<std::uint32_t> next_frontier;
        const std::size_t remaining_domain =
            static_cast<std::size_t>(kLabeledUDEdgeCount - table.visited_count);
        const std::size_t reserve_hint = std::min<std::size_t>(
            remaining_domain,
            frontier.size() * static_cast<std::size_t>(8)
        );
        next_frontier.reserve(reserve_hint);
        const std::uint8_t next_depth = static_cast<std::uint8_t>(depth + 1);
        for (const std::uint32_t coord : frontier) {
            const std::uint32_t base = coord * kMoveNames.size();
            for (std::uint32_t move = 0; move < kMoveNames.size(); ++move) {
                const std::uint32_t child = phase1_ud_edge_move[base + move];
                if (table.dist[child] == kUnvisited) {
                    table.dist[child] = next_depth;
                    next_frontier.push_back(child);
                }
            }
        }
        table.visited_count += next_frontier.size();
        if (!next_frontier.empty()) {
            table.max_distance = next_depth;
        }
        frontier.swap(next_frontier);
    }

    table.complete = table.visited_count == kLabeledUDEdgeCount;
    table.build_seconds = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - begin
    ).count();
    return table;
}

Phase2Tables build_phase2_tables() {
    Phase2Tables tables;
    tables.cp_move = build_move_table<std::uint16_t>(
        kPermutation8Count,
        [](const State& state) { return encode_cp(state); },
        [](std::uint32_t coord) { return decode_cp_coord(coord); }
    );
    tables.ud_move = build_move_table<std::uint16_t>(
        kPermutation8Count,
        [](const State& state) { return encode_ud_edges(state); },
        [](std::uint32_t coord) { return decode_ud_coord(coord); }
    );
    tables.slice_move = build_move_table<std::uint8_t>(
        kSlicePermutationCount,
        [](const State& state) { return encode_slice_edges(state); },
        [](std::uint32_t coord) { return decode_slice_coord(coord); }
    );
    tables.cp_dist = build_pruning_table(tables.cp_move, kPermutation8Count);
    tables.ud_dist = build_pruning_table(tables.ud_move, kPermutation8Count);
    tables.slice_dist = build_pruning_table(tables.slice_move, kSlicePermutationCount);
    tables.cp_slice_dist = build_pair_pruning_table(
        tables.cp_move,
        kPermutation8Count,
        0,
        tables.slice_move,
        kSlicePermutationCount,
        0,
        static_cast<std::uint32_t>(kPhase2MoveIndices.size())
    );
    tables.ud_slice_dist = build_pair_pruning_table(
        tables.ud_move,
        kPermutation8Count,
        0,
        tables.slice_move,
        kSlicePermutationCount,
        0,
        static_cast<std::uint32_t>(kPhase2MoveIndices.size())
    );
    return tables;
}

Phase1Tables build_phase1_tables() {
    Phase1Tables tables;
    tables.cp_move = build_all_move_table<std::uint16_t>(
        kPermutation8Count,
        [](const State& state) { return encode_cp(state); },
        [](std::uint32_t coord) { return decode_cp_coord(coord); }
    );
    tables.slice_perm_move = build_all_move_table<std::uint16_t>(
        kLabeledUDSliceCount,
        [](const State& state) { return encode_labeled_ud_slice(state); },
        [](std::uint32_t coord) { return decode_labeled_ud_slice_coord(coord); }
    );
    tables.co_move = build_all_move_table<std::uint16_t>(
        kCornerOrientationCount,
        [](const State& state) { return encode_corner_orientation(state); },
        [](std::uint32_t coord) { return decode_corner_orientation_coord(coord); }
    );
    tables.eo_move = build_all_move_table<std::uint16_t>(
        kEdgeOrientationCount,
        [](const State& state) { return encode_edge_orientation(state); },
        [](std::uint32_t coord) { return decode_edge_orientation_coord(coord); }
    );
    tables.slice_move = build_all_move_table<std::uint16_t>(
        kUDSliceCombinationCount,
        [](const State& state) { return encode_ud_slice_combination(state); },
        [](std::uint32_t coord) { return decode_ud_slice_combination_coord(coord); }
    );
    tables.co_dist = build_pruning_table_all_moves(tables.co_move, kCornerOrientationCount, 0);
    tables.eo_dist = build_pruning_table_all_moves(tables.eo_move, kEdgeOrientationCount, 0);
    tables.slice_dist = build_pruning_table_all_moves(
        tables.slice_move,
        kUDSliceCombinationCount,
        kUDSliceSolvedCoord
    );
    tables.co_eo_dist = build_pair_pruning_table(
        tables.co_move,
        kCornerOrientationCount,
        0,
        tables.eo_move,
        kEdgeOrientationCount,
        0,
        static_cast<std::uint32_t>(kMoveNames.size())
    );
    tables.co_slice_dist = build_pair_pruning_table(
        tables.co_move,
        kCornerOrientationCount,
        0,
        tables.slice_move,
        kUDSliceCombinationCount,
        kUDSliceSolvedCoord,
        static_cast<std::uint32_t>(kMoveNames.size())
    );
    tables.eo_slice_dist = build_pair_pruning_table(
        tables.eo_move,
        kEdgeOrientationCount,
        0,
        tables.slice_move,
        kUDSliceCombinationCount,
        kUDSliceSolvedCoord,
        static_cast<std::uint32_t>(kMoveNames.size())
    );
    return tables;
}

// ---------------------------------------------------------------------------
// FlipUDSlice 16-symmetry phase-1 reduction (Kociemba/Cube-Explorer style).
//
// The symmetry coordinate-action tables are generated by
// scripts/generate_phase1_sym_tables.py from the validated whole-cube symmetry
// layer (src/rubik_optimal/symmetry.py) and loaded here.  Everything downstream
// (class reduction, BFS pruning table, lookups) is native and exact-safe; it is
// validated end-to-end against the trusted raw phase-1 BFS table in the
// verify-sym-phase1 mode.
// ---------------------------------------------------------------------------

template <typename T>
bool read_vector(std::istream& stream, std::vector<T>& target, std::size_t count) {
    target.assign(count, T{});
    stream.read(
        reinterpret_cast<char*>(target.data()),
        static_cast<std::streamsize>(count * sizeof(T))
    );
    return static_cast<bool>(stream);
}

// Load the FlipUDSlice symmetry reduction emitted by
// scripts/generate_phase1_sym_tables.py.  All symmetry math (correct for the
// orientation-reversing reflections) is done in Python; here we only read the
// reduction tables and validate the header invariants.
bool load_sym_coordinate_tables(Phase1Tables& tables, const std::string& path) {
    if (!tables.flipudslice_classidx.empty()) {
        return true;
    }
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        return false;
    }
    std::array<char, 8> magic{};
    input.read(magic.data(), magic.size());
    const std::array<char, 8> expected = {'P', '1', 'S', 'Y', 'M', 'R', '0', '3'};
    if (magic != expected) {
        return false;
    }
    std::uint32_t sym_count = 0;
    std::uint32_t flip_count = 0;
    std::uint32_t udslice_count = 0;
    std::uint32_t twist_count = 0;
    std::uint32_t class_count = 0;
    std::uint32_t flipudslice_count = 0;
    if (
        !read_binary(input, sym_count)
        || !read_binary(input, flip_count)
        || !read_binary(input, udslice_count)
        || !read_binary(input, twist_count)
        || !read_binary(input, class_count)
        || !read_binary(input, flipudslice_count)
    ) {
        return false;
    }
    if (
        sym_count != kSymCount
        || flip_count != kEdgeOrientationCount
        || udslice_count != kUDSliceCombinationCount
        || twist_count != kCornerOrientationCount
        || class_count != kFlipUDSliceClassCount
        || flipudslice_count != kFlipUDSliceCount
    ) {
        return false;
    }
    input.read(reinterpret_cast<char*>(tables.inv_sym.data()), kSymCount);
    if (
        !read_vector(input, tables.sym_twist, static_cast<std::size_t>(kSymCount) * kCornerOrientationCount)
        || !read_vector(input, tables.classidx_to_rep, kFlipUDSliceClassCount)
        || !read_vector(input, tables.class_stab_mask, kFlipUDSliceClassCount)
        || !read_vector(input, tables.flipudslice_classidx, kFlipUDSliceCount)
        || !read_vector(input, tables.flipudslice_sym, kFlipUDSliceCount)
    ) {
        tables.sym_twist.clear();
        tables.classidx_to_rep.clear();
        tables.class_stab_mask.clear();
        tables.flipudslice_classidx.clear();
        tables.flipudslice_sym.clear();
        return false;
    }
    return true;
}

inline std::uint32_t sym_phase1_reduced_index(
    const Phase1Tables& tables,
    std::uint32_t co,
    std::uint32_t eo,
    std::uint32_t slice
) {
    const std::uint32_t r = eo * kUDSliceCombinationCount + slice;
    const std::uint32_t cls = tables.flipudslice_classidx[r];
    const std::uint32_t sym = tables.flipudslice_sym[r];
    const std::uint32_t base = tables.sym_twist[sym * kCornerOrientationCount + co];
    // Canonicalise the twist over the representative's FlipUDSlice stabilizer.
    // The symmetries mapping r -> rep are { tau . sym : tau in Stab(rep) }, so
    // the candidate reduced twists are sym_twist[tau][base]; the reduced state is
    // the orbit minimum (bit 0 = identity gives base itself).
    std::uint32_t reduced_twist = base;
    std::uint32_t mask = tables.class_stab_mask[cls] & ~1u;  // drop identity bit
    while (mask != 0) {
        const std::uint32_t tau = __builtin_ctz(mask);
        mask &= mask - 1;
        const std::uint32_t candidate = tables.sym_twist[tau * kCornerOrientationCount + base];
        if (candidate < reduced_twist) {
            reduced_twist = candidate;
        }
    }
    return cls * kCornerOrientationCount + reduced_twist;
}

inline int sym_phase1_dist(
    const Phase1Tables& tables,
    std::uint32_t co,
    std::uint32_t eo,
    std::uint32_t slice
) {
    const std::uint8_t value = tables.sym_dist[sym_phase1_reduced_index(tables, co, eo, slice)];
    if (value != 0xff) {
        return static_cast<int>(value);
    }
    // An unvisited (0xff) slot can only be a non-canonical reduced index, which
    // sym_phase1_reduced_index never produces for a real state.  Reaching this
    // point therefore means the distance table is inconsistent with the
    // canonicalisation (corrupt/stale cache); a fabricated "max+1" bound here
    // could silently over-prune an optimality proof, so fail loudly instead.
    std::cerr << "fatal: sym_phase1_dist hit an unvisited (0xff) entry for co=" << co
              << " eo=" << eo << " slice=" << slice
              << "; sym-reduced phase-1 distance table is inconsistent with its canonicalisation"
              << std::endl;
    std::abort();
}

BoundedTargetTable build_sym_phase1_dist(const Phase1Tables& tables, int max_depth) {
    constexpr std::uint8_t kUnvisited = 0xff;
    const auto begin = std::chrono::steady_clock::now();
    BoundedTargetTable table;
    table.dist.assign(kSymPhase1Count, kUnvisited);

    std::vector<std::uint32_t> frontier;
    const std::uint32_t solved =
        sym_phase1_reduced_index(tables, 0, 0, kUDSliceSolvedCoord);
    table.dist[solved] = 0;
    frontier.push_back(solved);
    table.target_count = 1;
    table.visited_count = 1;
    table.max_distance = 0;

    for (int depth = 0; depth < max_depth && !frontier.empty(); ++depth) {
        std::vector<std::uint32_t> next_frontier;
        next_frontier.reserve(std::min<std::size_t>(frontier.size() * 8, 80000000));
        const std::uint8_t next_depth = static_cast<std::uint8_t>(depth + 1);
        for (const std::uint32_t idx : frontier) {
            const std::uint32_t cls = idx / kCornerOrientationCount;
            const std::uint32_t twist = idx % kCornerOrientationCount;
            const std::uint32_t rep = tables.classidx_to_rep[cls];
            const std::uint32_t flip_base = (rep / kUDSliceCombinationCount) * kMoveNames.size();
            const std::uint32_t udslice_base = (rep % kUDSliceCombinationCount) * kMoveNames.size();
            const std::uint32_t twist_base = twist * kMoveNames.size();
            for (std::uint32_t move = 0; move < kMoveNames.size(); ++move) {
                const std::uint32_t new_flip = tables.eo_move[flip_base + move];
                const std::uint32_t new_udslice = tables.slice_move[udslice_base + move];
                const std::uint32_t new_twist = tables.co_move[twist_base + move];
                const std::uint32_t child =
                    sym_phase1_reduced_index(tables, new_twist, new_flip, new_udslice);
                if (table.dist[child] == kUnvisited) {
                    table.dist[child] = next_depth;
                    next_frontier.push_back(child);
                }
            }
        }
        table.visited_count += next_frontier.size();
        if (!next_frontier.empty()) {
            table.max_distance = next_depth;
        }
        frontier.swap(next_frontier);
    }

    table.complete = table.visited_count == kSymPhase1Count;
    table.build_seconds = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - begin
    ).count();
    return table;
}

bool load_sym_phase1_dist(const std::string& path, int max_depth, BoundedTargetTable& table) {
    if (path.empty()) {
        return false;
    }
    const auto begin = std::chrono::steady_clock::now();
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        return false;
    }
    std::array<char, 8> magic{};
    input.read(magic.data(), magic.size());
    const std::array<char, 8> expected = {'P', '1', 'S', 'Y', 'M', 'R', 'D', '1'};
    if (magic != expected) {
        return false;
    }
    std::uint32_t domain = 0;
    std::int32_t depth = 0;
    std::uint64_t visited_count = 0;
    if (
        !read_binary(input, domain)
        || !read_binary(input, depth)
        || !read_binary(input, visited_count)
    ) {
        return false;
    }
    if (domain != kSymPhase1Count || (depth < max_depth && visited_count != kSymPhase1Count)) {
        return false;
    }
    table.dist.assign(kSymPhase1Count, 0xff);
    input.read(
        reinterpret_cast<char*>(table.dist.data()),
        static_cast<std::streamsize>(table.dist.size())
    );
    if (!input) {
        table.dist.clear();
        return false;
    }
    table.visited_count = visited_count;
    table.complete = visited_count == kSymPhase1Count;
    table.max_distance = -1;
    for (const std::uint8_t value : table.dist) {
        if (value != 0xff) {
            table.max_distance = std::max(table.max_distance, static_cast<int>(value));
        }
    }
    table.cache_hit = true;
    table.load_seconds = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - begin
    ).count();
    return true;
}

void save_sym_phase1_dist(const std::string& path, int max_depth, const BoundedTargetTable& table) {
    if (path.empty()) {
        return;
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        return;
    }
    const std::array<char, 8> magic = {'P', '1', 'S', 'Y', 'M', 'R', 'D', '1'};
    output.write(magic.data(), magic.size());
    const std::uint32_t domain = kSymPhase1Count;
    const std::int32_t depth = max_depth;
    write_binary(output, domain);
    write_binary(output, depth);
    write_binary(output, table.visited_count);
    output.write(
        reinterpret_cast<const char*>(table.dist.data()),
        static_cast<std::streamsize>(table.dist.size())
    );
}

void set_sym_phase1_pruning_table(
    Phase1Tables& tables,
    TwoPhaseStats& stats,
    int max_depth,
    const std::string& sym_tables_path,
    const std::string& cache_path
) {
    if (
        !tables.sym_dist.empty()
        && (tables.sym_dist_complete || tables.sym_dist_depth >= max_depth)
    ) {
        return;
    }
    if (tables.flipudslice_classidx.empty()) {
        if (!load_sym_coordinate_tables(tables, sym_tables_path)) {
            throw std::runtime_error(
                "failed to load phase-1 symmetry tables from " + sym_tables_path
                + " (run scripts/generate_phase1_sym_tables.py)"
            );
        }
    }
    BoundedTargetTable table;
    if (!load_sym_phase1_dist(cache_path, max_depth, table)) {
        table = build_sym_phase1_dist(tables, max_depth);
        save_sym_phase1_dist(cache_path, max_depth, table);
    }
    tables.sym_dist = std::move(table.dist);
    tables.sym_dist_depth = max_depth;
    tables.sym_dist_max_distance = table.max_distance;
    tables.sym_dist_complete = table.complete;
    ++stats.sym_phase1_table_builds;
    stats.sym_phase1_last_states = table.visited_count;
    stats.sym_phase1_build_seconds += table.build_seconds;
    stats.sym_phase1_load_seconds += table.load_seconds;
    stats.sym_phase1_last_depth = max_depth;
    stats.sym_phase1_max_distance = table.max_distance;
    stats.sym_phase1_complete = table.complete;
    stats.sym_phase1_cache_hit = table.cache_hit;
}

void add_ud_edge_move_table(Phase1Tables& phase1_tables) {
    if (!phase1_tables.ud_edge_move.empty()) {
        return;
    }
    phase1_tables.ud_edge_move = build_all_move_table<std::uint32_t>(
        kLabeledUDEdgeCount,
        [](const State& state) { return encode_labeled_ud_edges(state); },
        [](std::uint32_t coord) { return decode_labeled_ud_edges_coord(coord); }
    );
}

void set_phase1_full_pruning_table(
    Phase1Tables& phase1_tables,
    TwoPhaseStats& stats,
    int max_depth,
    const std::string& cache_path
) {
    if (max_depth < 0) {
        phase1_tables.full_dist.clear();
        phase1_tables.full_dist_depth = -1;
        phase1_tables.full_dist_max_distance = -1;
        phase1_tables.full_dist_complete = false;
        return;
    }
    if (
        !phase1_tables.full_dist.empty()
        && (
            phase1_tables.full_dist_complete
            || phase1_tables.full_dist_depth >= max_depth
        )
    ) {
        return;
    }
    BoundedTargetTable table;
    const std::string resolved_cache_path =
        phase1_full_pruning_cache_path_for(cache_path, max_depth);
    if (!load_phase1_full_pruning_dist(resolved_cache_path, max_depth, table)) {
        table = build_phase1_full_pruning_dist(
            phase1_tables.co_move,
            phase1_tables.eo_move,
            phase1_tables.slice_move,
            max_depth
        );
        save_phase1_full_pruning_dist(resolved_cache_path, max_depth, table);
    }
    phase1_tables.full_dist = std::move(table.dist);
    phase1_tables.full_dist_depth = max_depth;
    phase1_tables.full_dist_max_distance = table.max_distance;
    phase1_tables.full_dist_complete = table.complete;
    ++stats.phase1_full_pruning_table_builds;
    stats.phase1_full_pruning_last_states = table.visited_count;
    stats.phase1_full_pruning_build_seconds += table.build_seconds;
    stats.phase1_full_pruning_last_depth = max_depth;
    stats.phase1_full_pruning_max_distance = table.max_distance;
    stats.phase1_full_pruning_complete = table.complete;
    stats.phase1_full_pruning_cache_hit = table.cache_hit;
    stats.phase1_full_pruning_load_seconds += table.load_seconds;
}

void add_cp_target_pruning_tables(
    Phase1Tables& phase1_tables,
    const Phase2Tables& phase2_tables,
    int max_cap
) {
    phase1_tables.cp_target_max_cap = std::max(0, max_cap);
    phase1_tables.cp_target_dist_by_cap = build_cp_target_dist_by_cap(
        phase1_tables.cp_move,
        phase2_tables.cp_move,
        phase1_tables.cp_target_max_cap
    );
}

void add_slice_perm_target_pruning_tables(
    Phase1Tables& phase1_tables,
    const Phase2Tables& phase2_tables,
    int max_cap
) {
    phase1_tables.slice_perm_target_max_cap = std::max(0, max_cap);
    phase1_tables.slice_perm_target_dist_by_cap = build_slice_perm_target_dist_by_cap(
        phase1_tables.slice_perm_move,
        phase2_tables.slice_dist,
        phase1_tables.slice_perm_target_max_cap
    );
}

void clear_cp_slice_target_pruning_table(Phase1Tables& phase1_tables) {
    phase1_tables.cp_slice_target_dist.clear();
    phase1_tables.cp_slice_target_cap = -1;
    phase1_tables.cp_slice_target_depth = -1;
    phase1_tables.cp_slice_target_max_distance = -1;
    phase1_tables.cp_slice_target_complete = false;
}

void clear_ud_edge_target_pruning_table(Phase1Tables& phase1_tables) {
    phase1_tables.ud_edge_target_dist.clear();
    phase1_tables.ud_edge_target_cap = -1;
    phase1_tables.ud_edge_target_depth = -1;
    phase1_tables.ud_edge_target_max_distance = -1;
    phase1_tables.ud_edge_target_complete = false;
}

void set_cp_slice_target_pruning_table(
    Phase1Tables& phase1_tables,
    const Phase2Tables& phase2_tables,
    TwoPhaseStats& stats,
    int suffix_cap,
    int max_depth,
    const std::string& cache_path
) {
    if (suffix_cap < 0 || max_depth < 0) {
        clear_cp_slice_target_pruning_table(phase1_tables);
        return;
    }
    if (
        !phase1_tables.cp_slice_target_dist.empty()
        && phase1_tables.cp_slice_target_cap == suffix_cap
        && phase1_tables.cp_slice_target_depth >= max_depth
    ) {
        return;
    }
    BoundedTargetTable table;
    const std::string resolved_cache_path =
        cp_slice_target_cache_path_for(cache_path, suffix_cap, max_depth);
    if (!load_bounded_cp_slice_target_dist(resolved_cache_path, suffix_cap, max_depth, table)) {
        table = build_bounded_cp_slice_target_dist(
            phase1_tables.cp_move,
            phase1_tables.slice_perm_move,
            phase2_tables.cp_slice_dist,
            suffix_cap,
            max_depth
        );
        save_bounded_cp_slice_target_dist(resolved_cache_path, suffix_cap, max_depth, table);
    }
    phase1_tables.cp_slice_target_dist = std::move(table.dist);
    phase1_tables.cp_slice_target_cap = suffix_cap;
    phase1_tables.cp_slice_target_depth = max_depth;
    phase1_tables.cp_slice_target_max_distance = table.max_distance;
    phase1_tables.cp_slice_target_complete = table.complete;
    ++stats.phase1_cp_slice_target_table_builds;
    stats.phase1_cp_slice_target_last_targets = table.target_count;
    stats.phase1_cp_slice_target_last_states = table.visited_count;
    stats.phase1_cp_slice_target_build_seconds += table.build_seconds;
    stats.phase1_cp_slice_target_last_cap = suffix_cap;
    stats.phase1_cp_slice_target_last_depth = max_depth;
    stats.phase1_cp_slice_target_max_distance = table.max_distance;
    stats.phase1_cp_slice_target_complete = table.complete;
    stats.phase1_cp_slice_target_cache_hit = table.cache_hit;
    stats.phase1_cp_slice_target_load_seconds += table.load_seconds;
}

void set_ud_edge_target_pruning_table(
    Phase1Tables& phase1_tables,
    const Phase2Tables& phase2_tables,
    TwoPhaseStats& stats,
    int suffix_cap,
    int max_depth,
    const std::string& cache_path
) {
    if (suffix_cap < 0 || max_depth < 0) {
        clear_ud_edge_target_pruning_table(phase1_tables);
        return;
    }
    if (
        !phase1_tables.ud_edge_target_dist.empty()
        && phase1_tables.ud_edge_target_cap == suffix_cap
        && phase1_tables.ud_edge_target_depth >= max_depth
    ) {
        return;
    }
    if (phase1_tables.ud_edge_move.empty()) {
        throw std::runtime_error("UD-edge target pruning requires UD-edge move table");
    }
    BoundedTargetTable table;
    const std::string resolved_cache_path =
        ud_edge_target_cache_path_for(cache_path, suffix_cap, max_depth);
    if (!load_bounded_ud_edge_target_dist(resolved_cache_path, suffix_cap, max_depth, table)) {
        table = build_bounded_ud_edge_target_dist(
            phase1_tables.ud_edge_move,
            phase2_tables.ud_slice_dist,
            suffix_cap,
            max_depth
        );
        save_bounded_ud_edge_target_dist(resolved_cache_path, suffix_cap, max_depth, table);
    }
    phase1_tables.ud_edge_target_dist = std::move(table.dist);
    phase1_tables.ud_edge_target_cap = suffix_cap;
    phase1_tables.ud_edge_target_depth = max_depth;
    phase1_tables.ud_edge_target_max_distance = table.max_distance;
    phase1_tables.ud_edge_target_complete = table.complete;
    ++stats.phase1_ud_edge_target_table_builds;
    stats.phase1_ud_edge_target_last_targets = table.target_count;
    stats.phase1_ud_edge_target_last_states = table.visited_count;
    stats.phase1_ud_edge_target_build_seconds += table.build_seconds;
    stats.phase1_ud_edge_target_last_cap = suffix_cap;
    stats.phase1_ud_edge_target_last_depth = max_depth;
    stats.phase1_ud_edge_target_max_distance = table.max_distance;
    stats.phase1_ud_edge_target_complete = table.complete;
    stats.phase1_ud_edge_target_cache_hit = table.cache_hit;
    stats.phase1_ud_edge_target_load_seconds += table.load_seconds;
}

int face_for_phase2_move(int move_index) {
    return kPhase2MoveNames[move_index][0];
}

int face_for_move(int move_index) {
    return kMoveNames[move_index][0];
}

int axis_for_face(int face) {
    switch (face) {
        case 'U':
        case 'D':
            return 0;
        case 'R':
        case 'L':
            return 1;
        case 'F':
        case 'B':
            return 2;
        default:
            return -1;
    }
}

bool commuting_order_violation(int previous_face, int move_face) {
    if (previous_face < 0 || previous_face == move_face) {
        return false;
    }
    const int axis = axis_for_face(move_face);
    if (axis_for_face(previous_face) != axis) {
        return false;
    }
    return (axis == 0 && move_face == 'U')
        || (axis == 1 && move_face == 'R')
        || (axis == 2 && move_face == 'F');
}

int admissible_dist(const std::vector<std::uint8_t>& table, std::uint32_t index) {
    const std::uint8_t value = table[index];
    return value == 0xff ? 0 : static_cast<int>(value);
}

int lower_bound(const Phase2Tables& tables, const Phase2Coord& coord) {
    return std::max({
        admissible_dist(tables.cp_dist, coord.cp),
        admissible_dist(tables.ud_dist, coord.ud),
        admissible_dist(tables.slice_dist, coord.slice),
        admissible_dist(
            tables.cp_slice_dist,
            coord.cp * kSlicePermutationCount + coord.slice
        ),
        admissible_dist(
            tables.ud_slice_dist,
            coord.ud * kSlicePermutationCount + coord.slice
        ),
    });
}

int lower_bound(const Phase1Tables& tables, const Phase1Coord& coord) {
    int full_bound = 0;
    if (!tables.full_dist.empty()) {
        const std::uint32_t index = phase1_full_index(coord.co, coord.eo, coord.slice);
        const std::uint8_t value = tables.full_dist[index];
        if (value != 0xff) {
            full_bound = static_cast<int>(value);
        } else if (tables.full_dist_max_distance >= 0) {
            full_bound = tables.full_dist_max_distance + 1;
        }
    }
    int sym_bound = 0;
    if (!tables.sym_dist.empty()) {
        // Exact distance-to-G1 (UD axis) for the FlipUDSlice x twist projection,
        // complete to the symmetry-reduced pruning depth (12).  Admissible lower
        // bound on the phase-1 distance; supersedes the raw full table.
        sym_bound = sym_phase1_dist(tables, coord.co, coord.eo, coord.slice);
    }
    return std::max({
        full_bound,
        sym_bound,
        admissible_dist(tables.co_dist, coord.co),
        admissible_dist(tables.eo_dist, coord.eo),
        admissible_dist(tables.slice_dist, coord.slice),
        admissible_dist(
            tables.co_eo_dist,
            coord.co * kEdgeOrientationCount + coord.eo
        ),
        admissible_dist(
            tables.co_slice_dist,
            coord.co * kUDSliceCombinationCount + coord.slice
        ),
        admissible_dist(
            tables.eo_slice_dist,
            coord.eo * kUDSliceCombinationCount + coord.slice
        ),
    });
}

// Mike Reid / Cube-Explorer three-axis bound: the maximum of the phase-1
// distance-to-G1 over the three choices of axis (UD, RL, FB).  Each is a lower
// bound on the distance to solved, so their maximum is an admissible lower bound
// on the *total* solution length (used for a global g + h > target prune).  The
// RL/FB coordinates are the state conjugated onto those axes (maintained
// incrementally via the move-conjugation maps).
int three_axis_solved_bound(const Phase1Tables& tables, const Phase1Coord& coord) {
    if (tables.sym_dist.empty()) {
        return 0;
    }
    const int p_ud = sym_phase1_dist(tables, coord.co, coord.eo, coord.slice);
    const int p_rl = sym_phase1_dist(tables, coord.co_rl, coord.eo_rl, coord.slice_rl);
    const int p_fb = sym_phase1_dist(tables, coord.co_fb, coord.eo_fb, coord.slice_fb);
    return std::max({p_ud, p_rl, p_fb});
}

int cp_target_lower_bound(const Phase1Tables& tables, const Phase1Coord& coord, int suffix_cap) {
    if (suffix_cap < 0 || tables.cp_target_dist_by_cap.empty()) {
        return 0;
    }
    const int cap = std::min(suffix_cap, tables.cp_target_max_cap);
    return admissible_dist(
        tables.cp_target_dist_by_cap,
        static_cast<std::uint32_t>(cap) * kPermutation8Count + coord.cp
    );
}

int slice_perm_target_lower_bound(const Phase1Tables& tables, const Phase1Coord& coord, int suffix_cap) {
    if (suffix_cap < 0 || tables.slice_perm_target_dist_by_cap.empty()) {
        return 0;
    }
    const int cap = std::min(suffix_cap, tables.slice_perm_target_max_cap);
    return admissible_dist(
        tables.slice_perm_target_dist_by_cap,
        static_cast<std::uint32_t>(cap) * kLabeledUDSliceCount + coord.slice_perm
    );
}

bool cp_slice_target_prunes(
    const Phase1Tables& tables,
    const Phase1Coord& coord,
    int suffix_cap,
    int remaining
) {
    if (
        suffix_cap < 0
        || remaining < 0
        || tables.cp_slice_target_dist.empty()
        || tables.cp_slice_target_cap != suffix_cap
        || tables.cp_slice_target_depth < remaining
    ) {
        return false;
    }
    if (
        tables.cp_slice_target_complete
        && tables.cp_slice_target_max_distance >= 0
        && remaining > tables.cp_slice_target_max_distance
    ) {
        return false;
    }
    const std::uint32_t index = coord.cp * kLabeledUDSliceCount + coord.slice_perm;
    const std::uint8_t value = tables.cp_slice_target_dist[index];
    return value == 0xff || static_cast<int>(value) > remaining;
}

bool ud_edge_target_prunes(
    const Phase1Tables& tables,
    const Phase1Coord& coord,
    int suffix_cap,
    int remaining
) {
    if (
        suffix_cap < 0
        || remaining < 0
        || tables.ud_edge_target_dist.empty()
        || tables.ud_edge_target_cap != suffix_cap
        || tables.ud_edge_target_depth < remaining
    ) {
        return false;
    }
    if (
        tables.ud_edge_target_complete
        && tables.ud_edge_target_max_distance >= 0
        && remaining > tables.ud_edge_target_max_distance
    ) {
        return false;
    }
    const std::uint8_t value = tables.ud_edge_target_dist[coord.ud_edges];
    return value == 0xff || static_cast<int>(value) > remaining;
}

bool is_goal(const Phase2Coord& coord) {
    return coord.cp == 0 && coord.ud == 0 && coord.slice == 0;
}

bool is_goal(const Phase1Coord& coord) {
    return coord.co == 0 && coord.eo == 0 && coord.slice == kUDSliceSolvedCoord;
}

std::uint64_t phase2_key(const Phase2Coord& coord) {
    return (
        (static_cast<std::uint64_t>(coord.cp) * kPermutation8Count + coord.ud)
        * kSlicePermutationCount
        + coord.slice
    );
}

int search(Solver& solver, Phase2Coord coord, int g, int bound, int previous_face) {
    if ((solver.expanded & 0x3fffU) == 0 && std::chrono::steady_clock::now() >= solver.deadline) {
        solver.timed_out = true;
        return kTimeout;
    }
    if (solver.node_limit != 0 && solver.expanded >= solver.node_limit) {
        solver.node_limited = true;
        return kNodeLimit;
    }
    const int h = lower_bound(*solver.tables, coord);
    const int f = g + h;
    if (f > bound) {
        return f;
    }
    if (is_goal(coord)) {
        solver.solution = solver.path;
        return kFound;
    }
    if (g >= bound) {
        return std::numeric_limits<int>::max();
    }

    ++solver.expanded;
    struct Child {
        int h;
        int move;
        Phase2Coord coord;
    };
    std::array<Child, 10> children{};
    std::uint32_t child_count = 0;
    for (std::uint32_t move = 0; move < kPhase2MoveIndices.size(); ++move) {
        const int face = face_for_phase2_move(move);
        if (face == previous_face) {
            continue;
        }
        Phase2Coord child{
            solver.tables->cp_move[coord.cp * kPhase2MoveIndices.size() + move],
            solver.tables->ud_move[coord.ud * kPhase2MoveIndices.size() + move],
            solver.tables->slice_move[coord.slice * kPhase2MoveIndices.size() + move],
        };
        ++solver.generated;
        children[child_count++] = {lower_bound(*solver.tables, child), static_cast<int>(move), child};
    }
    std::sort(children.begin(), children.begin() + child_count, [](const Child& a, const Child& b) {
        if (a.h != b.h) {
            return a.h < b.h;
        }
        return a.move < b.move;
    });

    int minimum = std::numeric_limits<int>::max();
    for (std::uint32_t index = 0; index < child_count; ++index) {
        solver.path.push_back(children[index].move);
        const int outcome = search(
            solver,
            children[index].coord,
            g + 1,
            bound,
            face_for_phase2_move(children[index].move)
        );
        if (outcome == kFound || outcome == kTimeout || outcome == kNodeLimit) {
            return outcome;
        }
        if (outcome < minimum) {
            minimum = outcome;
        }
        solver.path.pop_back();
    }
    return minimum;
}

Phase2SearchResult solve_phase2_with_tables(
    const Phase2Tables& tables,
    const Phase2Coord& start,
    int max_depth,
    std::chrono::steady_clock::time_point deadline,
    std::uint64_t node_limit
) {
    Phase2SearchResult result;
    result.initial_lower_bound = lower_bound(tables, start);
    result.final_bound = std::min(result.initial_lower_bound, max_depth);
    if (result.initial_lower_bound > max_depth) {
        result.status = "lower_bound";
        result.final_bound = max_depth;
        return result;
    }
    Solver solver;
    solver.tables = &tables;
    solver.deadline = deadline;
    solver.node_limit = node_limit;
    int bound = result.initial_lower_bound;
    while (bound <= max_depth) {
        solver.path.clear();
        solver.solution.clear();
        const int outcome = search(solver, start, 0, bound, -1);
        result.final_bound = bound;
        if (outcome == kFound) {
            result.status = "exact";
            result.solution = solver.solution;
            result.expanded = solver.expanded;
            result.generated = solver.generated;
            return result;
        }
        if (outcome == kTimeout || solver.timed_out) {
            result.status = "timeout";
            result.expanded = solver.expanded;
            result.generated = solver.generated;
            return result;
        }
        if (outcome == kNodeLimit || solver.node_limited) {
            result.status = "timeout";
            result.expanded = solver.expanded;
            result.generated = solver.generated;
            return result;
        }
        if (outcome == std::numeric_limits<int>::max()) {
            break;
        }
        bound = outcome;
    }
    result.status = "lower_bound";
    result.expanded = solver.expanded;
    result.generated = solver.generated;
    return result;
}

void search_two_phase_depth(
    const Phase1Tables& phase1_tables,
    const Phase2Tables& phase2_tables,
    const Options& options,
    TwoPhaseStats& stats,
    std::chrono::steady_clock::time_point deadline,
    State state,
    Phase1Coord coord,
    int g,
    int depth,
    int previous_face
) {
    if (stats.solution_found || stats.timed_out || stats.node_limited) {
        return;
    }
    if ((stats.phase1_expanded & 0x3fffU) == 0 && std::chrono::steady_clock::now() >= deadline) {
        stats.timed_out = true;
        return;
    }
    if (options.phase1_node_limit != 0 && stats.phase1_expanded >= options.phase1_node_limit) {
        stats.node_limited = true;
        return;
    }
    const int remaining = depth - g;
    if (lower_bound(phase1_tables, coord) > remaining) {
        return;
    }
    if (
        options.three_axis_pruning_enabled
        && g + three_axis_solved_bound(phase1_tables, coord) > options.target_bound
    ) {
        ++stats.phase1_three_axis_prunes;
        return;
    }
    const int suffix_cap = options.target_bound - depth;
    if (
        options.cp_target_pruning_enabled
        && cp_target_lower_bound(phase1_tables, coord, suffix_cap) > remaining
    ) {
        ++stats.phase1_cp_target_prunes;
        return;
    }
    if (
        options.cp_target_pruning_enabled
        && slice_perm_target_lower_bound(phase1_tables, coord, suffix_cap) > remaining
    ) {
        ++stats.phase1_slice_perm_target_prunes;
        return;
    }
    if (
        options.cp_slice_target_pruning_enabled
        && cp_slice_target_prunes(phase1_tables, coord, suffix_cap, remaining)
    ) {
        ++stats.phase1_cp_slice_target_prunes;
        return;
    }
    if (
        options.ud_edge_target_pruning_enabled
        && ud_edge_target_prunes(phase1_tables, coord, suffix_cap, remaining)
    ) {
        ++stats.phase1_ud_edge_target_prunes;
        return;
    }
    if (g == depth) {
        if (!is_goal(coord)) {
            return;
        }
        const Phase2Coord p2 = encode_phase2(state);
        if (options.handoff_dedup_enabled) {
            const auto key = phase2_key(p2);
            auto seen = stats.seen_g1_depths.find(key);
            if (seen != stats.seen_g1_depths.end() && seen->second <= g) {
                ++stats.duplicate_handoff_count;
                return;
            }
            stats.seen_g1_depths[key] = g;
        }
        ++stats.handoff_count;
        const int phase2_cap = options.target_bound - g;
        if (phase2_cap < 0) {
            ++stats.phase2_lower_bound_rows;
            return;
        }
        ++stats.phase2_calls;
        Phase2SearchResult p2_result = solve_phase2_with_tables(
            phase2_tables,
            p2,
            phase2_cap,
            deadline,
            options.phase2_node_limit
        );
        stats.phase2_expanded += p2_result.expanded;
        stats.phase2_generated += p2_result.generated;
        if (p2_result.status == "exact") {
            stats.solution_found = true;
            stats.solution_phase1_length = g;
            stats.solution_phase2_length = static_cast<int>(p2_result.solution.size());
            stats.best_phase1_solution = stats.phase1_path;
            stats.best_phase2_solution = p2_result.solution;
        } else if (p2_result.status == "timeout") {
            ++stats.phase2_timeout_rows;
            if (std::chrono::steady_clock::now() >= deadline) {
                stats.timed_out = true;
            } else {
                stats.node_limited = true;
            }
        } else {
            ++stats.phase2_lower_bound_rows;
        }
        return;
    }

    ++stats.phase1_expanded;
    struct Child {
        int h;
        int move;
        State state;
        Phase1Coord coord;
    };
    std::array<Child, 18> children{};
    std::uint32_t child_count = 0;
    for (std::uint32_t move = 0; move < kMoveNames.size(); ++move) {
        const int face = face_for_move(move);
        if (g == 0 && options.root_move_mask_enabled && !options.root_move_allowed[move]) {
            continue;
        }
        if (face == previous_face || commuting_order_violation(previous_face, face)) {
            continue;
        }
        Phase1Coord child_coord{
            phase1_tables.cp_move[coord.cp * kMoveNames.size() + move],
            phase1_tables.slice_perm_move[coord.slice_perm * kMoveNames.size() + move],
            phase1_tables.ud_edge_move.empty()
                ? 0
                : phase1_tables.ud_edge_move[coord.ud_edges * kMoveNames.size() + move],
            phase1_tables.co_move[coord.co * kMoveNames.size() + move],
            phase1_tables.eo_move[coord.eo * kMoveNames.size() + move],
            phase1_tables.slice_move[coord.slice * kMoveNames.size() + move],
        };
        if (lower_bound(phase1_tables, child_coord) > remaining - 1) {
            continue;
        }
        if (options.three_axis_pruning_enabled) {
            const std::uint32_t rl = options.conj_rl[move];
            const std::uint32_t fb = options.conj_fb[move];
            child_coord.co_rl = phase1_tables.co_move[coord.co_rl * kMoveNames.size() + rl];
            child_coord.eo_rl = phase1_tables.eo_move[coord.eo_rl * kMoveNames.size() + rl];
            child_coord.slice_rl = phase1_tables.slice_move[coord.slice_rl * kMoveNames.size() + rl];
            child_coord.co_fb = phase1_tables.co_move[coord.co_fb * kMoveNames.size() + fb];
            child_coord.eo_fb = phase1_tables.eo_move[coord.eo_fb * kMoveNames.size() + fb];
            child_coord.slice_fb = phase1_tables.slice_move[coord.slice_fb * kMoveNames.size() + fb];
            if (g + 1 + three_axis_solved_bound(phase1_tables, child_coord) > options.target_bound) {
                ++stats.phase1_three_axis_prunes;
                continue;
            }
        }
        if (
            options.cp_target_pruning_enabled
            && cp_target_lower_bound(phase1_tables, child_coord, suffix_cap) > remaining - 1
        ) {
            ++stats.phase1_cp_target_prunes;
            continue;
        }
        if (
            options.cp_target_pruning_enabled
            && slice_perm_target_lower_bound(phase1_tables, child_coord, suffix_cap) > remaining - 1
        ) {
            ++stats.phase1_slice_perm_target_prunes;
            continue;
        }
        if (
            options.cp_slice_target_pruning_enabled
            && cp_slice_target_prunes(phase1_tables, child_coord, suffix_cap, remaining - 1)
        ) {
            ++stats.phase1_cp_slice_target_prunes;
            continue;
        }
        if (
            options.ud_edge_target_pruning_enabled
            && ud_edge_target_prunes(phase1_tables, child_coord, suffix_cap, remaining - 1)
        ) {
            ++stats.phase1_ud_edge_target_prunes;
            continue;
        }
        ++stats.phase1_generated;
        children[child_count++] = {
            lower_bound(phase1_tables, child_coord),
            static_cast<int>(move),
            apply_base(state, kMoves[move]),
            child_coord,
        };
    }
    std::sort(children.begin(), children.begin() + child_count, [](const Child& a, const Child& b) {
        if (a.h != b.h) {
            return a.h < b.h;
        }
        return a.move < b.move;
    });
    for (std::uint32_t index = 0; index < child_count; ++index) {
        stats.phase1_path.push_back(children[index].move);
        search_two_phase_depth(
            phase1_tables,
            phase2_tables,
            options,
            stats,
            deadline,
            children[index].state,
            children[index].coord,
            g + 1,
            depth,
            face_for_move(children[index].move)
        );
        stats.phase1_path.pop_back();
        if (stats.solution_found || stats.timed_out || stats.node_limited) {
            return;
        }
    }
}

void build_phase1_tasks(
    const Phase1Tables& phase1_tables,
    const Options& options,
    TwoPhaseStats& stats,
    std::vector<Phase1Task>& tasks,
    State state,
    Phase1Coord coord,
    int g,
    int depth,
    int split_depth,
    int previous_face,
    std::vector<int>& path
) {
    const int remaining = depth - g;
    if (lower_bound(phase1_tables, coord) > remaining) {
        return;
    }
    if (
        options.three_axis_pruning_enabled
        && g + three_axis_solved_bound(phase1_tables, coord) > options.target_bound
    ) {
        ++stats.phase1_three_axis_prunes;
        return;
    }
    const int suffix_cap = options.target_bound - depth;
    if (
        options.cp_target_pruning_enabled
        && cp_target_lower_bound(phase1_tables, coord, suffix_cap) > remaining
    ) {
        ++stats.phase1_cp_target_prunes;
        return;
    }
    if (
        options.cp_target_pruning_enabled
        && slice_perm_target_lower_bound(phase1_tables, coord, suffix_cap) > remaining
    ) {
        ++stats.phase1_slice_perm_target_prunes;
        return;
    }
    if (
        options.cp_slice_target_pruning_enabled
        && cp_slice_target_prunes(phase1_tables, coord, suffix_cap, remaining)
    ) {
        ++stats.phase1_cp_slice_target_prunes;
        return;
    }
    if (
        options.ud_edge_target_pruning_enabled
        && ud_edge_target_prunes(phase1_tables, coord, suffix_cap, remaining)
    ) {
        ++stats.phase1_ud_edge_target_prunes;
        return;
    }
    if (g >= split_depth || g == depth) {
        tasks.push_back({state, coord, g, previous_face, path});
        return;
    }

    ++stats.phase1_expanded;
    struct Child {
        int h;
        int move;
        State state;
        Phase1Coord coord;
    };
    std::array<Child, 18> children{};
    std::uint32_t child_count = 0;
    for (std::uint32_t move = 0; move < kMoveNames.size(); ++move) {
        const int face = face_for_move(move);
        if (g == 0 && options.root_move_mask_enabled && !options.root_move_allowed[move]) {
            continue;
        }
        if (face == previous_face || commuting_order_violation(previous_face, face)) {
            continue;
        }
        Phase1Coord child_coord{
            phase1_tables.cp_move[coord.cp * kMoveNames.size() + move],
            phase1_tables.slice_perm_move[coord.slice_perm * kMoveNames.size() + move],
            phase1_tables.ud_edge_move.empty()
                ? 0
                : phase1_tables.ud_edge_move[coord.ud_edges * kMoveNames.size() + move],
            phase1_tables.co_move[coord.co * kMoveNames.size() + move],
            phase1_tables.eo_move[coord.eo * kMoveNames.size() + move],
            phase1_tables.slice_move[coord.slice * kMoveNames.size() + move],
        };
        if (lower_bound(phase1_tables, child_coord) > remaining - 1) {
            continue;
        }
        if (options.three_axis_pruning_enabled) {
            const std::uint32_t rl = options.conj_rl[move];
            const std::uint32_t fb = options.conj_fb[move];
            child_coord.co_rl = phase1_tables.co_move[coord.co_rl * kMoveNames.size() + rl];
            child_coord.eo_rl = phase1_tables.eo_move[coord.eo_rl * kMoveNames.size() + rl];
            child_coord.slice_rl = phase1_tables.slice_move[coord.slice_rl * kMoveNames.size() + rl];
            child_coord.co_fb = phase1_tables.co_move[coord.co_fb * kMoveNames.size() + fb];
            child_coord.eo_fb = phase1_tables.eo_move[coord.eo_fb * kMoveNames.size() + fb];
            child_coord.slice_fb = phase1_tables.slice_move[coord.slice_fb * kMoveNames.size() + fb];
            if (g + 1 + three_axis_solved_bound(phase1_tables, child_coord) > options.target_bound) {
                ++stats.phase1_three_axis_prunes;
                continue;
            }
        }
        if (
            options.cp_target_pruning_enabled
            && cp_target_lower_bound(phase1_tables, child_coord, suffix_cap) > remaining - 1
        ) {
            ++stats.phase1_cp_target_prunes;
            continue;
        }
        if (
            options.cp_target_pruning_enabled
            && slice_perm_target_lower_bound(phase1_tables, child_coord, suffix_cap) > remaining - 1
        ) {
            ++stats.phase1_slice_perm_target_prunes;
            continue;
        }
        if (
            options.cp_slice_target_pruning_enabled
            && cp_slice_target_prunes(phase1_tables, child_coord, suffix_cap, remaining - 1)
        ) {
            ++stats.phase1_cp_slice_target_prunes;
            continue;
        }
        if (
            options.ud_edge_target_pruning_enabled
            && ud_edge_target_prunes(phase1_tables, child_coord, suffix_cap, remaining - 1)
        ) {
            ++stats.phase1_ud_edge_target_prunes;
            continue;
        }
        ++stats.phase1_generated;
        children[child_count++] = {
            lower_bound(phase1_tables, child_coord),
            static_cast<int>(move),
            apply_base(state, kMoves[move]),
            child_coord,
        };
    }
    std::sort(children.begin(), children.begin() + child_count, [](const Child& a, const Child& b) {
        if (a.h != b.h) {
            return a.h < b.h;
        }
        return a.move < b.move;
    });
    for (std::uint32_t index = 0; index < child_count; ++index) {
        path.push_back(children[index].move);
        build_phase1_tasks(
            phase1_tables,
            options,
            stats,
            tasks,
            children[index].state,
            children[index].coord,
            g + 1,
            depth,
            split_depth,
            face_for_move(children[index].move),
            path
        );
        path.pop_back();
    }
}

void merge_two_phase_stats(TwoPhaseStats& target, const TwoPhaseStats& source) {
    target.phase1_expanded += source.phase1_expanded;
    target.phase1_generated += source.phase1_generated;
    target.phase1_cp_target_prunes += source.phase1_cp_target_prunes;
    target.phase1_slice_perm_target_prunes += source.phase1_slice_perm_target_prunes;
    target.phase1_three_axis_prunes += source.phase1_three_axis_prunes;
    target.phase1_cp_slice_target_prunes += source.phase1_cp_slice_target_prunes;
    target.phase1_ud_edge_target_prunes += source.phase1_ud_edge_target_prunes;
    target.handoff_count += source.handoff_count;
    target.duplicate_handoff_count += source.duplicate_handoff_count;
    target.phase2_calls += source.phase2_calls;
    target.phase2_expanded += source.phase2_expanded;
    target.phase2_generated += source.phase2_generated;
    target.phase2_lower_bound_rows += source.phase2_lower_bound_rows;
    target.phase2_timeout_rows += source.phase2_timeout_rows;
    target.timed_out = target.timed_out || source.timed_out;
    target.node_limited = target.node_limited || source.node_limited;
    if (source.solution_found && !target.solution_found) {
        target.solution_found = true;
        target.solution_phase1_length = source.solution_phase1_length;
        target.solution_phase2_length = source.solution_phase2_length;
        target.best_phase1_solution = source.best_phase1_solution;
        target.best_phase2_solution = source.best_phase2_solution;
    }
}

void search_two_phase_depth_parallel(
    const Phase1Tables& phase1_tables,
    const Phase2Tables& phase2_tables,
    const Options& options,
    TwoPhaseStats& stats,
    std::chrono::steady_clock::time_point deadline,
    const State& state,
    const Phase1Coord& coord,
    int depth
) {
    const int split_depth = std::min(options.split_depth, depth);
    std::vector<Phase1Task> tasks;
    std::vector<int> path;
    build_phase1_tasks(
        phase1_tables,
        options,
        stats,
        tasks,
        state,
        coord,
        0,
        depth,
        split_depth,
        -1,
        path
    );
    if (tasks.empty()) {
        return;
    }

    std::atomic<std::size_t> next_task{0};
    std::atomic<bool> stop{false};
    const int worker_count = std::max(1, std::min(options.threads, static_cast<int>(tasks.size())));
    std::vector<TwoPhaseStats> worker_stats(static_cast<std::size_t>(worker_count));
    std::vector<std::thread> workers;
    workers.reserve(static_cast<std::size_t>(worker_count));
    for (int worker = 0; worker < worker_count; ++worker) {
        workers.emplace_back([&, worker]() {
            while (!stop.load(std::memory_order_relaxed)) {
                const std::size_t index = next_task.fetch_add(1, std::memory_order_relaxed);
                if (index >= tasks.size()) {
                    return;
                }
                const Phase1Task& task = tasks[index];
                TwoPhaseStats& local = worker_stats[worker];
                local.phase1_path = task.path;
                search_two_phase_depth(
                    phase1_tables,
                    phase2_tables,
                    options,
                    local,
                    deadline,
                    task.state,
                    task.coord,
                    task.g,
                    depth,
                    task.previous_face
                );
                local.phase1_path.clear();
                if (local.solution_found || local.timed_out || local.node_limited) {
                    stop.store(true, std::memory_order_relaxed);
                }
            }
        });
    }
    for (auto& worker : workers) {
        worker.join();
    }
    for (const auto& local : worker_stats) {
        merge_two_phase_stats(stats, local);
    }
}

// ---------------------------------------------------------------------------
// Mike Reid / Cube-Explorer style single-search optimal IDA*.
//
// Instead of the two-phase depth-by-depth enumeration (which re-runs a separate
// pass for every phase-1 length and carries phase-2 handoff machinery), this
// performs ONE bounded IDA* search directly to the solved state over all 18
// moves, using the three-axis phase-1 distance max(p_ud, p_rl, p_fb) as an
// admissible heuristic.  To prove "no solution of length <= target" we run a
// single search at bound = target: if no solved leaf is reached with
// g + h <= target, no solution of that length or less exists.  This avoids the
// redundant depth passes of the two-phase proof driver.
// ---------------------------------------------------------------------------

bool is_solved_state(const State& state) {
    const State solved = solved_state();
    return state.cp == solved.cp && state.co == solved.co
        && state.ep == solved.ep && state.eo == solved.eo;
}

inline Phase1Coord optimal_child_coord(
    const Phase1Tables& tables,
    const Options& options,
    const Phase1Coord& coord,
    int move
) {
    const std::uint32_t m = kMoveNames.size();
    const std::uint32_t rl = options.conj_rl[move];
    const std::uint32_t fb = options.conj_fb[move];
    Phase1Coord child;
    child.co = tables.co_move[coord.co * m + move];
    child.eo = tables.eo_move[coord.eo * m + move];
    child.slice = tables.slice_move[coord.slice * m + move];
    child.co_rl = tables.co_move[coord.co_rl * m + rl];
    child.eo_rl = tables.eo_move[coord.eo_rl * m + rl];
    child.slice_rl = tables.slice_move[coord.slice_rl * m + rl];
    child.co_fb = tables.co_move[coord.co_fb * m + fb];
    child.eo_fb = tables.eo_move[coord.eo_fb * m + fb];
    child.slice_fb = tables.slice_move[coord.slice_fb * m + fb];
    return child;
}

struct OptimalIda {
    const Phase1Tables* tables = nullptr;
    const Options* options = nullptr;
    std::chrono::steady_clock::time_point deadline;
    std::uint64_t node_limit = 0;
    std::uint64_t expanded = 0;
    std::uint64_t generated = 0;
    bool timed_out = false;
    bool node_limited = false;
    bool found = false;
    int found_length = -1;
    std::vector<int> path;
    std::vector<int> solution;
};

// Returns kFound / kTimeout / kNodeLimit, or a positive lower bound on the
// f-value of any leaf below this node that exceeds the current bound.
int search_optimal_ida(
    OptimalIda& s,
    const State& state,
    const Phase1Coord& coord,
    int g,
    int bound,
    int previous_face
) {
    if ((s.expanded & 0x3fffU) == 0 && std::chrono::steady_clock::now() >= s.deadline) {
        s.timed_out = true;
        return kTimeout;
    }
    if (s.node_limit != 0 && s.expanded >= s.node_limit) {
        s.node_limited = true;
        return kNodeLimit;
    }
    const int h = three_axis_solved_bound(*s.tables, coord);
    const int f = g + h;
    if (f > bound) {
        return f;
    }
    if (is_solved_state(state)) {
        s.found = true;
        s.found_length = g;
        s.solution = s.path;
        return kFound;
    }
    ++s.expanded;
    int best = std::numeric_limits<int>::max();
    for (std::uint32_t move = 0; move < kMoveNames.size(); ++move) {
        if (g == 0 && s.options->root_move_mask_enabled && !s.options->root_move_allowed[move]) {
            continue;
        }
        const int face = face_for_move(move);
        if (face == previous_face || commuting_order_violation(previous_face, face)) {
            continue;
        }
        const Phase1Coord child = optimal_child_coord(*s.tables, *s.options, coord, move);
        ++s.generated;
        s.path.push_back(static_cast<int>(move));
        const int outcome = search_optimal_ida(
            s, apply_base(state, kMoves[move]), child, g + 1, bound, face
        );
        s.path.pop_back();
        if (outcome == kFound || outcome == kTimeout || outcome == kNodeLimit) {
            return outcome;
        }
        if (outcome < best) {
            best = outcome;
        }
    }
    return best;
}

struct OptimalTask {
    State state;
    Phase1Coord coord;
    int g = 0;
    int previous_face = -1;
    std::vector<int> path;
};

void build_optimal_tasks(
    const Phase1Tables& tables,
    const Options& options,
    int bound,
    std::vector<OptimalTask>& tasks,
    std::uint64_t& expanded,
    State state,
    Phase1Coord coord,
    int g,
    int split_depth,
    int previous_face,
    std::vector<int>& path
) {
    if (g + three_axis_solved_bound(tables, coord) > bound) {
        return;
    }
    if (g >= split_depth || is_solved_state(state)) {
        tasks.push_back({state, coord, g, previous_face, path});
        return;
    }
    ++expanded;
    for (std::uint32_t move = 0; move < kMoveNames.size(); ++move) {
        if (g == 0 && options.root_move_mask_enabled && !options.root_move_allowed[move]) {
            continue;
        }
        const int face = face_for_move(move);
        if (face == previous_face || commuting_order_violation(previous_face, face)) {
            continue;
        }
        const Phase1Coord child = optimal_child_coord(tables, options, coord, move);
        path.push_back(static_cast<int>(move));
        build_optimal_tasks(
            tables, options, bound, tasks, expanded,
            apply_base(state, kMoves[move]), child, g + 1, split_depth, face, path
        );
        path.pop_back();
    }
}

std::vector<std::uint8_t> parse_csv(const std::string& text, std::size_t expected) {
    std::vector<std::uint8_t> values;
    std::stringstream stream(text);
    std::string token;
    while (std::getline(stream, token, ',')) {
        if (token.empty()) {
            throw std::runtime_error("empty integer token in CSV");
        }
        const long value = std::strtol(token.c_str(), nullptr, 10);
        if (value < 0 || value > 255) {
            throw std::runtime_error("CSV integer outside uint8 range");
        }
        values.push_back(static_cast<std::uint8_t>(value));
    }
    if (values.size() != expected) {
        throw std::runtime_error("CSV field has wrong length");
    }
    return values;
}

template <std::size_t N>
void assign_csv(std::array<std::uint8_t, N>& target, const std::string& text) {
    const auto values = parse_csv(text, N);
    for (std::size_t index = 0; index < N; ++index) {
        target[index] = values[index];
    }
}

int move_index_from_token(const std::string& token) {
    for (std::uint32_t index = 0; index < kMoveNames.size(); ++index) {
        if (token == kMoveNames[index]) {
            return static_cast<int>(index);
        }
    }
    throw std::runtime_error("unknown move token in root mask: " + token);
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

std::array<std::uint8_t, 18> parse_conj_map(const std::string& text) {
    std::array<std::uint8_t, 18> map{};
    std::stringstream stream(text);
    std::string token;
    int count = 0;
    while (std::getline(stream, token, ',')) {
        if (token.empty()) {
            continue;
        }
        if (count >= 18) {
            throw std::runtime_error("conjugation map must have exactly 18 moves");
        }
        map[count++] = static_cast<std::uint8_t>(move_index_from_token(token));
    }
    if (count != 18) {
        throw std::runtime_error("conjugation map must have exactly 18 moves");
    }
    return map;
}

Options parse_args(int argc, char** argv) {
    Options options{solved_state()};
    options.rl_state = solved_state();
    options.fb_state = solved_state();
    for (std::uint32_t i = 0; i < 18; ++i) {
        options.conj_rl[i] = static_cast<std::uint8_t>(i);
        options.conj_fb[i] = static_cast<std::uint8_t>(i);
    }
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        auto need_value = [&](const char* name) -> std::string {
            if (i + 1 >= argc) {
                throw std::runtime_error(std::string("missing value for ") + name);
            }
            return argv[++i];
        };
        if (arg == "--cp") {
            assign_csv(options.state.cp, need_value("--cp"));
        } else if (arg == "--co") {
            assign_csv(options.state.co, need_value("--co"));
        } else if (arg == "--ep") {
            assign_csv(options.state.ep, need_value("--ep"));
        } else if (arg == "--eo") {
            assign_csv(options.state.eo, need_value("--eo"));
        } else if (arg == "--mode") {
            options.mode = need_value("--mode");
        } else if (arg == "--max-depth") {
            options.max_depth = std::stoi(need_value("--max-depth"));
        } else if (arg == "--phase1-start-depth") {
            options.phase1_start_depth = std::stoi(need_value("--phase1-start-depth"));
            if (options.phase1_start_depth < 0) {
                throw std::runtime_error("--phase1-start-depth must be nonnegative");
            }
        } else if (arg == "--phase1-max-depth") {
            options.phase1_max_depth = std::stoi(need_value("--phase1-max-depth"));
        } else if (arg == "--target-bound") {
            options.target_bound = std::stoi(need_value("--target-bound"));
        } else if (arg == "--timeout") {
            options.timeout_seconds = std::stod(need_value("--timeout"));
        } else if (arg == "--node-limit") {
            options.node_limit = static_cast<std::uint64_t>(std::stoull(need_value("--node-limit")));
        } else if (arg == "--phase1-node-limit") {
            options.phase1_node_limit = static_cast<std::uint64_t>(std::stoull(need_value("--phase1-node-limit")));
        } else if (arg == "--phase2-node-limit") {
            options.phase2_node_limit = static_cast<std::uint64_t>(std::stoull(need_value("--phase2-node-limit")));
        } else if (arg == "--root-move-mask") {
            options.root_move_allowed = parse_root_move_mask(need_value("--root-move-mask"));
            options.root_move_mask_enabled = true;
        } else if (arg == "--no-handoff-dedup") {
            options.handoff_dedup_enabled = false;
        } else if (arg == "--no-cp-target-pruning") {
            options.cp_target_pruning_enabled = false;
        } else if (arg == "--phase1-full-pruning") {
            options.phase1_full_pruning_enabled = true;
        } else if (arg == "--phase1-full-pruning-min-depth") {
            options.phase1_full_pruning_min_depth = std::stoi(
                need_value("--phase1-full-pruning-min-depth")
            );
            if (options.phase1_full_pruning_min_depth < 0) {
                throw std::runtime_error("--phase1-full-pruning-min-depth must be nonnegative");
            }
        } else if (arg == "--phase1-full-pruning-max-depth") {
            options.phase1_full_pruning_max_depth = std::stoi(
                need_value("--phase1-full-pruning-max-depth")
            );
            if (options.phase1_full_pruning_max_depth < 0) {
                throw std::runtime_error("--phase1-full-pruning-max-depth must be nonnegative");
            }
        } else if (arg == "--phase1-full-pruning-cache") {
            options.phase1_full_pruning_cache_path = need_value("--phase1-full-pruning-cache");
        } else if (arg == "--sym-phase1-pruning") {
            options.sym_phase1_pruning_enabled = true;
        } else if (arg == "--sym-phase1-max-depth") {
            options.sym_phase1_pruning_max_depth = std::stoi(need_value("--sym-phase1-max-depth"));
            if (options.sym_phase1_pruning_max_depth < 0) {
                throw std::runtime_error("--sym-phase1-max-depth must be nonnegative");
            }
        } else if (arg == "--sym-tables") {
            options.sym_tables_path = need_value("--sym-tables");
        } else if (arg == "--sym-phase1-cache") {
            options.sym_phase1_cache_path = need_value("--sym-phase1-cache");
        } else if (arg == "--raw-phase1-table") {
            options.raw_phase1_table_path = need_value("--raw-phase1-table");
        } else if (arg == "--three-axis-pruning") {
            options.three_axis_pruning_enabled = true;
        } else if (arg == "--conj-rl") {
            options.conj_rl = parse_conj_map(need_value("--conj-rl"));
        } else if (arg == "--conj-fb") {
            options.conj_fb = parse_conj_map(need_value("--conj-fb"));
        } else if (arg == "--cp-rl") {
            assign_csv(options.rl_state.cp, need_value("--cp-rl"));
        } else if (arg == "--co-rl") {
            assign_csv(options.rl_state.co, need_value("--co-rl"));
        } else if (arg == "--ep-rl") {
            assign_csv(options.rl_state.ep, need_value("--ep-rl"));
        } else if (arg == "--eo-rl") {
            assign_csv(options.rl_state.eo, need_value("--eo-rl"));
        } else if (arg == "--cp-fb") {
            assign_csv(options.fb_state.cp, need_value("--cp-fb"));
        } else if (arg == "--co-fb") {
            assign_csv(options.fb_state.co, need_value("--co-fb"));
        } else if (arg == "--ep-fb") {
            assign_csv(options.fb_state.ep, need_value("--ep-fb"));
        } else if (arg == "--eo-fb") {
            assign_csv(options.fb_state.eo, need_value("--eo-fb"));
        } else if (arg == "--cp-slice-target-pruning") {
            options.cp_slice_target_pruning_enabled = true;
        } else if (arg == "--cp-slice-target-min-depth") {
            options.cp_slice_target_min_depth = std::stoi(need_value("--cp-slice-target-min-depth"));
            if (options.cp_slice_target_min_depth < 0) {
                throw std::runtime_error("--cp-slice-target-min-depth must be nonnegative");
            }
        } else if (arg == "--cp-slice-target-cache") {
            options.cp_slice_target_cache_path = need_value("--cp-slice-target-cache");
        } else if (arg == "--ud-edge-target-pruning") {
            options.ud_edge_target_pruning_enabled = true;
        } else if (arg == "--ud-edge-target-min-depth") {
            options.ud_edge_target_min_depth = std::stoi(need_value("--ud-edge-target-min-depth"));
            if (options.ud_edge_target_min_depth < 0) {
                throw std::runtime_error("--ud-edge-target-min-depth must be nonnegative");
            }
        } else if (arg == "--ud-edge-target-cache") {
            options.ud_edge_target_cache_path = need_value("--ud-edge-target-cache");
        } else if (arg == "--threads") {
            options.threads = std::stoi(need_value("--threads"));
            if (options.threads < 1) {
                throw std::runtime_error("--threads must be at least 1");
            }
        } else if (arg == "--split-depth") {
            options.split_depth = std::stoi(need_value("--split-depth"));
            if (options.split_depth < 0) {
                throw std::runtime_error("--split-depth must be nonnegative");
            }
        } else if (arg == "--help") {
            std::cout
                << "Usage: kociemba_phase2_probe --cp CSV --co CSV --ep CSV --eo CSV [options]\n"
                << "Options:\n"
                << "  --mode phase2|two-phase\n"
                << "  --max-depth N\n"
                << "  --phase1-start-depth N\n"
                << "  --phase1-max-depth N\n"
                << "  --target-bound N\n"
                << "  --timeout SECONDS\n"
                << "  --node-limit N\n"
                << "  --root-move-mask MOVES_CSV\n"
                << "  --no-handoff-dedup\n"
                << "  --no-cp-target-pruning\n"
                << "  --phase1-full-pruning\n"
                << "  --phase1-full-pruning-min-depth N\n"
                << "  --phase1-full-pruning-max-depth N\n"
                << "  --phase1-full-pruning-cache PATH\n"
                << "  --sym-phase1-pruning\n"
                << "  --sym-phase1-max-depth N\n"
                << "  --sym-tables PATH\n"
                << "  --sym-phase1-cache PATH\n"
                << "  --raw-phase1-table PATH (verify-sym-phase1 mode)\n"
                << "  --mode verify-sym-phase1\n"
                << "  --three-axis-pruning (needs --sym-phase1-pruning)\n"
                << "  --conj-rl MOVES_CSV  --conj-fb MOVES_CSV\n"
                << "  --cp-rl/--co-rl/--ep-rl/--eo-rl  --cp-fb/--co-fb/--ep-fb/--eo-fb\n"
                << "  --mode optimal-ida (Reid single-bound IDA*; needs sym + three-axis)\n"
                << "  --cp-slice-target-pruning\n"
                << "  --cp-slice-target-min-depth N\n"
                << "  --cp-slice-target-cache PATH\n"
                << "  --ud-edge-target-pruning\n"
                << "  --ud-edge-target-min-depth N\n"
                << "  --ud-edge-target-cache PATH\n"
                << "  --threads N\n"
                << "  --split-depth N\n";
            std::exit(0);
        } else {
            throw std::runtime_error("unknown argument: " + arg);
        }
    }
    return options;
}

std::string json_escape(const std::string& text) {
    std::string out;
    for (const char ch : text) {
        if (ch == '\\' || ch == '"') {
            out.push_back('\\');
        }
        out.push_back(ch);
    }
    return out;
}

void print_json(
    const std::string& status,
    const Solver& solver,
    const Phase2Coord& start,
    int initial_lower_bound,
    int final_bound,
    double runtime_seconds,
    const std::string& error = ""
) {
    std::cout << "{\n";
    std::cout << "  \"schema_version\": 1,\n";
    std::cout << "  \"solver_name\": \"kociemba_phase2_native_probe\",\n";
    std::cout << "  \"status\": \"" << status << "\",\n";
    std::cout << "  \"metric\": \"HTM\",\n";
    std::cout << "  \"phase2_only\": true,\n";
    std::cout << "  \"phase2_pair_pruning_enabled\": true,\n";
    std::cout << "  \"start_cp_coord\": " << start.cp << ",\n";
    std::cout << "  \"start_ud_edge_coord\": " << start.ud << ",\n";
    std::cout << "  \"start_slice_edge_coord\": " << static_cast<int>(start.slice) << ",\n";
    std::cout << "  \"initial_lower_bound\": " << initial_lower_bound << ",\n";
    std::cout << "  \"final_bound\": " << final_bound << ",\n";
    std::cout << "  \"expanded_nodes\": " << solver.expanded << ",\n";
    std::cout << "  \"generated_nodes\": " << solver.generated << ",\n";
    std::cout << "  \"runtime_seconds\": " << runtime_seconds << ",\n";
    std::cout << "  \"solution_length\": ";
    if (solver.solution.empty() && status != "exact") {
        std::cout << "null,\n";
    } else {
        std::cout << solver.solution.size() << ",\n";
    }
    std::cout << "  \"solution_moves\": [";
    for (std::size_t i = 0; i < solver.solution.size(); ++i) {
        if (i != 0) {
            std::cout << ", ";
        }
        std::cout << "\"" << kPhase2MoveNames[solver.solution[i]] << "\"";
    }
    std::cout << "],\n";
    std::cout << "  \"error\": \"" << json_escape(error) << "\"\n";
    std::cout << "}\n";
}

void print_move_names(const std::vector<int>& moves, const std::array<const char*, 18>& names) {
    for (std::size_t i = 0; i < moves.size(); ++i) {
        if (i != 0) {
            std::cout << ", ";
        }
        std::cout << "\"" << names[moves[i]] << "\"";
    }
}

void print_phase2_move_names(const std::vector<int>& moves) {
    for (std::size_t i = 0; i < moves.size(); ++i) {
        if (i != 0) {
            std::cout << ", ";
        }
        std::cout << "\"" << kPhase2MoveNames[moves[i]] << "\"";
    }
}

void print_two_phase_json(
    const std::string& status,
    const TwoPhaseStats& stats,
    const Phase1Coord& start,
    int initial_phase1_lower_bound,
    const Options& options,
    double runtime_seconds,
    const std::string& error = ""
) {
    const bool phase1_exhaustive = options.phase1_start_depth == 0
        && !stats.timed_out
        && !stats.node_limited
        && !stats.solution_found
        && stats.completed_phase1_depth >= options.target_bound;
    const bool proves_no_solution = phase1_exhaustive && stats.phase2_timeout_rows == 0;
    std::cout << "{\n";
    std::cout << "  \"schema_version\": 1,\n";
    std::cout << "  \"solver_name\": \"kociemba_two_phase_native_probe\",\n";
    std::cout << "  \"status\": \"" << status << "\",\n";
    std::cout << "  \"metric\": \"HTM\",\n";
    std::cout << "  \"uses_h48_or_nissy\": false,\n";
    std::cout << "  \"phase1_pair_pruning_enabled\": true,\n";
    std::cout << "  \"phase2_pair_pruning_enabled\": true,\n";
    std::cout << "  \"phase1_cp_target_pruning_enabled\": "
              << (options.cp_target_pruning_enabled ? "true" : "false") << ",\n";
    std::cout << "  \"phase1_full_pruning_enabled\": "
              << (options.phase1_full_pruning_enabled ? "true" : "false") << ",\n";
    std::cout << "  \"phase1_full_pruning_min_depth\": "
              << options.phase1_full_pruning_min_depth << ",\n";
    std::cout << "  \"phase1_full_pruning_requested_max_depth\": "
              << options.phase1_full_pruning_max_depth << ",\n";
    std::cout << "  \"phase1_full_pruning_last_depth\": "
              << stats.phase1_full_pruning_last_depth << ",\n";
    std::cout << "  \"phase1_full_pruning_max_distance\": "
              << stats.phase1_full_pruning_max_distance << ",\n";
    std::cout << "  \"phase1_full_pruning_complete\": "
              << (stats.phase1_full_pruning_complete ? "true" : "false") << ",\n";
    std::cout << "  \"phase1_full_pruning_cache_hit\": "
              << (stats.phase1_full_pruning_cache_hit ? "true" : "false") << ",\n";
    std::cout << "  \"sym_phase1_pruning_enabled\": "
              << (options.sym_phase1_pruning_enabled ? "true" : "false") << ",\n";
    std::cout << "  \"sym_phase1_requested_max_depth\": "
              << options.sym_phase1_pruning_max_depth << ",\n";
    std::cout << "  \"sym_phase1_last_depth\": " << stats.sym_phase1_last_depth << ",\n";
    std::cout << "  \"sym_phase1_max_distance\": " << stats.sym_phase1_max_distance << ",\n";
    std::cout << "  \"sym_phase1_complete\": "
              << (stats.sym_phase1_complete ? "true" : "false") << ",\n";
    std::cout << "  \"sym_phase1_cache_hit\": "
              << (stats.sym_phase1_cache_hit ? "true" : "false") << ",\n";
    std::cout << "  \"sym_phase1_states\": " << stats.sym_phase1_last_states << ",\n";
    std::cout << "  \"sym_phase1_build_seconds\": " << stats.sym_phase1_build_seconds << ",\n";
    std::cout << "  \"sym_phase1_load_seconds\": " << stats.sym_phase1_load_seconds << ",\n";
    std::cout << "  \"three_axis_pruning_enabled\": "
              << (options.three_axis_pruning_enabled ? "true" : "false") << ",\n";
    std::cout << "  \"phase1_three_axis_prunes\": " << stats.phase1_three_axis_prunes << ",\n";
    std::cout << "  \"phase1_cp_slice_target_pruning_enabled\": "
              << (options.cp_slice_target_pruning_enabled ? "true" : "false") << ",\n";
    std::cout << "  \"phase1_cp_slice_target_min_depth\": "
              << options.cp_slice_target_min_depth << ",\n";
    std::cout << "  \"phase1_cp_slice_target_last_cap\": "
              << stats.phase1_cp_slice_target_last_cap << ",\n";
    std::cout << "  \"phase1_cp_slice_target_last_depth\": "
              << stats.phase1_cp_slice_target_last_depth << ",\n";
    std::cout << "  \"phase1_cp_slice_target_max_distance\": "
              << stats.phase1_cp_slice_target_max_distance << ",\n";
    std::cout << "  \"phase1_cp_slice_target_complete\": "
              << (stats.phase1_cp_slice_target_complete ? "true" : "false") << ",\n";
    std::cout << "  \"phase1_cp_slice_target_cache_hit\": "
              << (stats.phase1_cp_slice_target_cache_hit ? "true" : "false") << ",\n";
    std::cout << "  \"phase1_ud_edge_target_pruning_enabled\": "
              << (options.ud_edge_target_pruning_enabled ? "true" : "false") << ",\n";
    std::cout << "  \"phase1_ud_edge_target_min_depth\": "
              << options.ud_edge_target_min_depth << ",\n";
    std::cout << "  \"phase1_ud_edge_target_last_cap\": "
              << stats.phase1_ud_edge_target_last_cap << ",\n";
    std::cout << "  \"phase1_ud_edge_target_last_depth\": "
              << stats.phase1_ud_edge_target_last_depth << ",\n";
    std::cout << "  \"phase1_ud_edge_target_max_distance\": "
              << stats.phase1_ud_edge_target_max_distance << ",\n";
    std::cout << "  \"phase1_ud_edge_target_complete\": "
              << (stats.phase1_ud_edge_target_complete ? "true" : "false") << ",\n";
    std::cout << "  \"phase1_ud_edge_target_cache_hit\": "
              << (stats.phase1_ud_edge_target_cache_hit ? "true" : "false") << ",\n";
    std::cout << "  \"target_bound\": " << options.target_bound << ",\n";
    std::cout << "  \"phase1_start_depth\": " << options.phase1_start_depth << ",\n";
    std::cout << "  \"phase1_max_depth\": " << options.phase1_max_depth << ",\n";
    int root_move_count = 0;
    if (options.root_move_mask_enabled) {
        for (const bool allowed : options.root_move_allowed) {
            if (allowed) {
                ++root_move_count;
            }
        }
    }
    std::cout << "  \"root_move_mask_enabled\": "
              << (options.root_move_mask_enabled ? "true" : "false") << ",\n";
    std::cout << "  \"root_move_count\": "
              << (options.root_move_mask_enabled ? root_move_count : 18) << ",\n";
    std::cout << "  \"handoff_dedup_enabled\": "
              << (options.handoff_dedup_enabled ? "true" : "false") << ",\n";
    std::cout << "  \"threads\": " << options.threads << ",\n";
    std::cout << "  \"split_depth\": " << options.split_depth << ",\n";
    std::cout << "  \"phase1_exhaustive_for_target_bound\": " << (phase1_exhaustive ? "true" : "false") << ",\n";
    std::cout << "  \"proves_no_solution_at_or_below_target\": " << (proves_no_solution ? "true" : "false") << ",\n";
    std::cout << "  \"start_corner_orientation_coord\": " << start.co << ",\n";
    std::cout << "  \"start_corner_permutation_coord\": " << start.cp << ",\n";
    std::cout << "  \"start_labeled_ud_slice_coord\": " << start.slice_perm << ",\n";
    std::cout << "  \"start_edge_orientation_coord\": " << start.eo << ",\n";
    std::cout << "  \"start_ud_slice_coord\": " << start.slice << ",\n";
    std::cout << "  \"initial_phase1_lower_bound\": " << initial_phase1_lower_bound << ",\n";
    std::cout << "  \"completed_phase1_depth\": " << stats.completed_phase1_depth << ",\n";
    std::cout << "  \"current_phase1_depth\": " << stats.current_phase1_depth << ",\n";
    std::cout << "  \"phase1_expanded_nodes\": " << stats.phase1_expanded << ",\n";
    std::cout << "  \"phase1_generated_nodes\": " << stats.phase1_generated << ",\n";
    std::cout << "  \"phase1_cp_target_prunes\": " << stats.phase1_cp_target_prunes << ",\n";
    std::cout << "  \"phase1_slice_perm_target_prunes\": " << stats.phase1_slice_perm_target_prunes << ",\n";
    std::cout << "  \"phase1_cp_slice_target_prunes\": " << stats.phase1_cp_slice_target_prunes << ",\n";
    std::cout << "  \"phase1_ud_edge_target_prunes\": " << stats.phase1_ud_edge_target_prunes << ",\n";
    std::cout << "  \"phase1_full_pruning_table_builds\": "
              << stats.phase1_full_pruning_table_builds << ",\n";
    std::cout << "  \"phase1_full_pruning_last_states\": "
              << stats.phase1_full_pruning_last_states << ",\n";
    std::cout << "  \"phase1_full_pruning_build_seconds\": "
              << stats.phase1_full_pruning_build_seconds << ",\n";
    std::cout << "  \"phase1_full_pruning_load_seconds\": "
              << stats.phase1_full_pruning_load_seconds << ",\n";
    std::cout << "  \"phase1_cp_slice_target_table_builds\": "
              << stats.phase1_cp_slice_target_table_builds << ",\n";
    std::cout << "  \"phase1_cp_slice_target_last_targets\": "
              << stats.phase1_cp_slice_target_last_targets << ",\n";
    std::cout << "  \"phase1_cp_slice_target_last_states\": "
              << stats.phase1_cp_slice_target_last_states << ",\n";
    std::cout << "  \"phase1_cp_slice_target_build_seconds\": "
              << stats.phase1_cp_slice_target_build_seconds << ",\n";
    std::cout << "  \"phase1_cp_slice_target_load_seconds\": "
              << stats.phase1_cp_slice_target_load_seconds << ",\n";
    std::cout << "  \"phase1_ud_edge_target_table_builds\": "
              << stats.phase1_ud_edge_target_table_builds << ",\n";
    std::cout << "  \"phase1_ud_edge_target_last_targets\": "
              << stats.phase1_ud_edge_target_last_targets << ",\n";
    std::cout << "  \"phase1_ud_edge_target_last_states\": "
              << stats.phase1_ud_edge_target_last_states << ",\n";
    std::cout << "  \"phase1_ud_edge_target_build_seconds\": "
              << stats.phase1_ud_edge_target_build_seconds << ",\n";
    std::cout << "  \"phase1_ud_edge_target_load_seconds\": "
              << stats.phase1_ud_edge_target_load_seconds << ",\n";
    std::cout << "  \"handoff_count\": " << stats.handoff_count << ",\n";
    std::cout << "  \"duplicate_handoff_count\": " << stats.duplicate_handoff_count << ",\n";
    std::cout << "  \"distinct_g1_states_seen\": " << stats.seen_g1_depths.size() << ",\n";
    std::cout << "  \"phase2_calls\": " << stats.phase2_calls << ",\n";
    std::cout << "  \"phase2_expanded_nodes\": " << stats.phase2_expanded << ",\n";
    std::cout << "  \"phase2_generated_nodes\": " << stats.phase2_generated << ",\n";
    std::cout << "  \"phase2_lower_bound_rows\": " << stats.phase2_lower_bound_rows << ",\n";
    std::cout << "  \"phase2_timeout_rows\": " << stats.phase2_timeout_rows << ",\n";
    std::cout << "  \"timed_out\": " << (stats.timed_out ? "true" : "false") << ",\n";
    std::cout << "  \"node_limited\": " << (stats.node_limited ? "true" : "false") << ",\n";
    std::cout << "  \"runtime_seconds\": " << runtime_seconds << ",\n";
    std::cout << "  \"solution_found\": " << (stats.solution_found ? "true" : "false") << ",\n";
    std::cout << "  \"solution_length\": ";
    if (stats.solution_found) {
        std::cout << (stats.solution_phase1_length + stats.solution_phase2_length) << ",\n";
    } else {
        std::cout << "null,\n";
    }
    std::cout << "  \"solution_phase1_length\": " << stats.solution_phase1_length << ",\n";
    std::cout << "  \"solution_phase2_length\": " << stats.solution_phase2_length << ",\n";
    std::cout << "  \"phase1_solution_moves\": [";
    print_move_names(stats.best_phase1_solution, kMoveNames);
    std::cout << "],\n";
    std::cout << "  \"phase2_solution_moves\": [";
    print_phase2_move_names(stats.best_phase2_solution);
    std::cout << "],\n";
    std::cout << "  \"error\": \"" << json_escape(error) << "\"\n";
    std::cout << "}\n";
}

}  // namespace

int main(int argc, char** argv) {
    const auto begin = std::chrono::steady_clock::now();
    Phase2Coord start{};
    Solver solver;
    int initial_lower_bound = 0;
    int final_bound = 0;
    try {
        Options options = parse_args(argc, argv);
        if (options.phase2_node_limit == 0 && options.node_limit != 0) {
            options.phase2_node_limit = options.node_limit;
        }
        if (options.phase1_node_limit == 0 && options.node_limit != 0) {
            options.phase1_node_limit = options.node_limit;
        }
        // The handoff-dedup hash table is only used by the two-phase proof
        // driver; optimal-ida (Reid IDA*) and verify modes have no handoffs.
        const bool uses_handoff_dedup = options.mode == "two-phase" || options.mode == "phase2";
        if (options.threads > 1 && uses_handoff_dedup && options.handoff_dedup_enabled) {
            throw std::runtime_error("--threads > 1 requires --no-handoff-dedup");
        }
        if (options.threads > 1 && uses_handoff_dedup && options.phase1_node_limit != 0) {
            throw std::runtime_error("--threads > 1 requires --phase1-node-limit 0");
        }
        const Phase2Tables tables = build_phase2_tables();
        if (options.mode == "two-phase") {
            const int max_phase1_depth = std::min(options.phase1_max_depth, options.target_bound);
            Phase1Tables phase1_tables = build_phase1_tables();
            TwoPhaseStats stats;
            if (
                options.phase1_full_pruning_enabled
                && max_phase1_depth >= options.phase1_full_pruning_min_depth
            ) {
                set_phase1_full_pruning_table(
                    phase1_tables,
                    stats,
                    options.phase1_full_pruning_max_depth,
                    options.phase1_full_pruning_cache_path
                );
            }
            if (options.sym_phase1_pruning_enabled) {
                set_sym_phase1_pruning_table(
                    phase1_tables,
                    stats,
                    options.sym_phase1_pruning_max_depth,
                    options.sym_tables_path,
                    options.sym_phase1_cache_path
                );
            }
            if (
                options.ud_edge_target_pruning_enabled
                && max_phase1_depth >= options.ud_edge_target_min_depth
            ) {
                add_ud_edge_move_table(phase1_tables);
            }
            if (options.cp_target_pruning_enabled) {
                add_cp_target_pruning_tables(phase1_tables, tables, options.target_bound);
                add_slice_perm_target_pruning_tables(phase1_tables, tables, options.target_bound);
            }
            if (options.three_axis_pruning_enabled && phase1_tables.sym_dist.empty()) {
                throw std::runtime_error("--three-axis-pruning requires --sym-phase1-pruning");
            }
            Phase1Coord phase1_start = encode_phase1(options.state);
            if (options.three_axis_pruning_enabled) {
                phase1_start.co_rl = encode_corner_orientation(options.rl_state);
                phase1_start.eo_rl = encode_edge_orientation(options.rl_state);
                phase1_start.slice_rl = encode_ud_slice_combination(options.rl_state);
                phase1_start.co_fb = encode_corner_orientation(options.fb_state);
                phase1_start.eo_fb = encode_edge_orientation(options.fb_state);
                phase1_start.slice_fb = encode_ud_slice_combination(options.fb_state);
            }
            const int initial_phase1_lower_bound = lower_bound(phase1_tables, phase1_start);
            const auto deadline = begin + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                std::chrono::duration<double>(options.timeout_seconds)
            );
            const int start_phase1_depth = std::min(options.phase1_start_depth, max_phase1_depth);
            for (int depth = start_phase1_depth; depth <= max_phase1_depth; ++depth) {
                stats.current_phase1_depth = depth;
                if (initial_phase1_lower_bound > depth) {
                    stats.completed_phase1_depth = depth;
                    continue;
                }
                if (
                    options.cp_slice_target_pruning_enabled
                    && depth >= options.cp_slice_target_min_depth
                ) {
                    set_cp_slice_target_pruning_table(
                        phase1_tables,
                        tables,
                        stats,
                        options.target_bound - depth,
                        depth,
                        options.cp_slice_target_cache_path
                    );
                } else {
                    clear_cp_slice_target_pruning_table(phase1_tables);
                }
                if (
                    options.ud_edge_target_pruning_enabled
                    && depth >= options.ud_edge_target_min_depth
                ) {
                    set_ud_edge_target_pruning_table(
                        phase1_tables,
                        tables,
                        stats,
                        options.target_bound - depth,
                        depth,
                        options.ud_edge_target_cache_path
                    );
                } else {
                    clear_ud_edge_target_pruning_table(phase1_tables);
                }
                if (options.threads > 1 && options.split_depth > 0) {
                    search_two_phase_depth_parallel(
                        phase1_tables,
                        tables,
                        options,
                        stats,
                        deadline,
                        options.state,
                        phase1_start,
                        depth
                    );
                } else {
                    search_two_phase_depth(
                        phase1_tables,
                        tables,
                        options,
                        stats,
                        deadline,
                        options.state,
                        phase1_start,
                        0,
                        depth,
                        -1
                    );
                }
                if (stats.solution_found || stats.timed_out || stats.node_limited) {
                    break;
                }
                stats.completed_phase1_depth = depth;
            }
            const double runtime = std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
            std::string status = "lower_bound";
            if (stats.solution_found) {
                status = "solution_found";
            } else if (stats.timed_out || stats.node_limited) {
                status = "timeout";
            } else if (stats.completed_phase1_depth >= options.target_bound && stats.phase2_timeout_rows == 0) {
                status = "lower_bound";
            }
            print_two_phase_json(status, stats, phase1_start, initial_phase1_lower_bound, options, runtime);
            return 0;
        }
        if (options.mode == "optimal-ida") {
            if (!options.sym_phase1_pruning_enabled) {
                throw std::runtime_error("--mode optimal-ida requires --sym-phase1-pruning");
            }
            if (!options.three_axis_pruning_enabled) {
                throw std::runtime_error("--mode optimal-ida requires --three-axis-pruning");
            }
            Phase1Tables phase1_tables = build_phase1_tables();
            TwoPhaseStats setup_stats;
            set_sym_phase1_pruning_table(
                phase1_tables,
                setup_stats,
                options.sym_phase1_pruning_max_depth,
                options.sym_tables_path,
                options.sym_phase1_cache_path
            );
            Phase1Coord start = encode_phase1(options.state);
            start.co_rl = encode_corner_orientation(options.rl_state);
            start.eo_rl = encode_edge_orientation(options.rl_state);
            start.slice_rl = encode_ud_slice_combination(options.rl_state);
            start.co_fb = encode_corner_orientation(options.fb_state);
            start.eo_fb = encode_edge_orientation(options.fb_state);
            start.slice_fb = encode_ud_slice_combination(options.fb_state);
            const int root_h = three_axis_solved_bound(phase1_tables, start);
            const int bound = options.target_bound;
            const auto deadline = begin + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                std::chrono::duration<double>(options.timeout_seconds)
            );
            std::vector<OptimalTask> tasks;
            std::vector<int> build_path;
            std::uint64_t build_expanded = 0;
            const int split = std::max(0, std::min(options.split_depth, bound));
            build_optimal_tasks(
                phase1_tables, options, bound, tasks, build_expanded,
                options.state, start, 0, split, -1, build_path
            );
            std::uint64_t expanded = build_expanded;
            std::uint64_t generated = 0;
            bool found = false;
            bool timed_out = false;
            bool node_limited = false;
            int solution_length = -1;
            std::vector<int> solution;
            const int worker_count = std::max(1, std::min(options.threads, static_cast<int>(tasks.size())));
            if (!tasks.empty()) {
                std::atomic<std::size_t> next_task{0};
                std::atomic<bool> stop{false};
                std::vector<OptimalIda> worker(static_cast<std::size_t>(worker_count));
                std::vector<std::thread> threads;
                threads.reserve(static_cast<std::size_t>(worker_count));
                for (int w = 0; w < worker_count; ++w) {
                    threads.emplace_back([&, w]() {
                        OptimalIda& s = worker[static_cast<std::size_t>(w)];
                        s.tables = &phase1_tables;
                        s.options = &options;
                        s.deadline = deadline;
                        s.node_limit = options.phase1_node_limit;
                        while (!stop.load(std::memory_order_relaxed)) {
                            const std::size_t index = next_task.fetch_add(1, std::memory_order_relaxed);
                            if (index >= tasks.size()) {
                                return;
                            }
                            const OptimalTask& task = tasks[index];
                            s.path = task.path;
                            const int outcome = search_optimal_ida(
                                s, task.state, task.coord, task.g, bound, task.previous_face
                            );
                            if (outcome == kFound || s.timed_out || s.node_limited) {
                                stop.store(true, std::memory_order_relaxed);
                            }
                        }
                    });
                }
                for (auto& t : threads) {
                    t.join();
                }
                for (const auto& s : worker) {
                    expanded += s.expanded;
                    generated += s.generated;
                    timed_out = timed_out || s.timed_out;
                    node_limited = node_limited || s.node_limited;
                    if (s.found && !found) {
                        found = true;
                        solution_length = s.found_length;
                        solution = s.solution;
                    }
                }
            }
            const bool exhausted = !found && !timed_out && !node_limited;
            const bool proves_no_solution = exhausted;
            const double runtime = std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
            std::string status = found ? "solution_found"
                : ((timed_out || node_limited) ? "timeout" : "lower_bound");
            std::cout << "{\n";
            std::cout << "  \"schema_version\": 1,\n";
            std::cout << "  \"solver_name\": \"kociemba_reid_optimal_ida\",\n";
            std::cout << "  \"mode\": \"optimal-ida\",\n";
            std::cout << "  \"metric\": \"HTM\",\n";
            std::cout << "  \"uses_h48_or_nissy\": false,\n";
            std::cout << "  \"status\": \"" << status << "\",\n";
            std::cout << "  \"sym_phase1_pruning_enabled\": true,\n";
            std::cout << "  \"three_axis_pruning_enabled\": true,\n";
            std::cout << "  \"sym_phase1_max_distance\": " << phase1_tables.sym_dist_max_distance << ",\n";
            std::cout << "  \"sym_phase1_load_seconds\": " << setup_stats.sym_phase1_load_seconds << ",\n";
            std::cout << "  \"sym_phase1_build_seconds\": " << setup_stats.sym_phase1_build_seconds << ",\n";
            std::cout << "  \"target_bound\": " << bound << ",\n";
            std::cout << "  \"root_three_axis_lower_bound\": " << root_h << ",\n";
            std::cout << "  \"split_depth\": " << split << ",\n";
            std::cout << "  \"threads\": " << options.threads << ",\n";
            std::cout << "  \"task_count\": " << tasks.size() << ",\n";
            std::cout << "  \"expanded_nodes\": " << expanded << ",\n";
            std::cout << "  \"generated_nodes\": " << generated << ",\n";
            std::cout << "  \"timed_out\": " << (timed_out ? "true" : "false") << ",\n";
            std::cout << "  \"node_limited\": " << (node_limited ? "true" : "false") << ",\n";
            std::cout << "  \"solution_found\": " << (found ? "true" : "false") << ",\n";
            std::cout << "  \"solution_length\": ";
            if (found) {
                std::cout << solution_length << ",\n";
            } else {
                std::cout << "null,\n";
            }
            std::cout << "  \"solution_moves\": [";
            print_move_names(solution, kMoveNames);
            std::cout << "],\n";
            std::cout << "  \"proves_no_solution_at_or_below_target\": "
                      << (proves_no_solution ? "true" : "false") << ",\n";
            std::cout << "  \"runtime_seconds\": " << runtime << "\n";
            std::cout << "}\n";
            return 0;
        }
        if (options.mode == "verify-sym-phase1") {
            Phase1Tables phase1_tables = build_phase1_tables();
            TwoPhaseStats stats;
            set_sym_phase1_pruning_table(
                phase1_tables,
                stats,
                options.sym_phase1_pruning_max_depth,
                options.sym_tables_path,
                options.sym_phase1_cache_path
            );
            // Superflip phase-1 coordinate: CO=0, EO all flipped (2047), slice solved.
            const int superflip_sym_dist = sym_phase1_dist(phase1_tables, 0, 2047, kUDSliceSolvedCoord);
            // Solved must be distance 0.
            const int solved_sym_dist = sym_phase1_dist(phase1_tables, 0, 0, kUDSliceSolvedCoord);
            std::uint64_t compared = 0;
            std::uint64_t mismatches = 0;
            std::uint64_t first_mismatch_index = 0;
            int first_mismatch_raw = -1;
            int first_mismatch_sym = -1;
            bool raw_loaded = false;
            if (!options.raw_phase1_table_path.empty()) {
                BoundedTargetTable raw;
                if (load_phase1_full_pruning_dist(options.raw_phase1_table_path, 0, raw)) {
                    raw_loaded = true;
                    for (std::uint32_t index = 0; index < kPhase1FullCount; ++index) {
                        const std::uint8_t raw_value = raw.dist[index];
                        if (raw_value == 0xff) {
                            continue;
                        }
                        const std::uint32_t slice = index % kUDSliceCombinationCount;
                        const std::uint32_t orientation = index / kUDSliceCombinationCount;
                        const std::uint32_t eo = orientation % kEdgeOrientationCount;
                        const std::uint32_t co = orientation / kEdgeOrientationCount;
                        const std::uint8_t sym_value =
                            phase1_tables.sym_dist[sym_phase1_reduced_index(phase1_tables, co, eo, slice)];
                        ++compared;
                        if (sym_value != raw_value) {
                            if (mismatches == 0) {
                                first_mismatch_index = index;
                                first_mismatch_raw = raw_value;
                                first_mismatch_sym = sym_value;
                            }
                            ++mismatches;
                        }
                    }
                }
            }
            const double runtime = std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
            std::cout << "{\n";
            std::cout << "  \"schema_version\": 1,\n";
            std::cout << "  \"solver_name\": \"kociemba_sym_phase1_verify\",\n";
            std::cout << "  \"mode\": \"verify-sym-phase1\",\n";
            std::cout << "  \"uses_h48_or_nissy\": false,\n";
            std::cout << "  \"sym_phase1_class_count\": " << kFlipUDSliceClassCount << ",\n";
            std::cout << "  \"sym_phase1_domain\": " << kSymPhase1Count << ",\n";
            std::cout << "  \"sym_phase1_max_depth_requested\": " << options.sym_phase1_pruning_max_depth << ",\n";
            std::cout << "  \"sym_phase1_max_distance\": " << phase1_tables.sym_dist_max_distance << ",\n";
            std::cout << "  \"sym_phase1_complete\": " << (phase1_tables.sym_dist_complete ? "true" : "false") << ",\n";
            std::cout << "  \"sym_phase1_states\": " << stats.sym_phase1_last_states << ",\n";
            std::cout << "  \"sym_phase1_build_seconds\": " << stats.sym_phase1_build_seconds << ",\n";
            std::cout << "  \"sym_phase1_load_seconds\": " << stats.sym_phase1_load_seconds << ",\n";
            std::cout << "  \"sym_phase1_cache_hit\": " << (stats.sym_phase1_cache_hit ? "true" : "false") << ",\n";
            std::cout << "  \"solved_sym_dist\": " << solved_sym_dist << ",\n";
            std::cout << "  \"superflip_phase1_sym_dist\": " << superflip_sym_dist << ",\n";
            std::cout << "  \"raw_table_path\": \"" << json_escape(options.raw_phase1_table_path) << "\",\n";
            std::cout << "  \"raw_table_loaded\": " << (raw_loaded ? "true" : "false") << ",\n";
            std::cout << "  \"compared_entries\": " << compared << ",\n";
            std::cout << "  \"mismatches\": " << mismatches << ",\n";
            std::cout << "  \"first_mismatch_index\": " << first_mismatch_index << ",\n";
            std::cout << "  \"first_mismatch_raw\": " << first_mismatch_raw << ",\n";
            std::cout << "  \"first_mismatch_sym\": " << first_mismatch_sym << ",\n";
            std::cout << "  \"matches_raw_on_all_known\": "
                      << ((raw_loaded && mismatches == 0 && compared > 0) ? "true" : "false") << ",\n";
            std::cout << "  \"runtime_seconds\": " << runtime << "\n";
            std::cout << "}\n";
            return 0;
        }
        if (options.mode != "phase2") {
            throw std::runtime_error("unknown --mode value: " + options.mode);
        }
        start = encode_phase2(options.state);
        initial_lower_bound = lower_bound(tables, start);
        final_bound = initial_lower_bound;
        solver.tables = &tables;
        solver.deadline = begin + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
            std::chrono::duration<double>(options.timeout_seconds)
        );
        solver.node_limit = options.node_limit;

        if (initial_lower_bound > options.max_depth) {
            const double runtime = std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
            print_json("lower_bound", solver, start, initial_lower_bound, options.max_depth, runtime);
            return 0;
        }
        int bound = initial_lower_bound;
        while (bound <= options.max_depth) {
            solver.path.clear();
            const int outcome = search(solver, start, 0, bound, -1);
            final_bound = bound;
            if (outcome == kFound) {
                const double runtime = std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
                print_json("exact", solver, start, initial_lower_bound, bound, runtime);
                return 0;
            }
            if (outcome == kTimeout || solver.timed_out) {
                const double runtime = std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
                print_json("timeout", solver, start, initial_lower_bound, bound, runtime);
                return 0;
            }
            if (outcome == kNodeLimit || solver.node_limited) {
                const double runtime = std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
                print_json("timeout", solver, start, initial_lower_bound, bound, runtime, "node limit reached");
                return 0;
            }
            if (outcome == std::numeric_limits<int>::max()) {
                break;
            }
            bound = outcome;
        }
        const double runtime = std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
        print_json("lower_bound", solver, start, initial_lower_bound, final_bound, runtime);
        return 0;
    } catch (const std::exception& exc) {
        const double runtime = std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
        print_json("failed", solver, start, initial_lower_bound, final_bound, runtime, exc.what());
        return 1;
    }
}
