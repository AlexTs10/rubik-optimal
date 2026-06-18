// ---------------------------------------------------------------------------
// OPTIONAL nissy heuristic bridge — GPL-3.0 ATTRIBUTION
// ---------------------------------------------------------------------------
// This translation unit is compiled ONLY for the opt-in `optimal_solver_nissy`
// build. It adapts the student's cubie state to the data structures of nissy
// 2.0.8 (https://github.com/sebastianotronto/nissy) and queries nissy's HTM
// pruning tables (pd_corners_HTM, pd_drud_sym16_HTM) to provide an OPTIONAL
// extra admissible lower bound. nissy is licensed under the GNU General Public
// License, version 3.0 (GPL-3.0).
//
// The headers and `*.c` sources this file includes (alg.h, cube.h, pf.h,
// pruning.h, trans.h, ...) are part of nissy and are GPL-3.0. Linking them with
// optimal_solver.cpp creates a COMBINED / DERIVATIVE WORK that, if distributed,
// is itself subject to GPL-3.0. The student's default optimal engine does NOT
// compile or link this file and therefore carries no such obligation. The full
// third-party notice for nissy is maintained in THIRD_PARTY_NOTICES.md.
// ---------------------------------------------------------------------------

#include "nissy_bridge.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "alg.h"
#include "cube.h"
#include "pf.h"
#include "pruning.h"
#include "trans.h"

static const int k_native_to_nissy_move[18] = {
    U, U3, U2,
    R, R3, R2,
    F, F3, F2,
    D, D3, D2,
    L, L3, L2,
    B, B3, B2,
};

static const int k_native_edge_position_to_nissy[12] = {
    1, 2, 3, 0, 5, 6, 7, 4, 8, 9, 10, 11,
};

static const int k_our_edge_to_nissy[12] = {
    UR, UF, UL, UB, DR, DF, DL, DB, FR, FL, BL, BR,
};

static const int k_corl_from_coud[8][8][3] = {
    {{0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2}},
    {{2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1}},
    {{0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2}},
    {{2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1}},
    {{2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1}},
    {{0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2}},
    {{2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1}},
    {{0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2}},
};

static const int k_cofb_from_coud[8][8][3] = {
    {{0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2}},
    {{1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0}},
    {{0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2}},
    {{1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0}},
    {{1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0}},
    {{0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2}},
    {{1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0}},
    {{0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2}},
};

static int initialized = 0;

static void write_error(char* error_buffer, int error_buffer_size, const char* message) {
    if (error_buffer == NULL || error_buffer_size <= 0) {
        return;
    }
    snprintf(error_buffer, (size_t)error_buffer_size, "%s", message);
}

int nissy_bridge_init(const char* data_dir, int threads, char* error_buffer, int error_buffer_size) {
    if (initialized) {
        return 1;
    }
    if (data_dir != NULL && data_dir[0] != '\0') {
        setenv("NISSYDATA", data_dir, 1);
    }

    init_all_movesets();
    init_symcoord();
    genptable(&pd_corners_HTM, threads < 1 ? 1 : threads);
    genptable(&pd_drud_sym16_HTM, threads < 1 ? 1 : threads);

    if (!pd_corners_HTM.generated || !pd_drud_sym16_HTM.generated) {
        write_error(error_buffer, error_buffer_size, "failed to load or generate Nissy pruning tables");
        return 0;
    }
    initialized = 1;
    return 1;
}

