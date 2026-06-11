#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "alg.h"
#include "cube.h"
#include "env.h"
#include "moves.h"
#include "solve.h"
#include "steps.h"
#include "symcoord.h"

extern Step optimal_HTM;

static const int local_edge_to_nissy[12] = {
	3, 0, 1, 2, 7, 4, 5, 6, 8, 9, 10, 11
};
static const int nissy_edge_to_local[12] = {
	1, 2, 3, 0, 5, 6, 7, 4, 8, 9, 10, 11
};
static const int corner_cofb_from_coud[8][8][3] = {
	{
		{0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1},
		{2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2}
	},
	{
		{1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2},
		{0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0}
	},
	{
		{0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1},
		{2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2}
	},
	{
		{1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2},
		{0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0}
	},
	{
		{1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2},
		{0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0}
	},
	{
		{0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1},
		{2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2}
	},
	{
		{1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2},
		{0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0}
	},
	{
		{0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1},
		{2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2}
	}
};
static const int corner_corl_from_coud[8][8][3] = {
	{
		{0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0},
		{1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2}
	},
	{
		{2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2},
		{0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1}
	},
	{
		{0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0},
		{1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2}
	},
	{
		{2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2},
		{0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1}
	},
	{
		{2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2},
		{0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1}
	},
	{
		{0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0},
		{1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2}
	},
	{
		{2, 0, 1}, {0, 1, 2}, {2, 0, 1}, {0, 1, 2},
		{0, 1, 2}, {2, 0, 1}, {0, 1, 2}, {2, 0, 1}
	},
	{
		{0, 1, 2}, {1, 2, 0}, {0, 1, 2}, {1, 2, 0},
		{1, 2, 0}, {0, 1, 2}, {1, 2, 0}, {0, 1, 2}
	}
};

static bool parse_int_list(const char *text, int *out, int expected, int min, int max)
{
	char *copy, *token, *end;
	int count = 0;
	long value;

	copy = strdup(text);
	if (copy == NULL)
		return false;

	for (token = strtok(copy, ","); token != NULL; token = strtok(NULL, ",")) {
		if (count >= expected) {
			free(copy);
			return false;
		}
		value = strtol(token, &end, 10);
		if (*token == '\0' || *end != '\0' || value < min || value > max) {
			free(copy);
			return false;
		}
		out[count++] = (int)value;
	}

	free(copy);
	return count == expected;
}

static bool bridge_is_perm(const int *values, int n)
{
	bool seen[12] = { false };
	int i;

	for (i = 0; i < n; i++) {
		if (values[i] < 0 || values[i] >= n || seen[values[i]])
			return false;
		seen[values[i]] = true;
	}

	return true;
}

static int sum_mod(const int *values, int n, int mod)
{
	int i, sum = 0;

	for (i = 0; i < n; i++)
		sum = (sum + values[i]) % mod;

	return sum;
}

static bool arrays_equal(const int *left, const int *right, int n)
{
	int i;

	for (i = 0; i < n; i++)
		if (left[i] != right[i])
			return false;

	return true;
}

static void debug_compare_arrays(Cube bridge, Cube expected)
{
	CubeArray *b = new_cubearray(bridge, pf_all);
	CubeArray *e = new_cubearray(expected, pf_all);

	fprintf(stderr, "debug_ep_equal=%s\n", arrays_equal(b->ep, e->ep, 12) ? "true" : "false");
	fprintf(stderr, "debug_eofb_equal=%s\n", arrays_equal(b->eofb, e->eofb, 12) ? "true" : "false");
	fprintf(stderr, "debug_eorl_equal=%s\n", arrays_equal(b->eorl, e->eorl, 12) ? "true" : "false");
	fprintf(stderr, "debug_eoud_equal=%s\n", arrays_equal(b->eoud, e->eoud, 12) ? "true" : "false");
	fprintf(stderr, "debug_cp_equal=%s\n", arrays_equal(b->cp, e->cp, 8) ? "true" : "false");
	fprintf(stderr, "debug_coud_equal=%s\n", arrays_equal(b->coud, e->coud, 8) ? "true" : "false");
	fprintf(stderr, "debug_cofb_equal=%s\n", arrays_equal(b->cofb, e->cofb, 8) ? "true" : "false");
	fprintf(stderr, "debug_corl_equal=%s\n", arrays_equal(b->corl, e->corl, 8) ? "true" : "false");
	fprintf(stderr, "debug_cpos_equal=%s\n", arrays_equal(b->cpos, e->cpos, 6) ? "true" : "false");

	free_cubearray(b, pf_all);
	free_cubearray(e, pf_all);
}

