// Native generator for 3x3 edge pattern databases (6- or 7-edge subsets).
//
// The abstraction tracks a chosen subset of N edge cubies (N in {6, 7}): their
// occupied positions, their permutation among those positions, and their
// orientations. The coordinate size is C(12, N) * N! * 2^N states, indexed by a
// single uint32:
//   N = 6 -> C(12,6) * 6! * 2^6 =  42,577,920 states (legacy, byte-compatible)
//   N = 7 -> C(12,7) * 7! * 2^7 = 510,935,040 states
//
// The on-disk header layout is IDENTICAL across N. The (packed) subset_edges[6]
// and reserved[2] fields form 8 contiguous bytes, so up to 8 edge ids fit; the
// subset_size field disambiguates how many are meaningful (and which set of
// dimension constants applies). A 6-edge database produced by this generator is
// therefore byte-for-byte compatible with the pre-existing 6-edge format.
//
// 8-edge subsets are intentionally rejected: C(12,8) * 8! * 2^8 overflows uint32.

#include <algorithm>
#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <fstream>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr std::uint32_t kEdgePositionCount = 12;
constexpr std::uint32_t kMinSubsetSize = 6;
constexpr std::uint32_t kMaxSubsetSize = 7;  // 8 would overflow the uint32 coordinate
constexpr std::uint8_t kUnvisited = 0xff;
constexpr std::uint32_t kNoDepthLimit = std::numeric_limits<std::uint32_t>::max();
constexpr std::array<const char*, 18> kMoveNames = {
    "U", "U'", "U2", "R", "R'", "R2", "F", "F'", "F2",
    "D", "D'", "D2", "L", "L'", "L2", "B", "B'", "B2",
};

struct BaseMove {
    std::array<std::uint8_t, 12> ep;
    std::array<std::uint8_t, 12> eo;
};

constexpr std::array<BaseMove, 6> kBaseMoves = {{
    {{{3, 0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11}}, {{0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}}}, // U
    {{{8, 1, 2, 3, 11, 5, 6, 7, 4, 9, 10, 0}}, {{0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}}}, // R
    {{{0, 9, 2, 3, 4, 8, 6, 7, 1, 5, 10, 11}}, {{0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 0}}}, // F
    {{{0, 1, 2, 3, 5, 6, 7, 4, 8, 9, 10, 11}}, {{0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}}}, // D
    {{{0, 1, 10, 3, 4, 5, 9, 7, 8, 2, 6, 11}}, {{0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}}}, // L
    {{{0, 1, 2, 11, 4, 5, 6, 10, 8, 9, 3, 7}}, {{0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1}}}, // B
}};

#pragma pack(push, 1)
struct Header {
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
static_assert(sizeof(Header) == 72, "edge PDB header layout must stay 72 bytes");
// subset_edges[6] and reserved[2] are adjacent under pack(1): 8 contiguous bytes.
static_assert(offsetof(Header, reserved) == offsetof(Header, subset_edges) + 6,
              "subset_edges and reserved must be contiguous to hold a 7-edge subset");

struct AbstractEdgeState {
    std::array<std::uint8_t, 12> position_piece{};
    std::array<std::uint8_t, 12> orientation{};
};

struct Options {
    std::string output_path;
    std::vector<std::uint8_t> subset_edges = {0, 1, 2, 3, 4, 5};
    std::array<std::uint8_t, 18> move_costs{};
    std::string subset_label = "0_1_2_3_4_5";
    std::uint32_t max_depth = kNoDepthLimit;

    Options() {
        move_costs.fill(1);
    }