NissyBridgeCube nissy_bridge_from_arrays(
    const uint8_t* cp,
    const uint8_t* co,
    const uint8_t* ep,
    const uint8_t* eo
) {
    int edge_perm[12];
    int eofb[12];
    int eorl[12];
    int eoud[12];
    int corner_perm[8];
    int coud[8];
    int corl[8];
    int cofb[8];
    int cpos[6] = {0, 1, 2, 3, 4, 5};
    CubeArray arr;
    Cube cube;

    for (int nissy_pos = 0; nissy_pos < 12; ++nissy_pos) {
        int our_pos = k_native_edge_position_to_nissy[nissy_pos];
        edge_perm[nissy_pos] = k_our_edge_to_nissy[ep[our_pos]];
        eofb[nissy_pos] = eo[our_pos];
        eorl[nissy_pos] = eo[our_pos];
        eoud[nissy_pos] = eo[our_pos];
    }
    for (int pos = 0; pos < 8; ++pos) {
        corner_perm[pos] = cp[pos];
        coud[pos] = co[pos];
        corl[pos] = k_corl_from_coud[pos][corner_perm[pos]][coud[pos]];
        cofb[pos] = k_cofb_from_coud[pos][corner_perm[pos]][coud[pos]];
    }

    arr = (CubeArray){
        .ep = edge_perm,
        .eofb = eofb,
        .eorl = eorl,
        .eoud = eoud,
        .cp = corner_perm,
        .coud = coud,
        .corl = corl,
        .cofb = cofb,
        .cpos = cpos,
    };
    fix_eorleoud(&arr);
    cube = arrays_to_cube(&arr, pf_all);

    return (NissyBridgeCube){
        .epose = cube.epose,
        .eposs = cube.eposs,
        .eposm = cube.eposm,
        .eofb = cube.eofb,
        .eorl = cube.eorl,
        .eoud = cube.eoud,
        .cp = cube.cp,
        .coud = cube.coud,
        .cofb = cube.cofb,
        .corl = cube.corl,
        .cpos = cube.cpos,
    };
}

static Cube to_nissy_cube(NissyBridgeCube cube) {
    return (Cube){
        .epose = cube.epose,
        .eposs = cube.eposs,
        .eposm = cube.eposm,
        .eofb = cube.eofb,
        .eorl = cube.eorl,
        .eoud = cube.eoud,
        .cp = cube.cp,
        .coud = cube.coud,
        .cofb = cube.cofb,
        .corl = cube.corl,
        .cpos = cube.cpos,
    };
}

static NissyBridgeCube from_nissy_cube(Cube cube) {
    return (NissyBridgeCube){
        .epose = cube.epose,
        .eposs = cube.eposs,
        .eposm = cube.eposm,
        .eofb = cube.eofb,
        .eorl = cube.eorl,
        .eoud = cube.eoud,
        .cp = cube.cp,
        .coud = cube.coud,
        .cofb = cube.cofb,
        .corl = cube.corl,
        .cpos = cube.cpos,
    };
}

NissyBridgeCube nissy_bridge_apply_move(NissyBridgeCube cube, int native_move_index) {
    if (native_move_index < 0 || native_move_index >= 18) {
        return cube;
    }
    return from_nissy_cube(apply_move((Move)k_native_to_nissy_move[native_move_index], to_nissy_cube(cube)));
}

NissyBridgeCube nissy_bridge_from_sequence(const char* sequence) {
    Alg* alg = new_alg((char*)(sequence == NULL ? "" : sequence));
    Cube cube = apply_alg(alg, (Cube){0});
    free_alg(alg);
    return from_nissy_cube(cube);
}

static int max_int(int left, int right) {
    return left > right ? left : right;
}

static int drud_axis_lower_bound(Cube cube) {
    int ud = ptableval(&pd_drud_sym16_HTM, cube);
    int fb = ptableval(&pd_drud_sym16_HTM, apply_trans(fd, cube));
    int rl = ptableval(&pd_drud_sym16_HTM, apply_trans(rf, cube));
    int ret = max_int(ud, max_int(fb, rl));
    if (ret == 0) {
        return is_solved(cube) ? 0 : 1;
    }
    if (ud == fb && fb == rl) {
        ret = max_int(ret, ud + 1);
    }
    return ret;
}

int nissy_bridge_light_lower_bound(NissyBridgeCube bridge_cube, int include_inverse, int include_axis_transforms) {
    Cube cube = to_nissy_cube(bridge_cube);
    int ret = ptableval(&pd_corners_HTM, cube);
    if (include_axis_transforms) {
        ret = max_int(ret, drud_axis_lower_bound(cube));
    } else {
        ret = max_int(ret, ptableval(&pd_drud_sym16_HTM, cube));
    }
    if (include_inverse) {
        Cube inverse = inverse_cube(cube);
        if (include_axis_transforms) {
            ret = max_int(ret, drud_axis_lower_bound(inverse));
        } else {
            ret = max_int(ret, ptableval(&pd_drud_sym16_HTM, inverse));
        }
    }
    return ret;
}
