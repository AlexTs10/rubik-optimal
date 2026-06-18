// Optional nissy heuristic bridge interface. Used only by the opt-in
// `optimal_solver_nissy` build. The underlying heuristic is GPL-3.0 nissy
// 2.0.8 (https://github.com/sebastianotronto/nissy); linking it produces a
// combined/derivative work governed by GPL-3.0. See nissy_bridge.c and
// THIRD_PARTY_NOTICES.md. The student's default optimal engine never uses this.

#ifndef RUBIK_OPTIMAL_NISSY_BRIDGE_H
#define RUBIK_OPTIMAL_NISSY_BRIDGE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct NissyBridgeCube {
    int epose;
    int eposs;
    int eposm;
    int eofb;
    int eorl;
    int eoud;
    int cp;
    int coud;
    int cofb;
    int corl;
    int cpos;
} NissyBridgeCube;

int nissy_bridge_init(const char* data_dir, int threads, char* error_buffer, int error_buffer_size);
NissyBridgeCube nissy_bridge_from_arrays(
    const uint8_t* cp,
    const uint8_t* co,
    const uint8_t* ep,
    const uint8_t* eo
);
NissyBridgeCube nissy_bridge_from_sequence(const char* sequence);
NissyBridgeCube nissy_bridge_apply_move(NissyBridgeCube cube, int native_move_index);
int nissy_bridge_light_lower_bound(NissyBridgeCube cube, int include_inverse, int include_axis_transforms);

#ifdef __cplusplus
}
#endif

#endif
