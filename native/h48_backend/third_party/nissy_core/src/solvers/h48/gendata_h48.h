STATIC long long gendata_h48_dispatch(
    const char *, unsigned long long, unsigned char *);
STATIC uint64_t gendata_h48short(gendata_h48short_arg_t [NON_NULL]);
STATIC int64_t gendata_h48(gendata_h48_arg_t [NON_NULL]);
STATIC void gendata_h48_maintable(gendata_h48_arg_t [NON_NULL]);
STATIC wrapthread_return_t gendata_h48_runthread(void *);
STATIC void gendata_h48_set_expected_distribution(
    uint64_t [SIZE(INFO_DISTRIBUTION_LEN)], uint8_t);

STATIC_INLINE void gendata_h48_mark(gendata_h48_mark_t [NON_NULL]);
STATIC_INLINE bool gendata_h48_dfs_stop(
    cube_t, int8_t, h48_dfs_arg_t [NON_NULL]);
STATIC void gendata_h48_dfs(h48_dfs_arg_t [NON_NULL]);
STATIC tableinfo_t makeinfo_h48(gendata_h48_arg_t [NON_NULL]);

STATIC const uint32_t *get_cocsepdata_constptr(const unsigned char *);
STATIC const unsigned char *get_h48data_constptr(const unsigned char *);

STATIC_INLINE uint8_t get_h48_pval(const unsigned char *, uint64_t);
STATIC_INLINE void set_h48_pval(unsigned char *, uint64_t, uint8_t);
STATIC_INLINE uint8_t get_h48_pvalmin(const unsigned char *, uint64_t);
STATIC_INLINE void set_h48_pvalmin(unsigned char *, uint64_t, uint8_t);
STATIC_INLINE uint8_t get_h48_pval_atomic(
    const wrapthread_atomic unsigned char *, uint64_t);
STATIC_INLINE void set_h48_pval_atomic_min(
    wrapthread_atomic unsigned char *, uint64_t, uint8_t);
STATIC_INLINE void set_h48_pvalmin_atomic(
    wrapthread_atomic unsigned char *, uint64_t, uint8_t);
STATIC_INLINE uint8_t get_h48_pval_and_min(
    const unsigned char *, uint64_t, uint8_t [NON_NULL]);

#ifndef H48_GENDATA_WORKBATCH
#define H48_GENDATA_WORKBATCH 256
#endif

#ifndef H48_GENDATA_USE_EXPECTED_DISTRIBUTION
#define H48_GENDATA_USE_EXPECTED_DISTRIBUTION 0
#endif

STATIC_INLINE uint64_t h48_atomic_fetch_add_u64(
    wrapthread_atomic uint64_t *, uint64_t);
STATIC_INLINE uint64_t h48_atomic_load_u64(
    const wrapthread_atomic uint64_t *);

STATIC long long
gendata_h48_dispatch(
	const char *solver,
	unsigned long long data_size,
	unsigned char *data
)
{
	long long err;
	gendata_h48_arg_t arg;

	err = parse_h48h(solver, &arg.h);
	if (err != NISSY_OK)
		return err;

	arg.buf_size = data_size;
	arg.buf = data;
	arg.maxdepth = 20;

	return gendata_h48(&arg);
}