    std::uint32_t subset_size() const {
        return static_cast<std::uint32_t>(subset_edges.size());
    }
};

// Combinatorial dimensions derived from the subset size. Computed once per run
// (this generator is a one-shot BFS, not a hot path), so plain runtime math is
// fine and keeps the coordinate logic uniform across N.
struct Dimensions {
    std::uint32_t subset_size;
    std::uint32_t combination_count;  // C(12, N)
    std::uint32_t permutation_count;  // N!
    std::uint32_t orientation_count;  // 2^N
    std::uint32_t state_count;        // product of the three above
};

std::uint64_t choose(std::uint32_t n, std::uint32_t k) {
    if (k > n) {
        return 0;
    }
    k = std::min(k, n - k);
    std::uint64_t result = 1;
    for (std::uint32_t i = 0; i < k; ++i) {
        result = result * (n - i) / (i + 1);
    }
    return result;
}

std::uint64_t factorial(std::uint32_t n) {
    std::uint64_t result = 1;
    for (std::uint32_t i = 2; i <= n; ++i) {
        result *= i;
    }
    return result;
}

// Precomputed small tables so the BFS hot loop does no per-call arithmetic and,
// critically, no per-call heap allocation. Indices used: kFact[k] for k <= 6,
// kChoose[n][k] for n <= 11, k <= subset_size-1 <= 6 -- all in range below.
std::array<std::uint64_t, kMaxSubsetSize + 1> build_factorial_table() {
    std::array<std::uint64_t, kMaxSubsetSize + 1> values{};
    values[0] = 1;
    for (std::uint32_t i = 1; i <= kMaxSubsetSize; ++i) {
        values[i] = values[i - 1] * i;
    }
    return values;
}
const auto kFact = build_factorial_table();

std::array<std::array<std::uint32_t, kMaxSubsetSize + 1>, kEdgePositionCount + 1> build_choose_table() {
    std::array<std::array<std::uint32_t, kMaxSubsetSize + 1>, kEdgePositionCount + 1> values{};
    for (std::uint32_t n = 0; n <= kEdgePositionCount; ++n) {
        values[n][0] = 1;
        for (std::uint32_t k = 1; k <= kMaxSubsetSize; ++k) {
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
const auto kChoose = build_choose_table();

using SubsetArray = std::array<std::uint8_t, kMaxSubsetSize>;

Dimensions dimensions_for(std::uint32_t subset_size) {
    if (subset_size < kMinSubsetSize || subset_size > kMaxSubsetSize) {
        throw std::runtime_error("subset size must be 6 or 7");
    }
    const std::uint64_t combinations = choose(kEdgePositionCount, subset_size);
    const std::uint64_t permutations = factorial(subset_size);
    const std::uint64_t orientations = 1ULL << subset_size;
    const std::uint64_t states = combinations * permutations * orientations;
    if (states > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error("edge PDB state count exceeds uint32 capacity");
    }
    return Dimensions{
        subset_size,
        static_cast<std::uint32_t>(combinations),
        static_cast<std::uint32_t>(permutations),
        static_cast<std::uint32_t>(orientations),
        static_cast<std::uint32_t>(states),
    };
}

std::uint32_t rank_combination(const SubsetArray& positions, std::uint32_t subset_size) {
    std::uint32_t rank = 0;
    std::uint32_t next = 0;
    for (std::uint32_t i = 0; i < subset_size; ++i) {
        for (std::uint32_t value = next; value < positions[i]; ++value) {
            rank += kChoose[kEdgePositionCount - value - 1][subset_size - i - 1];
        }
        next = positions[i] + 1;
    }
    return rank;
}

void unrank_combination(std::uint32_t rank, std::uint32_t subset_size, SubsetArray& positions) {
    std::uint32_t next = 0;
    for (std::uint32_t i = 0; i < subset_size; ++i) {
        for (std::uint32_t value = next; value < kEdgePositionCount; ++value) {
            const std::uint32_t count = kChoose[kEdgePositionCount - value - 1][subset_size - i - 1];
            if (rank < count) {
                positions[i] = static_cast<std::uint8_t>(value);
                next = value + 1;
                break;
            }
            rank -= count;
        }
    }
}

std::uint32_t rank_permutation(const SubsetArray& values, std::uint32_t subset_size) {
    SubsetArray unused{};
    for (std::uint32_t i = 0; i < subset_size; ++i) {
        unused[i] = static_cast<std::uint8_t>(i);
    }
    std::uint32_t unused_size = subset_size;
    std::uint32_t rank = 0;
    for (std::uint32_t index = 0; index < subset_size; ++index) {
        std::uint32_t digit = 0;
        while (digit < unused_size && unused[digit] != values[index]) {
            ++digit;
        }
        if (digit == unused_size) {
            throw std::runtime_error("invalid edge-subset permutation while ranking");
        }
        rank += digit * static_cast<std::uint32_t>(kFact[subset_size - index - 1]);
        for (std::uint32_t j = digit; j + 1 < unused_size; ++j) {
            unused[j] = unused[j + 1];
        }
        --unused_size;
    }
    return rank;
}

void unrank_permutation(std::uint32_t rank, std::uint32_t subset_size, SubsetArray& values) {
    SubsetArray unused{};
    for (std::uint32_t i = 0; i < subset_size; ++i) {
        unused[i] = static_cast<std::uint8_t>(i);
    }
    std::uint32_t unused_size = subset_size;
    for (int index = static_cast<int>(subset_size) - 1; index >= 0; --index) {
        const std::uint32_t factor = static_cast<std::uint32_t>(kFact[static_cast<std::uint32_t>(index)]);
        const std::uint32_t digit = rank / factor;
        rank %= factor;
        values[subset_size - 1 - static_cast<std::uint32_t>(index)] = unused[digit];
        for (std::uint32_t j = digit; j + 1 < unused_size; ++j) {
            unused[j] = unused[j + 1];
        }
        --unused_size;
    }
}

std::uint32_t rank_state(const AbstractEdgeState& state, const Dimensions& dims) {
    SubsetArray positions{};
    SubsetArray permutation{};
    std::uint32_t orientation = 0;
    std::uint32_t index = 0;
    for (std::uint32_t position = 0; position < kEdgePositionCount; ++position) {
        const auto piece = state.position_piece[position];
        if (piece == 0xff) {
            continue;
        }
        if (index >= dims.subset_size) {
            throw std::runtime_error("too many subset edges in abstract state");
        }
        positions[index] = static_cast<std::uint8_t>(position);
        permutation[index] = piece;
        if (state.orientation[position] & 1U) {
            orientation |= (1U << index);
        }
        ++index;
    }
    if (index != dims.subset_size) {
        throw std::runtime_error("not enough subset edges in abstract state");
    }
    return (rank_combination(positions, dims.subset_size) * dims.permutation_count +
            rank_permutation(permutation, dims.subset_size)) *
               dims.orientation_count +
           orientation;
}

AbstractEdgeState unrank_state(std::uint32_t coord, const Dimensions& dims) {
    const std::uint32_t orientation = coord % dims.orientation_count;
    coord /= dims.orientation_count;
    const std::uint32_t permutation_rank = coord % dims.permutation_count;
    const std::uint32_t combination_rank = coord / dims.permutation_count;

    SubsetArray positions{};
    SubsetArray permutation{};
    unrank_combination(combination_rank, dims.subset_size, positions);
    unrank_permutation(permutation_rank, dims.subset_size, permutation);
    AbstractEdgeState state;
    state.position_piece.fill(0xff);
    state.orientation.fill(0);
    for (std::uint32_t index = 0; index < dims.subset_size; ++index) {
        const auto position = positions[index];
        state.position_piece[position] = permutation[index];
        state.orientation[position] = static_cast<std::uint8_t>((orientation >> index) & 1U);
    }
    return state;
}

AbstractEdgeState apply_base(const AbstractEdgeState& state, const BaseMove& move) {
    AbstractEdgeState out;
    out.position_piece.fill(0xff);
    out.orientation.fill(0);
    for (std::uint32_t position = 0; position < kEdgePositionCount; ++position) {
        const std::uint32_t old_position = move.ep[position];
        const auto piece = state.position_piece[old_position];
        if (piece == 0xff) {
            continue;
        }
        out.position_piece[position] = piece;
        out.orientation[position] =
            static_cast<std::uint8_t>((state.orientation[old_position] + move.eo[position]) & 1U);
    }
    return out;
}

Options parse_options(int argc, char** argv) {
    Options options;
    bool subset_provided = false;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--output" && i + 1 < argc) {
            options.output_path = argv[++i];
        } else if (arg == "--subset" && i + 1 < argc) {
            subset_provided = true;
            const std::string text = argv[++i];
            std::stringstream stream(text);
            std::string item;
            std::array<bool, 12> seen{};
            std::vector<std::uint8_t> subset;
            options.subset_label.clear();
            while (std::getline(stream, item, ',')) {
                if (subset.size() >= kMaxSubsetSize) {
                    throw std::runtime_error("--subset must contain six or seven comma-separated edge ids");
                }
                const int value = std::stoi(item);
                if (value < 0 || value >= static_cast<int>(kEdgePositionCount)) {
                    throw std::runtime_error("edge id out of range in --subset");
                }
                if (seen[static_cast<std::size_t>(value)]) {
                    throw std::runtime_error("duplicate edge id in --subset");
                }
                seen[static_cast<std::size_t>(value)] = true;
                subset.push_back(static_cast<std::uint8_t>(value));
                if (!options.subset_label.empty()) {
                    options.subset_label += "_";
                }
                options.subset_label += std::to_string(value);
            }
            if (subset.size() < kMinSubsetSize || subset.size() > kMaxSubsetSize) {
                throw std::runtime_error("--subset must contain six or seven comma-separated edge ids");
            }
            options.subset_edges = std::move(subset);
        } else if (arg == "--max-depth" && i + 1 < argc) {
            options.max_depth = static_cast<std::uint32_t>(std::stoul(argv[++i]));
        } else if (arg == "--move-costs" && i + 1 < argc) {
            const std::string text = argv[++i];
            std::stringstream stream(text);
            std::string item;
            std::uint32_t index = 0;
            while (std::getline(stream, item, ',')) {
                if (index >= kMoveNames.size()) {
                    throw std::runtime_error("--move-costs must contain exactly 18 comma-separated 0/1 values");
                }
                const int value = std::stoi(item);
                if (value != 0 && value != 1) {
                    throw std::runtime_error("--move-costs only supports 0/1 operator costs");
                }
                options.move_costs[index++] = static_cast<std::uint8_t>(value);
            }
            if (index != kMoveNames.size()) {
                throw std::runtime_error("--move-costs must contain exactly 18 comma-separated 0/1 values");
            }
        } else if (arg == "--help") {
            std::cout << "usage: edge_pdb --output PATH --subset 0,1,2,3,4,5[,6] "
                         "[--max-depth N] [--move-costs c0,...,c17]\n";
            std::exit(0);
        } else {
            throw std::runtime_error("unknown or incomplete argument: " + arg);
        }
    }
    if (options.output_path.empty()) {
        throw std::runtime_error("--output is required");
    }
    if (!subset_provided) {
        options.subset_label = "0_1_2_3_4_5";
    }
    return options;
}

bool is_uniform_unit_cost(const std::array<std::uint8_t, 18>& move_costs) {
    for (const auto cost : move_costs) {
        if (cost != 1) {
            return false;
        }
    }
    return true;
}

AbstractEdgeState solved_state(const std::vector<std::uint8_t>& subset_edges) {
    AbstractEdgeState state;
    state.position_piece.fill(0xff);
    state.orientation.fill(0);
    for (std::uint32_t index = 0; index < subset_edges.size(); ++index) {
        const auto edge = subset_edges[index];
        state.position_piece[edge] = static_cast<std::uint8_t>(index);
    }
    return state;
}

void write_binary_table(
    const std::string& output_path,
    const std::vector<std::uint8_t>& distances,
    const Header& header
) {
    std::ofstream out(output_path, std::ios::binary);
    if (!out) {
        throw std::runtime_error("failed to open output file: " + output_path);
    }
    out.write(reinterpret_cast<const char*>(&header), sizeof(header));
    out.write(reinterpret_cast<const char*>(distances.data()), static_cast<std::streamsize>(distances.size()));
    if (!out) {
        throw std::runtime_error("failed to write output file: " + output_path);
    }
}

} // namespace

int main(int argc, char** argv) {
    try {
        const auto options = parse_options(argc, argv);
        const Dimensions dims = dimensions_for(options.subset_size());
        const auto begin = std::chrono::steady_clock::now();

        std::vector<std::uint8_t> distances(dims.state_count, kUnvisited);
        std::deque<std::uint32_t> queue;
        const auto start = rank_state(solved_state(options.subset_edges), dims);
        distances[start] = 0;
        queue.push_back(start);

        std::uint64_t expanded = 0;
        std::uint64_t generated = 0;

        while (!queue.empty()) {
            const std::uint32_t coord = queue.front();
            queue.pop_front();
            const std::uint8_t depth = distances[coord];
            if (options.max_depth != kNoDepthLimit && depth >= options.max_depth) {
                continue;
            }
            ++expanded;
            // Unrank the parent once and expand all 18 children from it; ranking
            // each child is far cheaper than re-unranking per move.
            const AbstractEdgeState parent = unrank_state(coord, dims);
            for (std::uint32_t move_index = 0; move_index < kMoveNames.size(); ++move_index) {
                const std::uint32_t face = move_index / 3;
                const std::uint32_t turn_slot = move_index % 3;
                const std::uint32_t turns = turn_slot == 0 ? 1 : turn_slot == 1 ? 3 : 2;
                AbstractEdgeState child_state = parent;
                for (std::uint32_t turn = 0; turn < turns; ++turn) {
                    child_state = apply_base(child_state, kBaseMoves[face]);
                }
                const std::uint32_t child = rank_state(child_state, dims);
                const auto child_depth = static_cast<std::uint8_t>(depth + options.move_costs[move_index]);
                if (distances[child] != kUnvisited && distances[child] <= child_depth) {
                    continue;
                }
                distances[child] = child_depth;
                ++generated;
                if (options.move_costs[move_index] == 0) {
                    queue.push_front(child);
                } else {
                    queue.push_back(child);
                }
            }
        }

        std::array<std::uint64_t, 32> distribution{};
        std::uint64_t visited = 0;
        std::uint32_t max_distance = 0;
        for (const auto distance : distances) {
            if (distance == kUnvisited) {
                continue;
            }
            if (distance >= distribution.size()) {
                throw std::runtime_error("edge PDB distance exceeded distribution capacity");
            }
            ++distribution[distance];
            ++visited;
            if (distance > max_distance) {
                max_distance = distance;
            }
        }
        const bool complete = visited == dims.state_count;
        const bool uniform_unit_cost = is_uniform_unit_cost(options.move_costs);

        Header header = {
            {'R', '3', 'E', 'P', 'D', 'B', '1', '\0'},
            1,
            dims.subset_size,
            dims.state_count,
            dims.combination_count,
            dims.permutation_count,
            dims.orientation_count,
            {0, 0, 0, 0, 0, 0},
            {0, 0},
            max_distance,
            complete ? 1U : 0U,
            options.max_depth,
            static_cast<std::uint32_t>(sizeof(Header)),
            expanded,
            generated,
        };
        if (!uniform_unit_cost) {
            const char additive_magic[8] = {'R', '3', 'E', 'C', 'P', 'D', '1', '\0'};
            for (std::uint32_t index = 0; index < 8; ++index) {
                header.magic[index] = additive_magic[index];
            }
        }
        // subset_edges[6] and reserved[2] form 8 contiguous packed bytes; write
        // up to 7 ids starting at subset_edges[0] (the 7th lands in reserved[0]).
        std::uint8_t* subset_bytes = header.subset_edges;
        for (std::uint32_t index = 0; index < dims.subset_size; ++index) {
            subset_bytes[index] = options.subset_edges[index];
        }
        write_binary_table(options.output_path, distances, header);

        const auto end = std::chrono::steady_clock::now();
        const double runtime_seconds = std::chrono::duration<double>(end - begin).count();
        std::cout << "{\n";
        std::cout << "  \"schema_version\": 1,\n";
        std::cout << "  \"subset_label\": \"" << options.subset_label << "\",\n";
        std::cout << "  \"subset_size\": " << dims.subset_size << ",\n";
        std::cout << "  \"subset_edges\": [";
        for (std::uint32_t index = 0; index < dims.subset_size; ++index) {
            if (index > 0) {
                std::cout << ", ";
            }
            std::cout << static_cast<int>(options.subset_edges[index]);
        }
        std::cout << "],\n";
        std::cout << "  \"combination_count\": " << dims.combination_count << ",\n";
        std::cout << "  \"permutation_count\": " << dims.permutation_count << ",\n";
        std::cout << "  \"orientation_count\": " << dims.orientation_count << ",\n";
        std::cout << "  \"state_count\": " << dims.state_count << ",\n";
        std::cout << "  \"visited_states\": " << visited << ",\n";
        std::cout << "  \"complete\": " << (complete ? "true" : "false") << ",\n";
        std::cout << "  \"max_distance\": " << max_distance << ",\n";
        std::cout << "  \"expanded_nodes\": " << expanded << ",\n";
        std::cout << "  \"generated_nodes\": " << generated << ",\n";
        std::cout << "  \"runtime_seconds\": " << runtime_seconds << ",\n";
        std::cout << "  \"cost_partitioned\": " << (uniform_unit_cost ? "false" : "true") << ",\n";
        std::cout << "  \"move_costs\": [";
        for (std::uint32_t index = 0; index < kMoveNames.size(); ++index) {
            if (index > 0) {
                std::cout << ", ";
            }
            std::cout << static_cast<int>(options.move_costs[index]);
        }
        std::cout << "],\n";
        std::cout << "  \"depth_limit\": ";
        if (options.max_depth == kNoDepthLimit) {
            std::cout << "null";
        } else {
            std::cout << options.max_depth;
        }
        std::cout << ",\n";
        std::cout << "  \"distribution\": {";
        bool first = true;
        for (std::uint32_t depth = 0; depth < distribution.size(); ++depth) {
            if (distribution[depth] == 0) {
                continue;
            }
            if (!first) {
                std::cout << ", ";
            }
            first = false;
            std::cout << "\"" << depth << "\": " << distribution[depth];
        }
        std::cout << "}\n";
        std::cout << "}\n";
        return 0;
    } catch (const std::exception& exc) {
        std::cerr << "edge_pdb: " << exc.what() << "\n";
        return 1;
    }
}
