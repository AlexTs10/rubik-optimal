// Sparse bidirectional BFS in an edge-subset projection.
//
// This is a measurement tool, not a runtime solver heuristic.  It answers the
// design question "what projected distance does the superflip have if we track
// N named edge cubies exactly?" without building a full C(12,N) * N! * 2^N PDB.

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_set>
#include <vector>

namespace {

constexpr std::uint8_t kUntracked = 0xff;
constexpr std::uint32_t kEdgePositionCount = 12;
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

struct Move {
    std::array<std::uint8_t, 12> ep;
    std::array<std::uint8_t, 12> eo;
};

struct EdgeState {
    std::array<std::uint8_t, 12> piece;
    std::array<std::uint8_t, 12> orientation;
};

struct Options {
    std::vector<std::uint8_t> subset_edges;
    std::uint32_t max_depth = 12;
    std::uint64_t max_seen = 0;
    bool ball = false;
    bool canonical_rotations = false;
    bool canonical_full_symmetries = false;
    bool progress = false;
};

struct EdgeRotationTransform {
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

constexpr std::array<std::array<int, 2>, 12> kEdgeFacelets = {{
    {{5, 10}}, {{7, 19}}, {{3, 37}}, {{1, 46}}, {{32, 16}}, {{28, 25}},
    {{30, 43}}, {{34, 52}}, {{23, 12}}, {{21, 41}}, {{50, 39}}, {{48, 14}},
}};

constexpr std::array<std::array<int, 2>, 12> kEdgeColors = {{
    {{0, 1}}, {{0, 2}}, {{0, 4}}, {{0, 5}}, {{3, 1}}, {{3, 2}},
    {{3, 4}}, {{3, 5}}, {{2, 1}}, {{2, 4}}, {{5, 4}}, {{5, 1}},
}};

std::uint64_t choose(std::uint32_t n, std::uint32_t k) {
    if (k > n) {
        return 0;
    }
    k = std::min(k, n - k);
    std::uint64_t value = 1;
    for (std::uint32_t i = 0; i < k; ++i) {
        value = value * (n - i) / (i + 1);
    }
    return value;
}

std::uint64_t factorial(std::uint32_t n) {
    std::uint64_t value = 1;
    for (std::uint32_t i = 2; i <= n; ++i) {
        value *= i;
    }
    return value;
}

std::array<Move, 18> build_moves() {
    std::array<Move, 18> moves{};
    for (std::uint32_t face = 0; face < 6; ++face) {
        Move current{kBaseMoves[face].ep, kBaseMoves[face].eo};
        moves[face * 3] = current;
        Move twice{};
        for (std::uint32_t pos = 0; pos < 12; ++pos) {
            const std::uint8_t mid = current.ep[pos];
            twice.ep[pos] = current.ep[mid];
            twice.eo[pos] = (current.eo[pos] + current.eo[mid]) & 1U;
        }
        Move thrice{};
        for (std::uint32_t pos = 0; pos < 12; ++pos) {
            const std::uint8_t mid = twice.ep[pos];
            thrice.ep[pos] = current.ep[mid];
            thrice.eo[pos] = (twice.eo[pos] + current.eo[mid]) & 1U;
        }
        moves[face * 3 + 1] = thrice;
        moves[face * 3 + 2] = twice;
    }
    return moves;
}

const auto kMoves = build_moves();

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

std::vector<EdgeRotationTransform> build_edge_transforms(const std::vector<Matrix3>& matrices) {
    std::array<Vec3, 54> facelet_positions{};
    std::array<Vec3, 54> facelet_normals{};
    build_facelet_geometry(facelet_positions, facelet_normals);
    const auto position_to_edge = build_position_to_edge();
    std::vector<EdgeRotationTransform> rotations(matrices.size());

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
        EdgeRotationTransform transform;
        for (int face = 0; face < 6; ++face) {
            transform.face_map[face] = static_cast<std::uint8_t>(face_from_normal(apply_matrix(matrix, kFaceNormals[face])));
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

const std::vector<EdgeRotationTransform>& edge_rotation_transforms() {
    static const auto transforms = build_edge_transforms(build_rotation_matrices());
    return transforms;
}

const std::vector<EdgeRotationTransform>& edge_full_symmetry_transforms() {
    static const auto transforms = build_edge_transforms(build_full_symmetry_matrices());
    return transforms;
}

EdgeState rotate_edge_state(const EdgeState& state, const EdgeRotationTransform& transform) {
    EdgeState out{};
    out.piece.fill(kUntracked);
    out.orientation.fill(0);
    for (std::uint32_t pos = 0; pos < 12; ++pos) {
        const std::uint8_t piece = state.piece[pos];
        if (piece == kUntracked) {
            continue;
        }
        const std::uint8_t orientation = state.orientation[pos];
        const std::uint8_t new_pos = transform.edge_pos[pos];
        out.piece[new_pos] = transform.edge_cubie[piece];
        out.orientation[new_pos] = transform.edge_ori[(pos * 12 + piece) * 2 + orientation];
    }
    return out;
}

EdgeState solved_state(const std::vector<std::uint8_t>& subset_edges, bool superflip) {
    EdgeState state{};
    state.piece.fill(kUntracked);
    state.orientation.fill(0);
    for (std::uint8_t edge : subset_edges) {
        state.piece[edge] = edge;
        state.orientation[edge] = superflip ? 1 : 0;
    }
    return state;
}

EdgeState apply_move(const EdgeState& state, const Move& move) {
    EdgeState out{};
    out.piece.fill(kUntracked);
    out.orientation.fill(0);
    for (std::uint32_t pos = 0; pos < 12; ++pos) {
        const std::uint8_t source = move.ep[pos];
        const std::uint8_t piece = state.piece[source];
        out.piece[pos] = piece;
        if (piece != kUntracked) {
            out.orientation[pos] = (state.orientation[source] + move.eo[pos]) & 1U;
        }
    }
    return out;
}

std::uint64_t rank_combination(
    const std::array<std::uint8_t, 12>& positions,
    std::uint32_t subset_size
) {
    std::uint64_t rank = 0;
    std::uint32_t next = 0;
    for (std::uint32_t index = 0; index < subset_size; ++index) {
        for (std::uint32_t value = next; value < positions[index]; ++value) {
            rank += choose(kEdgePositionCount - value - 1, subset_size - index - 1);
        }
        next = positions[index] + 1;
    }
    return rank;
}

std::uint64_t rank_permutation(
    const std::array<std::uint8_t, 12>& values,
    std::uint32_t subset_size
) {
    std::array<std::uint8_t, 12> unused{};
    for (std::uint32_t i = 0; i < subset_size; ++i) {
        unused[i] = static_cast<std::uint8_t>(i);
    }
    std::uint32_t unused_size = subset_size;
    std::uint64_t rank = 0;
    for (std::uint32_t index = 0; index < subset_size; ++index) {
        std::uint32_t digit = 0;
        while (digit < unused_size && unused[digit] != values[index]) {
            ++digit;
        }
        if (digit == unused_size) {
            throw std::runtime_error("invalid projected permutation");
        }
        rank += digit * factorial(subset_size - index - 1);
        for (std::uint32_t j = digit; j + 1 < unused_size; ++j) {
            unused[j] = unused[j + 1];
        }
        --unused_size;
    }
    return rank;
}

std::uint64_t rank_state(
    const EdgeState& state,
    const std::array<std::uint8_t, 12>& edge_to_subset,
    std::uint32_t subset_size
) {
    std::array<std::uint8_t, 12> positions{};
    std::array<std::uint8_t, 12> permutation{};
    std::uint64_t orientation = 0;
    std::uint32_t index = 0;
    for (std::uint32_t pos = 0; pos < 12; ++pos) {
        const std::uint8_t piece = state.piece[pos];
        if (piece == kUntracked) {
            continue;
        }
        positions[index] = static_cast<std::uint8_t>(pos);
        permutation[index] = edge_to_subset[piece];
        if (state.orientation[pos] & 1U) {
            orientation |= 1ULL << index;
        }
        ++index;
    }
    if (index != subset_size) {
        throw std::runtime_error("projected state lost tracked edge");
    }
    return (
        rank_combination(positions, subset_size) * factorial(subset_size)
        + rank_permutation(permutation, subset_size)
    ) * (1ULL << subset_size) + orientation;
}

std::uint16_t subset_mask_from_state(const EdgeState& state) {
    std::uint16_t mask = 0;
    for (std::uint32_t pos = 0; pos < 12; ++pos) {
        const std::uint8_t piece = state.piece[pos];
        if (piece != kUntracked) {
            mask |= static_cast<std::uint16_t>(1U << piece);
        }
    }
    return mask;
}

std::uint64_t projection_key_for_state(const EdgeState& state) {
    constexpr std::uint64_t kCoordBits = 48;
    constexpr std::uint64_t kCoordLimit = 1ULL << kCoordBits;
    const std::uint16_t mask = subset_mask_from_state(state);
    std::array<std::uint8_t, 12> edge_to_subset{};
    edge_to_subset.fill(kUntracked);
    std::uint32_t subset_size = 0;
    for (std::uint32_t edge = 0; edge < 12; ++edge) {
        if ((mask & (1U << edge)) != 0) {
            edge_to_subset[edge] = static_cast<std::uint8_t>(subset_size);
            ++subset_size;
        }
    }
    const std::uint64_t coord = rank_state(state, edge_to_subset, subset_size);
    if (coord >= kCoordLimit) {
        throw std::runtime_error("projected coordinate does not fit in canonical key");
    }
    return (static_cast<std::uint64_t>(mask) << kCoordBits) | coord;
}

struct CanonicalProjection {
    std::uint64_t key = 0;
    EdgeState state{};
};

CanonicalProjection canonical_projection(const EdgeState& state, bool use_rotations, bool use_full_symmetries) {
    CanonicalProjection best{projection_key_for_state(state), state};
    if (!use_rotations) {
        return best;
    }
    const auto& transforms = use_full_symmetries ? edge_full_symmetry_transforms() : edge_rotation_transforms();
    for (std::size_t index = 1; index < transforms.size(); ++index) {
        EdgeState rotated = rotate_edge_state(state, transforms[index]);
        const std::uint64_t key = projection_key_for_state(rotated);
        if (key < best.key) {
            best.key = key;
            best.state = rotated;
        }
    }
    return best;
}

std::vector<std::uint8_t> parse_subset(const std::string& text) {
    std::vector<std::uint8_t> subset;
    std::stringstream stream(text);
    std::string part;
    while (std::getline(stream, part, ',')) {
        if (part.empty()) {
            continue;
        }
        const int value = std::stoi(part);
        if (value < 0 || value >= 12) {
            throw std::runtime_error("subset edge ids must be in [0, 11]");
        }
        subset.push_back(static_cast<std::uint8_t>(value));
    }
    if (subset.empty() || subset.size() > 12) {
        throw std::runtime_error("subset must contain 1..12 edge ids");
    }
    std::vector<std::uint8_t> sorted = subset;
    std::sort(sorted.begin(), sorted.end());
    if (std::adjacent_find(sorted.begin(), sorted.end()) != sorted.end()) {
        throw std::runtime_error("subset edge ids must be distinct");
    }
    return subset;
}

Options parse_args(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--subset" && i + 1 < argc) {
            options.subset_edges = parse_subset(argv[++i]);
        } else if (arg == "--max-depth" && i + 1 < argc) {
            options.max_depth = static_cast<std::uint32_t>(std::stoul(argv[++i]));
        } else if (arg == "--max-seen" && i + 1 < argc) {
            options.max_seen = static_cast<std::uint64_t>(std::stoull(argv[++i]));
        } else if (arg == "--ball") {
            options.ball = true;
        } else if (arg == "--canonical-rotations") {
            options.canonical_rotations = true;
        } else if (arg == "--canonical-full-symmetries") {
            options.canonical_rotations = true;
            options.canonical_full_symmetries = true;
        } else if (arg == "--progress") {
            options.progress = true;
        } else {
            throw std::runtime_error("unknown or incomplete argument: " + arg);
        }
    }
    if (options.subset_edges.empty()) {
        options.subset_edges = {0, 1, 2, 3, 4, 5, 6, 7, 8};
    }
    return options;
}

struct SearchResult {
    bool found = false;
    std::uint32_t distance = 0;
    std::uint32_t proved_greater_than = 0;
    std::uint64_t start_seen = 0;
    std::uint64_t target_seen = 0;
    std::uint64_t start_frontier = 0;
    std::uint64_t target_frontier = 0;
};

struct BallLayer {
    std::uint32_t depth = 0;
    std::uint64_t frontier = 0;
    std::uint64_t seen = 0;
    double elapsed_seconds = 0.0;
};

struct BallResult {
    bool completed = true;
    std::string stopped_reason;
    std::uint32_t completed_depth = 0;
    std::uint64_t seen = 0;
    std::uint64_t frontier = 0;
    std::vector<BallLayer> layers;
};

SearchResult search(const Options& options) {
    const std::uint32_t subset_size = static_cast<std::uint32_t>(options.subset_edges.size());
    std::array<std::uint8_t, 12> edge_to_subset{};
    edge_to_subset.fill(kUntracked);
    for (std::uint32_t i = 0; i < subset_size; ++i) {
        edge_to_subset[options.subset_edges[i]] = static_cast<std::uint8_t>(i);
    }

    std::vector<EdgeState> start_frontier{solved_state(options.subset_edges, false)};
    std::vector<EdgeState> target_frontier{solved_state(options.subset_edges, true)};
    std::unordered_set<std::uint64_t> start_seen;
    std::unordered_set<std::uint64_t> target_seen;
    start_seen.reserve(1 << 20);
    target_seen.reserve(1 << 20);
    start_seen.insert(rank_state(start_frontier.front(), edge_to_subset, subset_size));
    target_seen.insert(rank_state(target_frontier.front(), edge_to_subset, subset_size));

    std::uint32_t start_depth = 0;
    std::uint32_t target_depth = 0;

    auto expand = [&edge_to_subset, subset_size](
        const std::vector<EdgeState>& frontier,
        std::vector<EdgeState>& next_frontier,
        std::unordered_set<std::uint64_t>& own_seen,
        const std::unordered_set<std::uint64_t>& other_seen
    ) -> bool {
        next_frontier.clear();
        next_frontier.reserve(frontier.size() * 4);
        for (const EdgeState& state : frontier) {
            for (const Move& move : kMoves) {
                EdgeState child = apply_move(state, move);
                const std::uint64_t coord = rank_state(child, edge_to_subset, subset_size);
                if (other_seen.find(coord) != other_seen.end()) {
                    return true;
                }
                const auto inserted = own_seen.insert(coord);
                if (inserted.second) {
                    next_frontier.push_back(child);
                }
            }
        }
        return false;
    };

    std::vector<EdgeState> next_frontier;
    while (start_depth + target_depth < options.max_depth) {
        const bool expand_start = start_frontier.size() <= target_frontier.size();
        if (options.progress) {
            std::cerr
                << "depths=" << start_depth << "/" << target_depth
                << " frontiers=" << start_frontier.size() << "/" << target_frontier.size()
                << " seen=" << start_seen.size() << "/" << target_seen.size()
                << " expand=" << (expand_start ? "start" : "target") << "\n";
        }
        bool found = false;
        if (expand_start) {
            found = expand(start_frontier, next_frontier, start_seen, target_seen);
            start_frontier.swap(next_frontier);
            ++start_depth;
        } else {
            found = expand(target_frontier, next_frontier, target_seen, start_seen);
            target_frontier.swap(next_frontier);
            ++target_depth;
        }
        if (found) {
            return SearchResult{
                true,
                start_depth + target_depth,
                0,
                start_seen.size(),
                target_seen.size(),
                start_frontier.size(),
                target_frontier.size(),
            };
        }
    }

    return SearchResult{
        false,
        0,
        start_depth + target_depth,
        start_seen.size(),
        target_seen.size(),
        start_frontier.size(),
        target_frontier.size(),
    };
}

BallResult ball_search(const Options& options) {
    const std::uint32_t subset_size = static_cast<std::uint32_t>(options.subset_edges.size());
    std::array<std::uint8_t, 12> edge_to_subset{};
    edge_to_subset.fill(kUntracked);
    for (std::uint32_t i = 0; i < subset_size; ++i) {
        edge_to_subset[options.subset_edges[i]] = static_cast<std::uint8_t>(i);
    }

    const auto begin = std::chrono::steady_clock::now();
    std::vector<EdgeState> frontier;
    std::unordered_set<std::uint64_t> seen;
    seen.reserve(1 << 20);
    const EdgeState start = solved_state(options.subset_edges, false);
    if (options.canonical_rotations) {
        const CanonicalProjection canonical = canonical_projection(start, true, options.canonical_full_symmetries);
        frontier.push_back(canonical.state);
        seen.insert(canonical.key);
    } else {
        frontier.push_back(start);
        seen.insert(rank_state(frontier.front(), edge_to_subset, subset_size));
    }

    BallResult result;
    auto append_layer = [&](std::uint32_t depth) {
        const auto now = std::chrono::steady_clock::now();
        result.layers.push_back(BallLayer{
            depth,
            static_cast<std::uint64_t>(frontier.size()),
            static_cast<std::uint64_t>(seen.size()),
            std::chrono::duration<double>(now - begin).count(),
        });
    };

    append_layer(0);
    for (std::uint32_t depth = 0; depth < options.max_depth; ++depth) {
        if (options.progress) {
            std::cerr
                << "ball depth=" << depth
                << " frontier=" << frontier.size()
                << " seen=" << seen.size() << "\n";
        }
        std::vector<EdgeState> next_frontier;
        next_frontier.reserve(frontier.size() * 4);
        for (const EdgeState& state : frontier) {
            for (const Move& move : kMoves) {
                EdgeState child = apply_move(state, move);
                std::uint64_t key = 0;
                if (options.canonical_rotations) {
                    CanonicalProjection canonical = canonical_projection(child, true, options.canonical_full_symmetries);
                    key = canonical.key;
                    child = canonical.state;
                } else {
                    key = rank_state(child, edge_to_subset, subset_size);
                }
                const auto inserted = seen.insert(key);
                if (inserted.second) {
                    next_frontier.push_back(child);
                    if (options.max_seen != 0 && seen.size() >= options.max_seen) {
                        frontier.swap(next_frontier);
                        result.completed = false;
                        result.stopped_reason = "max_seen";
                        result.completed_depth = depth;
                        result.seen = seen.size();
                        result.frontier = frontier.size();
                        append_layer(depth + 1);
                        return result;
                    }
                }
            }
        }
        frontier.swap(next_frontier);
        result.completed_depth = depth + 1;
        append_layer(depth + 1);
    }

    result.completed = true;
    result.stopped_reason = "";
    result.seen = seen.size();
    result.frontier = frontier.size();
    return result;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const Options options = parse_args(argc, argv);
        const auto begin = std::chrono::steady_clock::now();
        if (options.ball) {
            const BallResult result = ball_search(options);
            const auto end = std::chrono::steady_clock::now();
            const double seconds = std::chrono::duration<double>(end - begin).count();
            const std::uint32_t subset_size = static_cast<std::uint32_t>(options.subset_edges.size());
            const std::uint64_t state_count =
                choose(kEdgePositionCount, subset_size) * factorial(subset_size) * (1ULL << subset_size);

            std::cout << "{\n";
            std::cout << "  \"mode\": \"ball\",\n";
            std::cout << "  \"subset_edges\": [";
            for (std::size_t i = 0; i < options.subset_edges.size(); ++i) {
                if (i != 0) {
                    std::cout << ", ";
                }
                std::cout << static_cast<int>(options.subset_edges[i]);
            }
            std::cout << "],\n";
            std::cout << "  \"subset_size\": " << subset_size << ",\n";
            std::cout << "  \"projected_state_count\": " << state_count << ",\n";
            std::cout << "  \"max_depth\": " << options.max_depth << ",\n";
            std::cout << "  \"max_seen\": " << options.max_seen << ",\n";
            std::cout << "  \"canonical_rotations\": " << (options.canonical_rotations ? "true" : "false") << ",\n";
            std::cout << "  \"canonical_full_symmetries\": "
                      << (options.canonical_full_symmetries ? "true" : "false") << ",\n";
            std::cout << "  \"canonical_transform_count\": "
                      << (
                          options.canonical_rotations
                              ? (options.canonical_full_symmetries ? edge_full_symmetry_transforms().size() : edge_rotation_transforms().size())
                              : 0
                      ) << ",\n";
            std::cout << "  \"completed\": " << (result.completed ? "true" : "false") << ",\n";
            std::cout << "  \"stopped_reason\": ";
            if (result.stopped_reason.empty()) {
                std::cout << "null,\n";
            } else {
                std::cout << "\"" << result.stopped_reason << "\",\n";
            }
            std::cout << "  \"completed_depth\": " << result.completed_depth << ",\n";
            std::cout << "  \"seen\": " << result.seen << ",\n";
            std::cout << "  \"frontier\": " << result.frontier << ",\n";
            std::cout << "  \"elapsed_seconds\": " << seconds << ",\n";
            std::cout << "  \"layers\": [\n";
            for (std::size_t i = 0; i < result.layers.size(); ++i) {
                const BallLayer& layer = result.layers[i];
                std::cout << "    {"
                          << "\"depth\": " << layer.depth
                          << ", \"frontier\": " << layer.frontier
                          << ", \"seen\": " << layer.seen
                          << ", \"elapsed_seconds\": " << layer.elapsed_seconds
                          << "}";
                if (i + 1 != result.layers.size()) {
                    std::cout << ",";
                }
                std::cout << "\n";
            }
            std::cout << "  ]\n";
            std::cout << "}\n";
            return 0;
        }

        const SearchResult result = search(options);
        const auto end = std::chrono::steady_clock::now();
        const double seconds = std::chrono::duration<double>(end - begin).count();
        const std::uint32_t subset_size = static_cast<std::uint32_t>(options.subset_edges.size());
        const std::uint64_t state_count =
            choose(kEdgePositionCount, subset_size) * factorial(subset_size) * (1ULL << subset_size);

        std::cout << "{\n";
        std::cout << "  \"subset_edges\": [";
        for (std::size_t i = 0; i < options.subset_edges.size(); ++i) {
            if (i != 0) {
                std::cout << ", ";
            }
            std::cout << static_cast<int>(options.subset_edges[i]);
        }
        std::cout << "],\n";
        std::cout << "  \"subset_size\": " << subset_size << ",\n";
        std::cout << "  \"projected_state_count\": " << state_count << ",\n";
        if (result.found) {
            std::cout << "  \"found_distance\": " << result.distance << ",\n";
            std::cout << "  \"proved_greater_than\": null,\n";
        } else {
            std::cout << "  \"found_distance\": null,\n";
            std::cout << "  \"proved_greater_than\": " << result.proved_greater_than << ",\n";
        }
        std::cout << "  \"max_depth\": " << options.max_depth << ",\n";
        std::cout << "  \"elapsed_seconds\": " << seconds << ",\n";
        std::cout << "  \"start_seen\": " << result.start_seen << ",\n";
        std::cout << "  \"target_seen\": " << result.target_seen << ",\n";
        std::cout << "  \"start_frontier\": " << result.start_frontier << ",\n";
        std::cout << "  \"target_frontier\": " << result.target_frontier << "\n";
        std::cout << "}\n";
        return 0;
    } catch (const std::exception& exc) {
        std::cerr << "error: " << exc.what() << "\n";
        return 1;
    }
}