STATIC uint64_t
gendata_h48short(gendata_h48short_arg_t arg[NON_NULL])
{
	uint8_t i, m;
	uint8_t t, ttrep;
	uint32_t cdata;
	uint64_t coord;
	uint64_t coclass, cocsep, selfsim;
	uint64_t j;
	kvpair_t kv;
	cube_t cube, d, edge_rep, edge_sym;

	cube = SOLVED_CUBE;
	coord = coord_h48(cube, arg->cocsepdata, 11);
	h48map_insertmin(arg->map, coord, 0);
	for (i = 0; i < arg->maxdepth; i++) {
		j = 0;
		for (kv = h48map_nextkvpair(arg->map, &j);
		     j != arg->map->capacity;
		     kv = h48map_nextkvpair(arg->map, &j)
		) {
			if (kv.val != i)
				continue;
			cube = invcoord_h48(kv.key, arg->crep, 11);
			for (m = 0; m < 18; m++) {
				d = move(cube, m);
				cocsep = coord_cocsep(d);
				cdata = arg->cocsepdata[cocsep];
				coclass = COCLASS(cdata);
				ttrep = TTREP(cdata);
				edge_rep = transform_edges(d, ttrep);
				selfsim = arg->selfsim[coclass];
				for (t = 0; t < NTRANS && selfsim; t++, selfsim >>= 1) {
					if (!(selfsim & 1))
						continue;
					edge_sym = transform_edges(edge_rep, t);
					coord = coord_h48_edges_rep(edge_sym, coclass, 11);
					h48map_insertmin(arg->map, coord, i+1);
				}
			}
		}
	}

	return arg->map->n;
}

STATIC int64_t
gendata_h48(gendata_h48_arg_t arg[NON_NULL])
{
	uint64_t size, cocsepsize, h48size, eoesepsize;
	long long r;
	unsigned char *cocsepdata_offset;
	tableinfo_t cocsepinfo, h48info;

	cocsepsize = COCSEP_FULLSIZE;
	h48size = INFOSIZE + H48_TABLESIZE(arg->h);
	eoesepsize = EOESEP_FULLSIZE;

	size = cocsepsize + h48size + eoesepsize;

	if (arg->buf == NULL)
		return size; /* Dry-run */

	if (arg->buf_size < size) {
		LOG("[H48 gendata] Error: buffer is too small "
		    "(needed %" PRId64 " bytes but received %" PRIu64 ")\n",
		    size, arg->buf_size);
		return NISSY_ERROR_BUFFER_SIZE;
	}

	gendata_cocsep(arg->buf, arg->selfsim, arg->crep);

	cocsepdata_offset = arg->buf + INFOSIZE;
	arg->cocsepdata = (uint32_t *)cocsepdata_offset;
	arg->h48buf = (wrapthread_atomic unsigned char*)arg->buf + cocsepsize;

	/* Compute the main H48 table with two bits per entry */
	gendata_h48_maintable(arg);

	r = readtableinfo(arg->buf_size, arg->buf, &cocsepinfo);
	if (r != NISSY_OK) {
		LOG("[H48 gendata] Error: could not read info "
		    "for cocsep table\n");
		return NISSY_ERROR_UNKNOWN;
	}

	cocsepinfo.next = cocsepsize;
	r = writetableinfo(&cocsepinfo, arg->buf_size, arg->buf);
	if (r != NISSY_OK) {
		LOG("[H48 gendata] Error: could not write info for "
		    "cocsep table with updated 'next' value\n");
		return NISSY_ERROR_UNKNOWN;
	}

	/* Add eoesep fallback table */

	gendata_eoesep(arg->buf + (size - eoesepsize), 20);

	/* Update tableinfo with correct next values */

	r = readtableinfo_n(arg->buf_size, arg->buf, 2, &h48info);
	if (r != NISSY_OK) {
		LOG("[H48 gendata] Error: could not read info "
		    "for h48 table\n");
		return NISSY_ERROR_UNKNOWN;
	}
	h48info.next = h48size;
	r = writetableinfo(&h48info,
	     arg->buf_size - cocsepsize, arg->buf + cocsepsize);
	if (r != NISSY_OK) {
		LOG("[H48 gendata] Error: could not write info "
		    "for h48 table\n");
		return NISSY_ERROR_UNKNOWN;
	}

	return size;
}

