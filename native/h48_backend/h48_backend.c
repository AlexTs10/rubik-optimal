// In-repository native H48 backend wrapper.
//
// This file provides a small JSON-speaking executable around the vendored
// nissy-core H48 API. The thesis Python layer uses it for reproducible table
// generation and exact-or-timeout optimal solve probes.

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "nissy.h"

typedef struct {
    const char* mode;
    const char* solver;
    const char* output_path;
    const char* table_path;
    const char* sequence;
    const char* cube;
    unsigned threads;
    unsigned min_depth;
    unsigned max_depth;
    bool skip_table_check;
    bool preload_table;
    bool generate_mmap;
    bool progress_log;
    bool auto_min_depth;
    const char* mmap_sync_mode;
    unsigned search_timeout_ms;
} Options;

typedef struct {
    unsigned char* data;
    unsigned long long size;
    bool mapped;
} LoadedTable;

typedef struct {
    bool enabled;
    double deadline_seconds;
    bool timed_out;
} SolveDeadline;

static double now_seconds(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static void json_string(FILE* out, const char* value) {
    fputc('"', out);
    if (value != NULL) {
        for (const unsigned char* p = (const unsigned char*)value; *p != '\0'; ++p) {
            switch (*p) {
                case '\\':
                    fputs("\\\\", out);
                    break;
                case '"':
                    fputs("\\\"", out);
                    break;
                case '\n':
                    fputs("\\n", out);
                    break;
                case '\r':
                    fputs("\\r", out);
                    break;
                case '\t':
                    fputs("\\t", out);
                    break;
                default:
                    if (*p < 0x20) {
                        fprintf(out, "\\u%04x", *p);
                    } else {
                        fputc(*p, out);
                    }
            }
        }
    }
    fputc('"', out);
}

static void print_error_json(const char* status, const char* message) {
    fputs("{\"status\":", stdout);
    json_string(stdout, status);
    fputs(",\"error\":", stdout);
    json_string(stdout, message);
    fputs("}\n", stdout);
}

static void stderr_logger(const char* message, void* user_data) {
    (void)user_data;
    fputs(message, stderr);
    fflush(stderr);
}

static int poll_deadline_status(void* user_data) {
    SolveDeadline* deadline = (SolveDeadline*)user_data;
    if (deadline != NULL && deadline->enabled && now_seconds() >= deadline->deadline_seconds) {
        deadline->timed_out = true;
        return NISSY_STATUS_STOP;
    }
    return NISSY_STATUS_RUN;
}

static bool parse_uint(const char* value, unsigned* out) {
    char* end = NULL;
    unsigned long parsed;
    errno = 0;
    parsed = strtoul(value, &end, 10);
    if (errno != 0 || end == value || *end != '\0' || parsed > UINT32_MAX) {
        return false;
    }
    *out = (unsigned)parsed;
    return true;
}

static bool valid_mmap_sync_mode(const char* value) {
    return value != NULL && (
        !strcmp(value, "sync") ||
        !strcmp(value, "async") ||
        !strcmp(value, "none")
    );
}

static bool parse_args(int argc, char** argv, Options* options) {
    *options = (Options){
        .mode = NULL,
        .solver = "h48h0",
        .output_path = NULL,
        .table_path = NULL,
        .sequence = NULL,
        .cube = NULL,
        .threads = 1,
        .min_depth = 0,
        .max_depth = 20,
        .skip_table_check = false,
        .preload_table = false,
        .generate_mmap = false,
        .progress_log = false,
        .auto_min_depth = false,
        .mmap_sync_mode = "sync",
        .search_timeout_ms = 0,
    };
    for (int i = 1; i < argc; ++i) {
        const char* arg = argv[i];
        if (
            !strcmp(arg, "--generate") ||
            !strcmp(arg, "--solve") ||
            !strcmp(arg, "--solve-batch") ||
            !strcmp(arg, "--lower-bound") ||
            !strcmp(arg, "--lower-bound-batch")
        ) {
            options->mode = arg + 2;
        } else if (!strcmp(arg, "--solver") && i + 1 < argc) {
            options->solver = argv[++i];
        } else if (!strcmp(arg, "--output") && i + 1 < argc) {
            options->output_path = argv[++i];
        } else if (!strcmp(arg, "--table") && i + 1 < argc) {
            options->table_path = argv[++i];
        } else if (!strcmp(arg, "--sequence") && i + 1 < argc) {
            options->sequence = argv[++i];
        } else if (!strcmp(arg, "--cube") && i + 1 < argc) {
            options->cube = argv[++i];
        } else if (!strcmp(arg, "--threads") && i + 1 < argc) {
            if (!parse_uint(argv[++i], &options->threads)) {
                return false;
            }
        } else if (!strcmp(arg, "--min-depth") && i + 1 < argc) {
            if (!parse_uint(argv[++i], &options->min_depth)) {
                return false;
            }
        } else if (!strcmp(arg, "--max-depth") && i + 1 < argc) {
            if (!parse_uint(argv[++i], &options->max_depth)) {
                return false;
            }
        } else if (!strcmp(arg, "--search-timeout-ms") && i + 1 < argc) {
            if (!parse_uint(argv[++i], &options->search_timeout_ms)) {
                return false;
            }
        } else if (!strcmp(arg, "--skip-table-check")) {
            options->skip_table_check = true;
        } else if (!strcmp(arg, "--preload-table")) {
            options->preload_table = true;
        } else if (!strcmp(arg, "--generate-mmap")) {
            options->generate_mmap = true;
        } else if (!strcmp(arg, "--mmap-sync-mode") && i + 1 < argc) {
            options->mmap_sync_mode = argv[++i];
            if (!valid_mmap_sync_mode(options->mmap_sync_mode)) {
                return false;
            }
        } else if (!strcmp(arg, "--progress-log")) {
            options->progress_log = true;
        } else if (!strcmp(arg, "--auto-min-depth")) {
            options->auto_min_depth = true;
        } else {
            return false;
        }
    }
    return options->mode != NULL && options->solver != NULL;
}

static int write_all(const char* path, const unsigned char* data, size_t size) {
    FILE* file = fopen(path, "wb");
    if (file == NULL) {
        return -1;
    }
    if (fwrite(data, 1, size, file) != size) {
        fclose(file);
        return -1;
    }
    if (fclose(file) != 0) {
        return -1;
    }
    return 0;
}

static int generate_to_mapped_file(
    const char* path,
    const char* solver,
    long long data_size,
    const char* sync_mode,
    double* runtime,
    double* sync_runtime
) {
    int fd;
    void* mapped;
    long long generated;
    double begin;
    double sync_begin;

    *sync_runtime = 0.0;
    fd = open(path, O_RDWR | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) {
        return -1;
    }
    if (lseek(fd, (off_t)data_size - 1, SEEK_SET) < 0 || write(fd, "", 1) != 1) {
        close(fd);
        unlink(path);
        return -1;
    }
    mapped = mmap(NULL, (size_t)data_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (mapped == MAP_FAILED) {
        close(fd);
        unlink(path);
        return -1;
    }

    begin = now_seconds();
    generated = nissy_gendata(solver, (unsigned long long)data_size, (unsigned char*)mapped);
    *runtime = now_seconds() - begin;
    if (generated < 0 || generated != data_size) {
        munmap(mapped, (size_t)data_size);
        close(fd);
        unlink(path);
        return -1;
    }
    if (!valid_mmap_sync_mode(sync_mode)) {
        munmap(mapped, (size_t)data_size);
        close(fd);
        unlink(path);
        return -1;
    }
    sync_begin = now_seconds();
    if (!strcmp(sync_mode, "sync")) {
        if (msync(mapped, (size_t)data_size, MS_SYNC) != 0) {
            munmap(mapped, (size_t)data_size);
            close(fd);
            unlink(path);
            return -1;
        }
    } else if (!strcmp(sync_mode, "async")) {
        if (msync(mapped, (size_t)data_size, MS_ASYNC) != 0) {
            munmap(mapped, (size_t)data_size);
            close(fd);
            unlink(path);
            return -1;
        }
    }
    *sync_runtime = now_seconds() - sync_begin;
    if (munmap(mapped, (size_t)data_size) != 0) {
        close(fd);
        unlink(path);
        return -1;
    }
    if (close(fd) != 0) {
        unlink(path);
        return -1;
    }
    return 0;
}

static int load_table_file(const char* path, LoadedTable* table) {
    int fd;
    struct stat st;
    void* mapped;
    unsigned char* data = NULL;
    size_t size;
    size_t total = 0;

    *table = (LoadedTable){0};
    fd = open(path, O_RDONLY);
    if (fd < 0) {
        return -1;
    }
    if (fstat(fd, &st) != 0 || st.st_size <= 0 || (unsigned long long)st.st_size > SIZE_MAX) {
        close(fd);
        return -1;
    }
    size = (size_t)st.st_size;
    mapped = mmap(NULL, size, PROT_READ, MAP_PRIVATE, fd, 0);
    if (mapped != MAP_FAILED && ((size_t)mapped % 64) == 0) {
        close(fd);
        table->data = (unsigned char*)mapped;
        table->size = (unsigned long long)size;
        table->mapped = true;
        return 0;
    }
    if (mapped != MAP_FAILED) {
        munmap(mapped, size);
    }
    if (posix_memalign((void**)&data, 64, size) != 0) {
        close(fd);
        return -1;
    }
    while (total < size) {
        ssize_t nread = read(fd, data + total, size - total);
        if (nread <= 0) {
            free(data);
            close(fd);
            return -1;
        }
        total += (size_t)nread;
    }
    close(fd);
    table->data = data;
    table->size = (unsigned long long)size;
    table->mapped = false;
    return 0;
}

static void unload_table(LoadedTable* table) {
    if (table->data == NULL) {
        return;
    }
    if (table->mapped) {
        munmap(table->data, (size_t)table->size);
    } else {
        free(table->data);
    }
    *table = (LoadedTable){0};
}

static void preload_table_pages(const LoadedTable* table) {
    volatile unsigned char sink = 0;
    const size_t page = 4096;
    size_t size;
    size_t offset;
    if (table->data == NULL || table->size == 0) {
        return;
    }
    size = (size_t)table->size;
    for (offset = 0; offset < size; offset += page) {
        sink ^= table->data[offset];
    }
    sink ^= table->data[size - 1];
    (void)sink;
}

static int run_generate(const Options* options) {
    char data_id[NISSY_SIZE_DATAID] = {0};
    unsigned char* data = NULL;
    long long data_size;
    long long generated;
    double begin;
    double runtime;
    double mmap_sync_runtime = 0.0;

    if (options->output_path == NULL) {
        print_error_json("failed", "missing --output");
        return 2;
    }

    data_size = nissy_solverinfo(options->solver, data_id);
    if (data_size < 0) {
        print_error_json("failed", "nissy_solverinfo failed");
        return 2;
    }
    if (options->generate_mmap) {
        if (
            generate_to_mapped_file(
                options->output_path,
                options->solver,
                data_size,
                options->mmap_sync_mode,
                &runtime,
                &mmap_sync_runtime
            ) != 0
        ) {
            print_error_json("failed", "mapped table generation failed");
            return 2;
        }
    } else {
        if (posix_memalign((void**)&data, 64, (size_t)data_size) != 0) {
            print_error_json("failed", "aligned allocation failed");
            return 2;
        }

        begin = now_seconds();
        generated = nissy_gendata(options->solver, (unsigned long long)data_size, data);
        runtime = now_seconds() - begin;
        if (generated < 0 || generated != data_size) {
            free(data);
            print_error_json("failed", "nissy_gendata failed");
            return 2;
        }
        if (write_all(options->output_path, data, (size_t)data_size) != 0) {
            free(data);
            print_error_json("failed", "could not write generated table");
            return 2;
        }
        free(data);
    }

    fputs("{\"status\":\"generated\",\"solver\":", stdout);
    json_string(stdout, options->solver);
    fputs(",\"data_id\":", stdout);
    json_string(stdout, data_id);
    fputs(",\"generation_storage\":", stdout);
    json_string(stdout, options->generate_mmap ? "mmap_file" : "heap_then_write");
    fputs(",\"mmap_sync_mode\":", stdout);
    json_string(stdout, options->generate_mmap ? options->mmap_sync_mode : "not_applicable");
    fprintf(
        stdout,
        ",\"mmap_sync_runtime_seconds\":%.6f,\"table_size_bytes\":%lld,\"runtime_seconds\":%.6f}\n",
        mmap_sync_runtime,
        data_size,
        runtime
    );
    return 0;
}

static void first_solution(char* sols, char* out, size_t out_size) {
    size_t i = 0;
    while (sols[i] != '\0' && sols[i] != '\n' && i + 1 < out_size) {
        out[i] = sols[i];
        ++i;
    }
    out[i] = '\0';
}

static int solve_loaded_cube(
    const Options* options,
    unsigned long long data_size,
    const unsigned char* data,
    const char* cube_string,
    bool table_mapped
) {
    char cube[NISSY_SIZE_CUBE] = {0};
    char sols[NISSY_SIZE_MOVES] = {0};
    char solution[NISSY_SIZE_MOVES] = {0};
    long long stats[NISSY_SIZE_SOLVE_STATS] = {0};
    long long result;
    long long lower_bound = 0;
    long long move_count = 0;
    unsigned min_depth;
    double begin;
    double runtime;
    SolveDeadline deadline = {0};
    bool timed_out_by_poll = false;
    bool search_deadline_expired = false;
    bool exact_solution_found = false;
    bool completed_negative_search = false;
    long long proved_lower_bound = 0;

    strncpy(cube, cube_string, sizeof(cube) - 1);
    cube[sizeof(cube) - 1] = '\0';
    min_depth = options->min_depth;
    if (options->auto_min_depth) {
        lower_bound = nissy_lowerbound(cube, options->solver, data_size, data);
        if (lower_bound < 0) {
            print_error_json("failed", "nissy_lowerbound failed");
            return 2;
        }
        if ((unsigned)lower_bound > min_depth) {
            min_depth = (unsigned)lower_bound;
        }
    }

    if (options->search_timeout_ms > 0) {
        deadline.enabled = true;
        deadline.deadline_seconds = now_seconds() + ((double)options->search_timeout_ms / 1000.0);
        deadline.timed_out = false;
    }

    begin = now_seconds();
    result = nissy_solve(
        cube,
        options->solver,
        NISSY_NISSFLAG_NORMAL,
        min_depth,
        options->max_depth,
        1,
        0,
        options->threads,
        data_size,
        data,
        sizeof(sols),
        sols,
        stats,
        deadline.enabled ? poll_deadline_status : NULL,
        deadline.enabled ? &deadline : NULL
    );
    runtime = now_seconds() - begin;
    timed_out_by_poll = deadline.timed_out;
    search_deadline_expired = deadline.enabled && now_seconds() >= deadline.deadline_seconds;

    if (result < 0) {
        print_error_json("failed", "nissy_solve failed");
        return 2;
    }
    first_solution(sols, solution, sizeof(solution));
    exact_solution_found = result > 0 && solution[0] != '\0';
    completed_negative_search = result == 0 && !timed_out_by_poll && !search_deadline_expired;
    proved_lower_bound = completed_negative_search ? (long long)options->max_depth + 1 : lower_bound;
    if (exact_solution_found) {
        move_count = nissy_countmoves(solution);
        fputs("{\"status\":\"exact\",\"solver\":", stdout);
    } else if (completed_negative_search) {
        fputs("{\"status\":\"lower_bound\",\"solver\":", stdout);
    } else {
        fputs("{\"status\":\"timeout\",\"solver\":", stdout);
    }
    json_string(stdout, options->solver);
    fputs(",\"solution\":", stdout);
    json_string(stdout, solution);
    fputs(",\"solution_length\":", stdout);
    if (exact_solution_found) {
        fprintf(stdout, "%lld", move_count < 0 ? 0 : move_count);
    } else {
        fputs("null", stdout);
    }
    fprintf(
        stdout,
        ",\"proved_lower_bound\":%lld,\"runtime_seconds\":%.6f,"
        "\"expanded_nodes\":%lld,\"table_lookups\":%lld,\"table_fallbacks\":%lld,"
        "\"table_size_bytes\":%llu,",
        proved_lower_bound,
        runtime,
        stats[0],
        stats[1],
        stats[2],
        data_size
    );
    fputs("\"table_check\":", stdout);
    json_string(stdout, options->skip_table_check ? "skipped" : "verified");
    fputs(",\"table_storage\":", stdout);
    json_string(stdout, table_mapped ? "mmap" : "heap");
    fputs(",\"table_preload\":", stdout);
    json_string(stdout, options->preload_table ? "enabled" : "disabled");
    fputs(",\"auto_min_depth\":", stdout);
    json_string(stdout, options->auto_min_depth ? "enabled" : "disabled");
    fprintf(
        stdout,
        ",\"lower_bound\":%lld,\"min_depth\":%u,\"max_depth\":%u,"
        "\"search_timeout_ms\":%u,\"timed_out_by_poll\":%s,"
        "\"search_deadline_expired\":%s}\n",
        lower_bound,
        min_depth,
        options->max_depth,
        options->search_timeout_ms,
        timed_out_by_poll ? "true" : "false",
        search_deadline_expired ? "true" : "false"
    );
    return result > 0 ? 0 : 1;
}

static int prepare_solve_data(
    const Options* options,
    LoadedTable* table
) {
    if (options->table_path == NULL) {
        print_error_json("failed", "missing --table");
        return 2;
    }
    if (options->max_depth > 20) {
        print_error_json("failed", "--max-depth above 20 is not supported");
        return 2;
    }
    if (load_table_file(options->table_path, table) != 0) {
        print_error_json("failed", "could not read table");
        return 2;
    }
    if (!options->skip_table_check && nissy_checkdata(options->solver, table->size, table->data) != NISSY_OK) {
        unload_table(table);
        print_error_json("failed", "table check failed");
        return 2;
    }
    if (options->preload_table) {
        preload_table_pages(table);
    }
    return 0;
}

static int run_solve(const Options* options) {
    LoadedTable table = {0};
    char cube[NISSY_SIZE_CUBE] = {0};
    int rc;

    if (options->sequence == NULL && options->cube == NULL) {
        print_error_json("failed", "missing --sequence or --cube");
        return 2;
    }
    rc = prepare_solve_data(options, &table);
    if (rc != 0) {
        return rc;
    }
    if (options->sequence != NULL) {
        if (nissy_applymoves(NISSY_SOLVED_CUBE, options->sequence, cube) < 0) {
            unload_table(&table);
            print_error_json("failed", "invalid move sequence");
            return 2;
        }
    } else {
        strncpy(cube, options->cube, sizeof(cube) - 1);
        cube[sizeof(cube) - 1] = '\0';
    }
    rc = solve_loaded_cube(options, table.size, table.data, cube, table.mapped);
    unload_table(&table);
    return rc;
}

static int print_loaded_lower_bound(const Options* options, const LoadedTable* table, const char* cube) {
    long long lower_bound;
    double begin;
    double runtime;

    begin = now_seconds();
    lower_bound = nissy_lowerbound(cube, options->solver, table->size, table->data);
    runtime = now_seconds() - begin;
    if (lower_bound < 0) {
        print_error_json("failed", "nissy_lowerbound failed");
        return 2;
    }

    fputs("{\"status\":\"lower_bound\",\"solver\":", stdout);
    json_string(stdout, options->solver);
    fprintf(
        stdout,
        ",\"lower_bound\":%lld,\"runtime_seconds\":%.6f,"
        "\"table_size_bytes\":%llu,",
        lower_bound,
        runtime,
        table->size
    );
    fputs("\"table_check\":", stdout);
    json_string(stdout, options->skip_table_check ? "skipped" : "verified");
    fputs(",\"table_storage\":", stdout);
    json_string(stdout, table->mapped ? "mmap" : "heap");
    fputs(",\"table_preload\":", stdout);
    json_string(stdout, options->preload_table ? "enabled" : "disabled");
    fputs("}\n", stdout);
    return 0;
}

static int run_lower_bound(const Options* options) {
    LoadedTable table = {0};
    char cube[NISSY_SIZE_CUBE] = {0};
    int rc;

    if (options->sequence == NULL && options->cube == NULL) {
        print_error_json("failed", "missing --sequence or --cube");
        return 2;
    }
    rc = prepare_solve_data(options, &table);
    if (rc != 0) {
        return rc;
    }
    if (options->sequence != NULL) {
        if (nissy_applymoves(NISSY_SOLVED_CUBE, options->sequence, cube) < 0) {
            unload_table(&table);
            print_error_json("failed", "invalid move sequence");
            return 2;
        }
    } else {
        strncpy(cube, options->cube, sizeof(cube) - 1);
        cube[sizeof(cube) - 1] = '\0';
    }

    rc = print_loaded_lower_bound(options, &table, cube);
    unload_table(&table);
    return rc;
}

static int run_lower_bound_batch(const Options* options) {
    LoadedTable table = {0};
    char line[512] = {0};
    int rc;
    int final_rc = 0;

    rc = prepare_solve_data(options, &table);
    if (rc != 0) {
        return rc;
    }
    while (fgets(line, sizeof(line), stdin) != NULL) {
        size_t len = strlen(line);
        while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r')) {
            line[--len] = '\0';
        }
        if (len == 0) {
            continue;
        }
        rc = print_loaded_lower_bound(options, &table, line);
        fflush(stdout);
        if (rc != 0 && final_rc == 0) {
            final_rc = rc;
        }
    }
    unload_table(&table);
    return final_rc;
}

static int run_solve_batch(const Options* options) {
    LoadedTable table = {0};
    char line[512] = {0};
    int rc;
    int final_rc = 0;

    rc = prepare_solve_data(options, &table);
    if (rc != 0) {
        return rc;
    }
    while (fgets(line, sizeof(line), stdin) != NULL) {
        size_t len = strlen(line);
        while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r')) {
            line[--len] = '\0';
        }
        if (len == 0) {
            continue;
        }
        rc = solve_loaded_cube(options, table.size, table.data, line, table.mapped);
        fflush(stdout);
        if (rc != 0 && final_rc == 0) {
            final_rc = rc;
        }
    }
    unload_table(&table);
    return final_rc;
}

int main(int argc, char** argv) {
    Options options;
    if (!parse_args(argc, argv, &options)) {
        print_error_json("failed", "invalid arguments");
        return 2;
    }
    if (options.progress_log) {
        nissy_setlogger(stderr_logger, NULL);
    }
    if (!strcmp(options.mode, "generate")) {
        return run_generate(&options);
    }
    if (!strcmp(options.mode, "solve")) {
        return run_solve(&options);
    }
    if (!strcmp(options.mode, "lower-bound")) {
        return run_lower_bound(&options);
    }
    if (!strcmp(options.mode, "lower-bound-batch")) {
        return run_lower_bound_batch(&options);
    }
    if (!strcmp(options.mode, "solve-batch")) {
        return run_solve_batch(&options);
    }
    print_error_json("failed", "unknown mode");
    return 2;
}
