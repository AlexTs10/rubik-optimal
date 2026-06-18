// Native generator for the 3x3 corner-state pattern database.
//
// The coordinate is:
//   corner_permutation_rank * 3^7 + corner_orientation_coordinate
//
// The move definitions mirror src/rubik_optimal/cube.py. The output file is a
// compact binary table with one unsigned byte per projected corner state.

#include <array>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <queue>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr std::uint32_t kCornerPermutationCount = 40320;
constexpr std::uint32_t kCornerOrientationCount = 2187;
constexpr std::uint32_t kCornerStateCount = kCornerPermutationCount * kCornerOrientationCount;
constexpr std::uint8_t kUnvisited = 0xff;
constexpr std::uint32_t kNoDepthLimit = std::numeric_limits<std::uint32_t>::max();
constexpr std::array<const char*, 18> kMoveNames = {
    "U", "U'", "U2", "R", "R'", "R2", "F", "F'", "F2",
    "D", "D'", "D2", "L", "L'", "L2", "B", "B'", "B2",
};

struct BaseMove {
    std::array<std::uint8_t, 8> cp;
    std::array<std::uint8_t, 8> co;
};

constexpr std::array<BaseMove, 6> kBaseMoves = {{
    {{{3, 0, 1, 2, 4, 5, 6, 7}}, {{0, 0, 0, 0, 0, 0, 0, 0}}}, // U
    {{{4, 1, 2, 0, 7, 5, 6, 3}}, {{2, 0, 0, 1, 1, 0, 0, 2}}}, // R
    {{{1, 5, 2, 3, 0, 4, 6, 7}}, {{1, 2, 0, 0, 2, 1, 0, 0}}}, // F
    {{{0, 1, 2, 3, 5, 6, 7, 4}}, {{0, 0, 0, 0, 0, 0, 0, 0}}}, // D
    {{{0, 2, 6, 3, 4, 1, 5, 7}}, {{0, 1, 2, 0, 0, 2, 1, 0}}}, // L
    {{{0, 1, 3, 7, 4, 5, 2, 6}}, {{0, 0, 1, 2, 0, 0, 2, 1}}}, // B
}};

#pragma pack(push, 1)
struct Header {
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
#pragma pack(pop)

constexpr std::array<std::uint32_t, 9> factorials() {
    std::array<std::uint32_t, 9> values{};
    values[0] = 1;
    for (std::uint32_t i = 1; i < values.size(); ++i) {
        values[i] = values[i - 1] * i;
    }
    return values;
}

constexpr auto kFactorial = factorials();

std::array<std::uint8_t, 8> unrank_permutation(std::uint32_t rank) {
    std::array<std::uint8_t, 8> values{};
    std::array<std::uint8_t, 8> unused = {{0, 1, 2, 3, 4, 5, 6, 7}};
    std::uint8_t unused_size = 8;
    for (int index = 7; index >= 0; --index) {
        const std::uint32_t factor = kFactorial[static_cast<std::size_t>(index)];
        const std::uint32_t digit = rank / factor;
        rank %= factor;
        values[static_cast<std::size_t>(7 - index)] = unused[digit];
        for (std::uint32_t j = digit; j + 1 < unused_size; ++j) {
            unused[j] = unused[j + 1];
        }
        --unused_size;
    }
    return values;
}

std::uint32_t rank_permutation(const std::array<std::uint8_t, 8>& values) {
    std::array<std::uint8_t, 8> unused = {{0, 1, 2, 3, 4, 5, 6, 7}};
    std::uint8_t unused_size = 8;
    std::uint32_t rank = 0;
    for (std::uint32_t index = 0; index < 8; ++index) {
        std::uint32_t digit = 0;
        while (digit < unused_size && unused[digit] != values[index]) {
            ++digit;
        }
        if (digit == unused_size) {
            throw std::runtime_error("invalid permutation while ranking");
        }
        rank += digit * kFactorial[7 - index];
        for (std::uint32_t j = digit; j + 1 < unused_size; ++j) {
            unused[j] = unused[j + 1];
        }
        --unused_size;
    }
    return rank;
}

std::array<std::uint8_t, 8> unrank_orientation(std::uint32_t coord) {
    std::array<std::uint8_t, 8> values{};
    std::uint32_t sum = 0;
    for (int index = 6; index >= 0; --index) {
        values[static_cast<std::size_t>(index)] = static_cast<std::uint8_t>(coord % 3);
        sum += values[static_cast<std::size_t>(index)];
        coord /= 3;
    }
    values[7] = static_cast<std::uint8_t>((3 - (sum % 3)) % 3);
    return values;
}

std::uint32_t rank_orientation(const std::array<std::uint8_t, 8>& values) {
    std::uint32_t coord = 0;
    for (std::uint32_t index = 0; index < 7; ++index) {
        coord = coord * 3 + values[index];
    }
    return coord;
}

std::array<std::uint8_t, 8> apply_cp_base(
    const std::array<std::uint8_t, 8>& cp,
    const BaseMove& move
) {
    std::array<std::uint8_t, 8> out{};
    for (std::uint32_t i = 0; i < 8; ++i) {
        out[i] = cp[move.cp[i]];
    }
    return out;
}

std::array<std::uint8_t, 8> apply_co_base(
    const std::array<std::uint8_t, 8>& co,
    const BaseMove& move
) {
    std::array<std::uint8_t, 8> out{};
    for (std::uint32_t i = 0; i < 8; ++i) {
        out[i] = static_cast<std::uint8_t>((co[move.cp[i]] + move.co[i]) % 3);
    }
    return out;
}

std::vector<std::array<std::uint32_t, 18>> build_corner_permutation_moves() {
    std::vector<std::array<std::uint32_t, 18>> table(kCornerPermutationCount);
    for (std::uint32_t coord = 0; coord < kCornerPermutationCount; ++coord) {
        for (std::uint32_t face = 0; face < 6; ++face) {
            auto state = unrank_permutation(coord);
            for (std::uint32_t turns = 1; turns <= 3; ++turns) {
                state = apply_cp_base(state, kBaseMoves[face]);
                table[coord][face * 3 + (turns == 1 ? 0 : turns == 3 ? 1 : 2)] = rank_permutation(state);
            }
        }
    }
    return table;
}

std::vector<std::array<std::uint16_t, 18>> build_corner_orientation_moves() {
    std::vector<std::array<std::uint16_t, 18>> table(kCornerOrientationCount);
    for (std::uint32_t coord = 0; coord < kCornerOrientationCount; ++coord) {
        for (std::uint32_t face = 0; face < 6; ++face) {
            auto state = unrank_orientation(coord);
            for (std::uint32_t turns = 1; turns <= 3; ++turns) {
                state = apply_co_base(state, kBaseMoves[face]);
                table[coord][face * 3 + (turns == 1 ? 0 : turns == 3 ? 1 : 2)] =
                    static_cast<std::uint16_t>(rank_orientation(state));
            }
        }
    }
    return table;
}

struct Options {
    std::string output_path;
    std::uint32_t max_depth = kNoDepthLimit;
};

Options parse_options(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--output" && i + 1 < argc) {
            options.output_path = argv[++i];
        } else if (arg == "--max-depth" && i + 1 < argc) {
            options.max_depth = static_cast<std::uint32_t>(std::stoul(argv[++i]));
        } else if (arg == "--help") {
            std::cout << "usage: corner_pdb --output PATH [--max-depth N]\n";
            std::exit(0);
        } else {
            throw std::runtime_error("unknown or incomplete argument: " + arg);
        }
    }
    if (options.output_path.empty()) {
        throw std::runtime_error("--output is required");
    }
    return options;
}