STATIC void
gendata_h48_maintable(gendata_h48_arg_t arg[NON_NULL])
{
	/*
	 * A good base value for the h48 tables have few positions with value
	 * 0, because those are treated as lower bound 0 and require a second
	 * lookup in another table, and at the same time not too many positions
	 * with value 3, because some of those are under-estimates.
	 *
	 * The following values for the base have been hand-picked. I first
	 * performed some statistics on the frequency of these values, but
	 * they turned out to be unreliable. In the end I generated the same
	 * table with multiple base value and see what was best.
	 *
	 * A curious case is h3, which has this distribution for base 8:
	 *   [0] = 6686828
	 *   [1] = 63867852
	 *   [2] = 392789689
	 *   [3] = 477195231
	 *
	 * and this for base 9:
	 *   [0] = 70554680
	 *   [1] = 392789689
	 *   [2] = 462294676
	 *   [3] = 14900555
	 *
	 * Experimentally, the table with base 8 is much faster. Intuitively,
	 * this is because it has a much lower count of elements  with value 0,
         * at the cost of a less precise estimate for the higher values.
	 */
	 
	static const uint8_t base[] = {
		[0]  = 8,
		[1]  = 8,
		[2]  = 8,
		[3]  = 8,
		[4]  = 9,
		[5]  = 9,
		[6]  = 9,
		[7]  = 9,
		[8]  = 10,
		[9]  = 10,
		[10] = 10,
		[11] = 10
	};

	static const uint8_t shortdepth = 8;
	static const uint64_t capacity = 10000019;
	static const uint64_t randomizer = 10000079;

	int sleeptime;
	unsigned char *table;
	wrapthread_atomic unsigned char *table_atomic;
	wrapthread_atomic uint64_t count;
	wrapthread_atomic uint64_t next;
	uint64_t i, bufsize, done, nshort, scanned_done, velocity;
	wrapthread_atomic uint64_t scanned;
	h48map_t shortcubes;
	gendata_h48short_arg_t shortarg;
	h48_dfs_arg_t dfsarg[THREADS];
	wrapthread_define_var_thread_t(thread[THREADS]);

	table_atomic = arg->h48buf + INFOSIZE;
	table = (unsigned char *)table_atomic;
	memset(table, 0xFF, H48_TABLESIZE(arg->h));

	LOG("[H48 gendata] Computing depth <=%" PRIu8 "\n", shortdepth)
	h48map_create(&shortcubes, capacity, randomizer);
	shortarg = (gendata_h48short_arg_t) {
		.maxdepth = shortdepth,
		.cocsepdata = arg->cocsepdata,
		.crep = arg->crep,
		.selfsim = arg->selfsim,
		.map = &shortcubes
	};
	gendata_h48short(&shortarg);
	nshort = shortarg.map->n;
	LOG("[H48 gendata] Computed %" PRIu64 " positions\n", nshort);

	arg->base = base[arg->h];
	arg->info = makeinfo_h48(arg);

	next = 0;
	scanned = 0;
	count = 0;
	for (i = 0; i < THREADS; i++) {
		dfsarg[i] = (h48_dfs_arg_t){
			.h = arg->h,
			.base = arg->base,
			.shortdepth = shortdepth,
			.cocsepdata = arg->cocsepdata,
			.table = table,
			.table_atomic = table_atomic,
			.selfsim = arg->selfsim,
			.crep = arg->crep,
			.shortcubes = &shortcubes,
			.next = &next,
			.scanned = &scanned,
			.count = &count,
		};

		wrapthread_create(
		    &thread[i], gendata_h48_runthread, &dfsarg[i]);
	}

	if (NISSY_CANSLEEP) {
		/* Log the progress periodically */
		LOG("[H48 gendata] Processing 'short cubes'. "
		    "This will take a while.\n");

		/* Estimate velocity by checking how much is done after 1s */
		msleep(1000);
		velocity = h48_atomic_load_u64(&count);

		/*
		 * For large h-values the first work batch may take more than a
		 * second, so the initial velocity can be zero. Keep progress
		 * reporting bounded instead of spinning and flooding stderr.
		 */
		if (velocity == 0) {
			sleeptime = 10000;
		} else {
			/* We plan to log about 10 times */
			sleeptime = (int)((100*(nshort-velocity)) / velocity);
			if (sleeptime < 1000)
				sleeptime = 1000;
			if (sleeptime > 60000)
				sleeptime = 60000;
		}

		done = h48_atomic_load_u64(&count);
		while (done < nshort) {
			msleep(sleeptime);
			done = h48_atomic_load_u64(&count);
			scanned_done = h48_atomic_load_u64(dfsarg[0].scanned);
			LOG("[H48 gendata] Scanned %" PRIu64 " / %" PRIu64
			    " slots; Processed %" PRIu64 " / %" PRIu64
			    " cubes\n", scanned_done, shortcubes.capacity, done, nshort);
		}
	} else {
		LOG("Status updates won't be available because the sleep() "
		    "functionality is not available on this platform.\n");
	}

	for (i = 0; i < THREADS; i++)
		wrapthread_join(thread[i]);

	h48map_destroy(&shortcubes);

#if H48_GENDATA_USE_EXPECTED_DISTRIBUTION
	LOG("[H48 gendata] Using built-in expected H48 distribution; "
	    "skipping full generated-table distribution scan\n");
	gendata_h48_set_expected_distribution(
	    arg->info.distribution, arg->h);
#else
	getdistribution_h48(table, arg->info.distribution, &arg->info);
#endif

	bufsize = arg->buf_size - COCSEP_FULLSIZE;
	writetableinfo(&arg->info, bufsize, (unsigned char *)arg->h48buf);
}