static Cube cube_from_local_arrays(int *local_cp, int *local_co, int *local_ep, int *local_eo)
{
	int cp[8], coud[8], cofb[8], corl[8];
	int ep[12], eofb[12], eorl[12], eoud[12];
	int cpos[6] = { 0, 1, 2, 3, 4, 5 };
	CubeArray arr = {
		.ep = ep,
		.eofb = eofb,
		.eorl = eorl,
		.eoud = eoud,
		.cp = cp,
		.coud = coud,
		.corl = corl,
		.cofb = cofb,
		.cpos = cpos,
	};
	int i, local_pos, local_cubie;

	for (i = 0; i < 8; i++) {
		cp[i] = local_cp[i];
		coud[i] = local_co[i];
		cofb[i] = corner_cofb_from_coud[i][cp[i]][coud[i]];
		corl[i] = corner_corl_from_coud[i][cp[i]][coud[i]];
	}

	for (i = 0; i < 12; i++) {
		local_pos = nissy_edge_to_local[i];
		local_cubie = local_ep[local_pos];
		ep[i] = local_edge_to_nissy[local_cubie];
		eofb[i] = local_eo[local_pos];
	}
	fix_eorleoud(&arr);

	return arrays_to_cube(&arr, pf_all);
}

int main(int argc, char **argv)
{
	int cp[8], co[8], ep[12], eo[12];
	int threads = 1;
	int i;
	Cube cube;
	AlgList *solutions;
	SolveOptions opts = {
		.min_moves = 0,
		.max_moves = 20,
		.max_solutions = 1,
		.nthreads = 1,
		.optimal = 0,
		.nisstype = NORMAL,
		.verbose = false,
		.all = false,
		.print_number = true,
		.count_only = false,
	};

	if (argc != 6) {
		fprintf(stderr, "usage: %s CP CO EP EO THREADS\n", argv[0]);
		return 2;
	}

	if (!parse_int_list(argv[1], cp, 8, 0, 7) ||
	    !parse_int_list(argv[2], co, 8, 0, 2) ||
	    !parse_int_list(argv[3], ep, 12, 0, 11) ||
	    !parse_int_list(argv[4], eo, 12, 0, 1)) {
		fprintf(stderr, "invalid cubie coordinate list\n");
		return 2;
	}

	threads = atoi(argv[5]);
	if (threads < 1 || threads > 64) {
		fprintf(stderr, "invalid thread count\n");
		return 2;
	}
	if (!bridge_is_perm(cp, 8) || !bridge_is_perm(ep, 12) || sum_mod(co, 8, 3) != 0 || sum_mod(eo, 12, 2) != 0) {
		fprintf(stderr, "invalid physical cubie coordinates\n");
		return 2;
	}

	init_env();
	init_all_movesets();
	init_symcoord();

	cube = cube_from_local_arrays(cp, co, ep, eo);
	if (getenv("NISSY2_BRIDGE_DEBUG_ALG") != NULL) {
		Alg *debug_alg = new_alg(getenv("NISSY2_BRIDGE_DEBUG_ALG"));
		if (debug_alg != NULL) {
			Cube expected = apply_alg(debug_alg, (Cube){0});
			fprintf(stderr, "debug_equal_expected=%s\n", equal(cube, expected) ? "true" : "false");
			debug_compare_arrays(cube, expected);
			fprintf(stderr, "debug_bridge: ");
			print_cube(cube);
			fprintf(stderr, "debug_expected: ");
			print_cube(expected);
			free_alg(debug_alg);
		}
		if (getenv("NISSY2_BRIDGE_DEBUG_ONLY") != NULL)
			return 0;
	}
	if (!is_admissible(cube)) {
		fprintf(stderr, "nissy cube is not admissible\n");
		return 2;
	}

	opts.nthreads = threads;
	solutions = solve(cube, &optimal_HTM, &opts);
	if (solutions == NULL || solutions->len == 0) {
		if (solutions != NULL)
			free_alglist(solutions);
		fprintf(stderr, "no optimal solution returned\n");
		return 3;
	}

	sort_alglist(solutions);
	print_alglist(stdout, solutions, true);
	free_alglist(solutions);

	for (i = 0; i < 1; i++) {
		/* Keep C99 compilers from warning if future builds change init side effects. */
	}

	return 0;
}