std::uint32_t next_coord(
    std::uint32_t coord,
    std::uint32_t move_index,
    const std::vector<std::array<std::uint32_t, 18>>& cp_moves,
    const std::vector<std::array<std::uint16_t, 18>>& co_moves
) {
    const std::uint32_t cp = coord / kCornerOrientationCount;
    const std::uint32_t co = coord % kCornerOrientationCount;
    return cp_moves[cp][move_index] * kCornerOrientationCount + co_moves[co][move_index];
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
        const auto begin = std::chrono::steady_clock::now();

        std::cerr << "building corner move tables\n";
        const auto cp_moves = build_corner_permutation_moves();
        const auto co_moves = build_corner_orientation_moves();

        std::vector<std::uint8_t> distances(kCornerStateCount, kUnvisited);
        std::queue<std::uint32_t> queue;
        distances[0] = 0;
        queue.push(0);

        std::array<std::uint64_t, 32> distribution{};
        distribution[0] = 1;
        std::uint64_t expanded = 0;
        std::uint64_t generated = 0;
        std::uint32_t max_distance = 0;

        while (!queue.empty()) {
            const std::uint32_t coord = queue.front();
            queue.pop();
            const std::uint8_t depth = distances[coord];
            if (options.max_depth != kNoDepthLimit && depth >= options.max_depth) {
                continue;
            }
            ++expanded;
            for (std::uint32_t move_index = 0; move_index < kMoveNames.size(); ++move_index) {
                const std::uint32_t child = next_coord(coord, move_index, cp_moves, co_moves);
                if (distances[child] != kUnvisited) {
                    continue;
                }
                const auto child_depth = static_cast<std::uint8_t>(depth + 1);
                distances[child] = child_depth;
                ++distribution[child_depth];
                ++generated;
                if (child_depth > max_distance) {
                    max_distance = child_depth;
                    std::cerr << "reached depth " << static_cast<int>(max_distance)
                              << ", generated=" << generated << "\n";
                }
                queue.push(child);
            }
        }

        std::uint64_t visited = 0;
        for (const auto count : distribution) {
            visited += count;
        }
        const bool complete = visited == kCornerStateCount;

        Header header = {
            {'R', '3', 'C', 'P', 'D', 'B', '1', '\0'},
            1,
            kCornerStateCount,
            kCornerPermutationCount,
            kCornerOrientationCount,
            max_distance,
            complete ? 1U : 0U,
            options.max_depth,
            static_cast<std::uint32_t>(sizeof(Header)),
            expanded,
            generated,
        };
        write_binary_table(options.output_path, distances, header);

        const auto end = std::chrono::steady_clock::now();
        const double runtime_seconds = std::chrono::duration<double>(end - begin).count();
        std::cout << "{\n";
        std::cout << "  \"schema_version\": 1,\n";
        std::cout << "  \"state_count\": " << kCornerStateCount << ",\n";
        std::cout << "  \"visited_states\": " << visited << ",\n";
        std::cout << "  \"complete\": " << (complete ? "true" : "false") << ",\n";
        std::cout << "  \"max_distance\": " << max_distance << ",\n";
        std::cout << "  \"expanded_nodes\": " << expanded << ",\n";
        std::cout << "  \"generated_nodes\": " << generated << ",\n";
        std::cout << "  \"runtime_seconds\": " << runtime_seconds << ",\n";
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
        std::cerr << "corner_pdb: " << exc.what() << "\n";
        return 1;
    }
}