STATIC void
gendata_h48_set_expected_distribution(
	uint64_t distr[SIZE(INFO_DISTRIBUTION_LEN)],
	uint8_t h
)
{
	static const uint64_t expected[12][4] = {
		[0]  = { 5473562, 34776317, 68566704, 8750867 },
		[1]  = { 6012079, 45822302, 142018732, 41281787 },
		[2]  = { 6391286, 55494785, 252389935, 155993794 },
		[3]  = { 6686828, 63867852, 392789689, 477195231 },
		[4]  = { 77147213, 543379415, 1139570251, 120982321 },
		[5]  = { 82471284, 687850732, 2345840746, 645995638 },
		[6]  = { 85941099, 804752968, 4077248182, 2556374551 },
		[7]  = { 88529761, 897323475, 6126260791, 7936519573 },
		[8]  = { 1051579940, 8136021316, 19024479822, 1885186122 },
		[9]  = { 1102038189, 9888265242, 38299375805, 10904855164 },
		[10] = { 1133240039, 11196285614, 64164702961, 43894840186 },
		[11] = { 1150763161, 12045845660, 91163433330, 136418095449 },
	};
	uint8_t i;

	memset(distr, 0, INFO_DISTRIBUTION_LEN * sizeof(uint64_t));
	for (i = 0; i < 4; i++)
		distr[i] = expected[h][i];
}

STATIC wrapthread_return_t 
gendata_h48_runthread(void *arg)
{
	uint64_t coord, coordext, coordmin, end, i, local_count, local_scanned, pair, start;
	kvpair_t kv;
	h48_dfs_arg_t *dfsarg;

	dfsarg = (h48_dfs_arg_t *)arg;

	while (true) {
		start = h48_atomic_fetch_add_u64(
		    dfsarg->next, H48_GENDATA_WORKBATCH);
		if (start >= dfsarg->shortcubes->capacity) {
			break;
		}
		end = MIN(start + H48_GENDATA_WORKBATCH, dfsarg->shortcubes->capacity);

		local_scanned = end - start;
		local_count = 0;
		for (i = start; i < end; i++) {
			if (dfsarg->shortcubes->table[i] == MAP_UNSET)
				continue;

			pair = dfsarg->shortcubes->table[i];
			kv.key = pair & MAP_KEYMASK;
			kv.val = pair >> MAP_KEYSHIFT;
			local_count++;

			if (kv.val < dfsarg->shortdepth) {
				coord = kv.key >> (uint64_t)(11 - dfsarg->h);
				coordext = H48_LINE_EXT(coord);
				coordmin = H48_LINE_MIN(coord);

				set_h48_pval_atomic_min(
				    dfsarg->table_atomic, coordext, 0);
				set_h48_pvalmin_atomic(
				    dfsarg->table_atomic,
				    coordmin,
				    (uint8_t)kv.val);
			} else {
				dfsarg->cube = invcoord_h48(kv.key, dfsarg->crep, 11);
				gendata_h48_dfs(dfsarg);
			}
		}

		h48_atomic_fetch_add_u64(dfsarg->scanned, local_scanned);
		h48_atomic_fetch_add_u64(dfsarg->count, local_count);
	}

	return wrapthread_return_val;
}

STATIC_INLINE uint64_t
h48_atomic_fetch_add_u64(wrapthread_atomic uint64_t *ptr, uint64_t value)
{
#if THREADS == 1
	uint64_t previous;

	previous = *ptr;
	*ptr += value;
	return previous;
#else
	return atomic_fetch_add_explicit(ptr, value, memory_order_relaxed);
#endif
}

STATIC_INLINE uint64_t
h48_atomic_load_u64(const wrapthread_atomic uint64_t *ptr)
{
#if THREADS == 1
	return *ptr;
#else
	return atomic_load_explicit(ptr, memory_order_relaxed);
#endif
}

STATIC void
gendata_h48_dfs(h48_dfs_arg_t arg[NON_NULL])
{
	int8_t d;
	uint8_t m[4];
	cube_t cube[4];
	gendata_h48_mark_t markarg;

	markarg = (gendata_h48_mark_t) {
		.h = arg->h,
		.base = arg->base,
		.cocsepdata = arg->cocsepdata,
		.selfsim = arg->selfsim,
		.table = arg->table,
		.table_atomic = arg->table_atomic,
	};

	d = (int8_t)arg->shortdepth - (int8_t)arg->base;

	/* Depth d+0 (shortcubes) */
	markarg.depth = d;
	markarg.cube = arg->cube;
	gendata_h48_mark(&markarg);

	/* Depth d+1 */
	for (m[0] = 0; m[0] < 18; m[0]++) {
		markarg.depth = d+1;
		cube[0] = move(arg->cube, m[0]);
		if (gendata_h48_dfs_stop(cube[0], d+1, arg))
			continue;
		markarg.cube = cube[0];
		gendata_h48_mark(&markarg);

		/* Depth d+2 */
		for (m[1] = 0; m[1] < 18; m[1]++) {
			markarg.depth = d+2;
			if (m[0] / 3 == m[1] / 3) {
				m[1] += 2;
				continue;
			}
			cube[1] = move(cube[0], m[1]);
			if (gendata_h48_dfs_stop(cube[1], d+2, arg))
				continue;
			markarg.cube = cube[1];
			gendata_h48_mark(&markarg);
			if (d >= 0)
				continue;

			/* Depth d+3 */
			for (m[2] = 0; m[2] < 18; m[2]++) {
				markarg.depth = d+3;
				if (!allowednextmove(m[1], m[2])) {
					m[2] += 2;
					continue;
				}
				cube[2] = move(cube[1], m[2]);
				if (gendata_h48_dfs_stop(cube[2], d+3, arg))
					continue;
				markarg.cube = cube[2];
				gendata_h48_mark(&markarg);
				if (d >= -1)
					continue;

				/* Depth d+4 */
				for (m[3] = 0; m[3] < 18; m[3]++) {
					markarg.depth = d+4;
					if (!allowednextmove(m[2], m[3])) {
						m[3] += 2;
						continue;
					}
					cube[3] = move(cube[2], m[3]);
					markarg.cube = cube[3];
					gendata_h48_mark(&markarg);
				}
			}
		}
	}
}

STATIC_INLINE void
gendata_h48_mark(gendata_h48_mark_t arg[NON_NULL])
{
	uint8_t newval, v;
	uint8_t t, ttrep;
	uint32_t cdata;
	uint64_t coclass, cocsep, coord, coordext, coordmin, selfsim;
	cube_t edge_rep, edge_sym;

	cocsep = coord_cocsep(arg->cube);
	cdata = arg->cocsepdata[cocsep];
	coclass = COCLASS(cdata);
	ttrep = TTREP(cdata);
	edge_rep = transform_edges(arg->cube, ttrep);
	selfsim = arg->selfsim[coclass];

	for (t = 0; t < NTRANS && selfsim; t++, selfsim >>= 1) {
		if (!(selfsim & 1))
			continue;

		edge_sym = transform_edges(edge_rep, t);
		coord = coord_h48_edges_rep(edge_sym, coclass, arg->h);
		coordext = H48_LINE_EXT(coord);
		coordmin = H48_LINE_MIN(coord);

		newval = (uint8_t)MAX(arg->depth, 0);
		set_h48_pval_atomic_min(arg->table_atomic, coordext, newval);
		v = arg->depth + arg->base;
		set_h48_pvalmin_atomic(arg->table_atomic, coordmin, v);
	}
}

STATIC_INLINE bool
gendata_h48_dfs_stop(cube_t cube, int8_t d, h48_dfs_arg_t arg[NON_NULL])
{
	uint64_t val;
	uint64_t coord, coordext;
	int8_t oldval;

	if (arg->h == 0 || arg->h == 11) {
		/* We are in the "real coordinate" case, we can stop
		   if this coordinate has already been visited */
		coord = coord_h48(cube, arg->cocsepdata, arg->h);
		coordext = H48_LINE_EXT(coord);
		oldval = get_h48_pval_atomic(arg->table_atomic, coordext);
		return oldval <= d;
	} else {
		/* With 0 < h < 11 we do not have a "real coordinate".
		   The best we can do is checking if we backtracked to
		   one of the "short cubes". */
		coord = coord_h48(cube, arg->cocsepdata, 11);
		val = h48map_value(arg->shortcubes, coord);
		return val <= arg->shortdepth;
	}
}

STATIC tableinfo_t
makeinfo_h48(gendata_h48_arg_t arg[NON_NULL])
{
	tableinfo_t info;

	info = (tableinfo_t) {
		.solver = "h48 solver h =  ",
		.type = TABLETYPE_PRUNING,
		.infosize = INFOSIZE,
		.fullsize = H48_TABLESIZE(arg->h) + INFOSIZE,
		.hash = 0,
		.entries = H48_COORDMAX(arg->h) + 2 * H48_LINES(arg->h),
		.classes = 0,
		.h48h = arg->h,
		.bits = 2,
		.base = arg->base,
		.maxvalue = 3,
		.next = 0,
	};
	info.solver[15] = (arg->h % 10) + '0';
	if (arg->h >= 10)
		info.solver[14] = (arg->h / 10) + '0';

	return info;
}

STATIC const uint32_t *
get_cocsepdata_constptr(const unsigned char *data)
{
	return (uint32_t *)(data + INFOSIZE);
}

STATIC const unsigned char *
get_h48data_constptr(const unsigned char *data)
{
	return data + COCSEP_FULLSIZE + INFOSIZE;
}

STATIC_INLINE uint8_t
get_h48_pval(const unsigned char *table, uint64_t i)
{
	return (table[H48_INDEX(i)] & H48_MASK(i)) >> H48_SHIFT(i);
}

STATIC_INLINE uint8_t
get_h48_pvalmin(const unsigned char *table, uint64_t i)
{
	return table[H48_INDEX(i)] >> UINT8_C(4);
}

STATIC_INLINE void
set_h48_pval(unsigned char *table, uint64_t i, uint8_t val)
{
	table[H48_INDEX(i)] = (table[H48_INDEX(i)] & (~H48_MASK(i)))
	    | (val << H48_SHIFT(i));
}

STATIC_INLINE void
set_h48_pvalmin(unsigned char *table, uint64_t i, uint8_t val)
{
	uint8_t t, v;

	v = MIN(val, get_h48_pvalmin(table, i));
	t = table[H48_INDEX(i)];
	table[H48_INDEX(i)] = (t & UINT8_C(0xF)) | (v << UINT8_C(4));
}

STATIC_INLINE uint8_t
get_h48_pval_atomic(const wrapthread_atomic unsigned char *table, uint64_t i)
{
#if THREADS == 1
	return get_h48_pval((const unsigned char *)table, i);
#else
	unsigned char t;

	t = atomic_load_explicit(&table[H48_INDEX(i)], memory_order_relaxed);
	return (t & H48_MASK(i)) >> H48_SHIFT(i);
#endif
}

STATIC_INLINE void
set_h48_pval_atomic_min(
	wrapthread_atomic unsigned char *table,
	uint64_t i,
	uint8_t val
)
{
#if THREADS == 1
	uint8_t oldval;

	oldval = get_h48_pval((const unsigned char *)table, i);
	set_h48_pval((unsigned char *)table, i, MIN(val, oldval));
#else
	unsigned char desired, old;
	uint8_t mask, newval, oldval, shift;
	wrapthread_atomic unsigned char *cell;

	cell = &table[H48_INDEX(i)];
	mask = H48_MASK(i);
	shift = H48_SHIFT(i);
	old = atomic_load_explicit(cell, memory_order_relaxed);

	while (true) {
		oldval = (old & mask) >> shift;
		newval = MIN(val, oldval);
		if (newval == oldval)
			return;

		desired = (unsigned char)(
		    (old & (uint8_t)(~mask)) | (newval << shift));
		if (atomic_compare_exchange_weak_explicit(
		    cell,
		    &old,
		    desired,
		    memory_order_relaxed,
		    memory_order_relaxed
		))
			return;
	}
#endif
}

STATIC_INLINE void
set_h48_pvalmin_atomic(
	wrapthread_atomic unsigned char *table,
	uint64_t i,
	uint8_t val
)
{
#if THREADS == 1
	set_h48_pvalmin((unsigned char *)table, i, val);
#else
	unsigned char desired, old;
	uint8_t newval, oldval;
	wrapthread_atomic unsigned char *cell;

	cell = &table[H48_INDEX(i)];
	old = atomic_load_explicit(cell, memory_order_relaxed);

	while (true) {
		oldval = old >> UINT8_C(4);
		newval = MIN(val, oldval);
		if (newval == oldval)
			return;

		desired = (unsigned char)(
		    (old & UINT8_C(0xF)) | (newval << UINT8_C(4)));
		if (atomic_compare_exchange_weak_explicit(
		    cell,
		    &old,
		    desired,
		    memory_order_relaxed,
		    memory_order_relaxed
		))
			return;
	}
#endif
}

STATIC_INLINE uint8_t
get_h48_pval_and_min(
	const unsigned char *table,
	uint64_t coord_noext,
	uint8_t pval_min[NON_NULL]
)
{
	uint64_t iext, imin;
	uint8_t t, tmin;

	iext = H48_LINE_EXT(coord_noext);
	imin = H48_LINE_MIN(coord_noext);
	t = table[H48_INDEX(iext)];
	tmin = table[H48_INDEX(imin)];

	*pval_min = tmin >> UINT8_C(4);
	return (t & H48_MASK(iext)) >> H48_SHIFT(iext);
}
