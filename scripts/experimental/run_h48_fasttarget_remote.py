#!/usr/bin/env python
"""Run or dry-run the H48 fast-target proof on a remote SSH machine."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.runtime import run_process_tree  # noqa: E402


DEFAULT_RSYNC_EXCLUDES = (
    ".git/",
    "__pycache__/",
    ".pytest_cache/",
    "tmp/",
    "results/cloud_hardtail_artifacts_*.tar.gz",
    "results/cloud_hardtail_prerequisite_tables_*.tar.gz",
    "results/cloud_hardtail_prerequisite_tables_*_parts/",
)

PREREQUISITE_BUNDLE_MODE_CHOICES = ("archive", "split", "both")

REMOTE_ACTION_CHOICES = (
    "end-to-end",
    "preflight",
    "canary",
    "canary-after-prerequisites",
    "start-prerequisites",
    "prerequisites",
    "full",
    "start-full",
    "wait-full",
    "status",
    "wait-prerequisites",
    "recover-prerequisite-metadata",
    "resume",
    "staged-proof",
    "detached-staged-proof",
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _ssh_prefix(
    *,
    host: str,
    port: int | None,
    identity_file: Path | None,
    ssh_options: list[str],
) -> list[str]:
    command = ["ssh"]
    if port is not None:
        command.extend(["-p", str(port)])
    if identity_file is not None:
        command.extend(["-i", str(identity_file)])
    for option in ssh_options:
        command.extend(["-o", option])
    command.append(host)
    return command


def _rsync_prefix(
    *,
    port: int | None,
    identity_file: Path | None,
    ssh_options: list[str],
    delete: bool,
    excludes: list[str],
) -> list[str]:
    ssh_transport = ["ssh"]
    if port is not None:
        ssh_transport.extend(["-p", str(port)])
    if identity_file is not None:
        ssh_transport.extend(["-i", str(identity_file)])
    for option in ssh_options:
        ssh_transport.extend(["-o", option])
    command = ["rsync", "-az", "--info=progress2", "-e", shlex.join(ssh_transport)]
    if delete:
        command.append("--delete")
    for pattern in excludes:
        command.extend(["--exclude", pattern])
    return command


def _remote_shell(
    *,
    host: str,
    port: int | None,
    identity_file: Path | None,
    ssh_options: list[str],
    command: str,
) -> list[str]:
    return [
        *_ssh_prefix(
            host=host,
            port=port,
            identity_file=identity_file,
            ssh_options=ssh_options,
        ),
        "bash",
        "-lc",
        command,
    ]


def _remote_detached_scripts_command(
    *,
    remote_root: str,
    run_suffix: str,
    launch_id: str,
    scripts: list[str],
) -> str:
    safe_suffix = _safe_id(run_suffix)
    safe_launch = _safe_id(launch_id)
    log_relative = f"results/logs/h48_fasttarget_{safe_suffix}_{safe_launch}.log"
    pid_relative = f"results/processed/h48_fasttarget_{safe_suffix}_{safe_launch}.pid"
    launch_relative = f"results/processed/h48_fasttarget_{safe_suffix}_{safe_launch}_launch.json"
    script_chain = " && ".join(f"bash {shlex.quote(script)}" for script in scripts)
    return (
        f"cd {shlex.quote(remote_root)} && mkdir -p results/logs results/processed && "
        f"nohup bash -lc {shlex.quote(script_chain)} > {shlex.quote(log_relative)} 2>&1 "
        f"< /dev/null & pid=$!; "
        f"printf '%s\\n' \"$pid\" > {shlex.quote(pid_relative)}; "
        f"REMOTE_PID=\"$pid\" "
        f"REMOTE_LOG={shlex.quote(log_relative)} "
        f"REMOTE_PID_FILE={shlex.quote(pid_relative)} "
        f"REMOTE_LAUNCH_FILE={shlex.quote(launch_relative)} "
        f"REMOTE_SCRIPT_CHAIN={shlex.quote(script_chain)} "
        "python - <<'PY'\n"
        "import json\n"
        "import os\n"
        "import time\n"
        "payload = {\n"
        "    'schema_version': 1,\n"
        f"    'run_suffix': {run_suffix!r},\n"
        f"    'launch_id': {launch_id!r},\n"
        "    'pid': int(os.environ['REMOTE_PID']),\n"
        "    'pid_file': os.environ['REMOTE_PID_FILE'],\n"
        "    'log_file': os.environ['REMOTE_LOG'],\n"
        "    'script_chain': os.environ['REMOTE_SCRIPT_CHAIN'],\n"
        "    'launched_at_unix': time.time(),\n"
        "}\n"
        "with open(os.environ['REMOTE_LAUNCH_FILE'], 'w', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps(payload, sort_keys=True) + '\\n')\n"
        "print(json.dumps(payload, sort_keys=True))\n"
        "PY"
    )


def _remote_status_command(
    *,
    remote_root: str,
    run_suffix: str,
    solver: str | None,
    profile: str | None,
    seed: int | None,
    results_archive: str,
    prerequisite_tables_archive: str,
    prerequisite_tables_parts_dir: str,
    prerequisite_bundle_mode: str,
    expected_table_size_bytes: int | None,
) -> str:
    config = json.dumps(
        {
            "run_suffix": run_suffix,
            "solver": solver,
            "profile": profile,
            "seed": seed,
            "results_archive": results_archive,
            "prerequisite_tables_archive": prerequisite_tables_archive,
            "prerequisite_tables_parts_dir": prerequisite_tables_parts_dir,
            "prerequisite_bundle_mode": prerequisite_bundle_mode,
            "expected_table_size_bytes": expected_table_size_bytes,
        },
        sort_keys=True,
    )
    return (
        f"cd {shlex.quote(remote_root)} && python - <<'PY'\n"
        "import glob\n"
        "import json\n"
        "import os\n"
        "import shutil\n"
        "import time\n"
        "from pathlib import Path\n"
        "from rubik_optimal.tables.h48 import validate_trusted_h48_table_checksum\n"
        f"config = json.loads({config!r})\n"
        "root = Path('.')\n"
        "solver = config.get('solver')\n"
        "profile = config.get('profile')\n"
        "seed = config.get('seed')\n"
        "\n"
        "def safe_id(value):\n"
        "    return ''.join(char if char.isalnum() or char in '._-' else '_' for char in str(value))\n"
        "\n"
        "def resolve_path(relative):\n"
        "    path = Path(str(relative))\n"
        "    return path if path.is_absolute() else root / path\n"
        "\n"
        "def file_info(relative):\n"
        "    path = resolve_path(relative)\n"
        "    exists = path.exists()\n"
        "    info = {'path': str(relative), 'exists': exists}\n"
        "    if exists:\n"
        "        stat = path.stat()\n"
        "        info.update({'size_bytes': stat.st_size, 'mtime': stat.st_mtime})\n"
        "    return info\n"
        "\n"
        "def directory_info(relative):\n"
        "    path = resolve_path(relative)\n"
        "    exists = path.is_dir()\n"
        "    info = {'path': str(relative), 'exists': exists, 'is_dir': exists}\n"
        "    if exists:\n"
        "        stat = path.stat()\n"
        "        manifest = path / 'h48_table_bundle_manifest.json'\n"
        "        info.update({'size_bytes': stat.st_size, 'mtime': stat.st_mtime, 'manifest_exists': manifest.is_file(), 'part_file_count': len(list(path.glob('*.part*'))), 'manifest': file_info(str(manifest))})\n"
        "    return info\n"
        "\n"
        "def read_text_file(relative):\n"
        "    return resolve_path(relative).read_text(encoding='utf-8').strip()\n"
        "\n"
        "def read_json_file(relative):\n"
        "    path = resolve_path(relative)\n"
        "    if not path.exists():\n"
        "        return None\n"
        "    try:\n"
        "        parsed = json.loads(path.read_text(encoding='utf-8'))\n"
        "    except Exception as exc:\n"
        "        return {'load_error': str(exc)}\n"
        "    return parsed if isinstance(parsed, dict) else {'load_error': 'not a JSON object'}\n"
        "\n"
        "def file_tail_info(relative, max_bytes=8192, max_lines=40):\n"
        "    info = file_info(relative)\n"
        "    if not info.get('exists'):\n"
        "        return info\n"
        "    path = resolve_path(relative)\n"
        "    try:\n"
        "        with path.open('rb') as handle:\n"
        "            size = info.get('size_bytes') or 0\n"
        "            handle.seek(max(0, int(size) - max_bytes))\n"
        "            data = handle.read(max_bytes)\n"
        "        info['tail'] = data.decode('utf-8', errors='replace').splitlines()[-max_lines:]\n"
        "        info['tail_max_bytes'] = max_bytes\n"
        "        info['tail_max_lines'] = max_lines\n"
        "    except Exception as exc:\n"
        "        info['tail_error'] = str(exc)\n"
        "    return info\n"
        "\n"
        "def detached_launch_status(launch_id):\n"
        "    safe_suffix = safe_id(config.get('run_suffix') or 'unknown')\n"
        "    launch_relative = f'results/processed/h48_fasttarget_{safe_suffix}_{launch_id}_launch.json'\n"
        "    default_pid_relative = f'results/processed/h48_fasttarget_{safe_suffix}_{launch_id}.pid'\n"
        "    default_log_relative = f'results/logs/h48_fasttarget_{safe_suffix}_{launch_id}.log'\n"
        "    launch_payload = read_json_file(launch_relative)\n"
        "    if not isinstance(launch_payload, dict) or launch_payload.get('load_error'):\n"
        "        launch_payload = None\n"
        "    pid_relative = default_pid_relative\n"
        "    log_relative = default_log_relative\n"
        "    if isinstance(launch_payload, dict):\n"
        "        pid_relative = launch_payload.get('pid_file') or pid_relative\n"
        "        log_relative = launch_payload.get('log_file') or log_relative\n"
        "    pid = None\n"
        "    pid_source = None\n"
        "    pid_parse_error = None\n"
        "    pid_info = file_info(pid_relative)\n"
        "    if pid_info.get('exists'):\n"
        "        try:\n"
        "            pid = int(read_text_file(pid_relative).splitlines()[0].strip())\n"
        "            pid_source = 'pid_file'\n"
        "        except Exception as exc:\n"
        "            pid_parse_error = str(exc)\n"
        "    if pid is None and isinstance(launch_payload, dict) and launch_payload.get('pid') is not None:\n"
        "        try:\n"
        "            pid = int(launch_payload['pid'])\n"
        "            pid_source = 'launch_json'\n"
        "        except Exception as exc:\n"
        "            pid_parse_error = str(exc)\n"
        "    process_alive = None\n"
        "    process_check_error = None\n"
        "    if pid is not None:\n"
        "        try:\n"
        "            os.kill(pid, 0)\n"
        "            process_alive = True\n"
        "        except ProcessLookupError:\n"
        "            process_alive = False\n"
        "        except PermissionError:\n"
        "            process_alive = True\n"
        "            process_check_error = 'permission denied, but process exists'\n"
        "        except Exception as exc:\n"
        "            process_check_error = str(exc)\n"
        "    return {\n"
        "        'launch_id': launch_id,\n"
        "        'launch_file': file_info(launch_relative),\n"
        "        'launch_payload': launch_payload,\n"
        "        'pid_file': pid_info,\n"
        "        'pid': pid,\n"
        "        'pid_source': pid_source,\n"
        "        'pid_parse_error': pid_parse_error,\n"
        "        'process_alive': process_alive,\n"
        "        'process_check_error': process_check_error,\n"
        "        'log_file': file_tail_info(log_relative),\n"
        "    }\n"
        "\n"
        "def detached_prerequisite_status():\n"
        "    status = detached_launch_status('start_prerequisites')\n"
        "    archive = file_info(config['prerequisite_tables_archive'])\n"
        "    parts_dir = directory_info(config['prerequisite_tables_parts_dir'])\n"
        "    status['prerequisite_tables_archive'] = archive\n"
        "    status['prerequisite_tables_archive_present'] = archive.get('exists') is True\n"
        "    status['prerequisite_tables_parts_dir'] = parts_dir\n"
        "    status['prerequisite_tables_parts_present'] = parts_dir.get('manifest_exists') is True and int(parts_dir.get('part_file_count') or 0) > 0\n"
        "    return status\n"
        "\n"
        "def detached_full_proof_status():\n"
        "    status = detached_launch_status('start_full')\n"
        "    archive = file_info(config['results_archive'])\n"
        "    status['results_archive'] = archive\n"
        "    status['results_archive_present'] = bool(archive.get('exists') and int(archive.get('size_bytes') or 0) > 0)\n"
        "    return status\n"
        "\n"
        "def json_field(relative, key):\n"
        "    path = resolve_path(relative)\n"
        "    if not path.exists():\n"
        "        return None\n"
        "    try:\n"
        "        return json.loads(path.read_text(encoding='utf-8')).get(key)\n"
        "    except Exception:\n"
        "        return None\n"
        "\n"
        "def checksum_status():\n"
        "    if not (solver and profile and seed is not None and table_relative and metadata_relative):\n"
        "        return {'valid': None, 'message': 'missing solver/profile/seed', 'details': {}}\n"
        "    table = root / table_relative\n"
        "    metadata = root / metadata_relative\n"
        "    expected = config.get('expected_table_size_bytes')\n"
        "    if not table.exists() or not metadata.exists():\n"
        "        return {'valid': False, 'message': 'missing target table or metadata', 'details': {}}\n"
        "    if expected and table.stat().st_size != expected:\n"
        "        return {'valid': False, 'message': 'target table size does not match expected size', 'details': {'table_size_bytes': table.stat().st_size, 'expected_table_size_bytes': expected}}\n"
        "    begin = time.perf_counter()\n"
        "    try:\n"
        "        passed, message, details = validate_trusted_h48_table_checksum(root=root, profile=profile, seed=int(seed), solver=solver, use_cache=False, persistent_cache=True)\n"
        "    except Exception as exc:\n"
        "        return {'valid': False, 'message': f'checksum validation raised: {exc}', 'runtime_seconds': round(time.perf_counter() - begin, 6), 'details': {}}\n"
        "    return {'valid': bool(passed), 'message': message, 'runtime_seconds': round(time.perf_counter() - begin, 6), 'details': details}\n"
        "\n"
        "table_relative = None\n"
        "metadata_relative = None\n"
        "contract_relative = None\n"
        "h48_table_root = os.environ.get('RUBIK_OPTIMAL_H48_TABLE_ROOT', 'data/generated/h48')\n"
        "if solver and profile and seed is not None:\n"
        "    table_relative = str(Path(h48_table_root) / f'{profile}_seed_{seed}' / f'{solver}.bin')\n"
        "    metadata_relative = f'results/processed/h48_metadata_seed_{seed}_{profile}_{solver}.json'\n"
        "    contract_relative = f'results/processed/h48_oracle_contract_seed_{seed}_{profile}_{solver}.json'\n"
        "disk = shutil.disk_usage('.')\n"
        "payload = {\n"
        "    'schema_version': 1,\n"
        "    'run_suffix': config.get('run_suffix'),\n"
        "    'solver': solver,\n"
        "    'profile': profile,\n"
        "    'seed': seed,\n"
        "    'h48_table_root': h48_table_root,\n"
        "    'cpu_count': os.cpu_count(),\n"
        "    'load_average': list(os.getloadavg()) if hasattr(os, 'getloadavg') else None,\n"
        "    'disk_free_bytes': disk.free,\n"
        "    'disk_total_bytes': disk.total,\n"
        "    'expected_table_size_bytes': config.get('expected_table_size_bytes'),\n"
        "    'table': file_info(table_relative) if table_relative else None,\n"
        "    'metadata': file_info(metadata_relative) if metadata_relative else None,\n"
        "    'metadata_trusted_table': json_field(metadata_relative, 'trusted_table') if metadata_relative else None,\n"
        "    'contract': file_info(contract_relative) if contract_relative else None,\n"
        "    'contract_fast_runtime_proven_for_every_possible_state': json_field(contract_relative, 'fast_runtime_proven_for_every_possible_state') if contract_relative else None,\n"
        "    'results_archive': file_info(config['results_archive']),\n"
        "    'prerequisite_tables_archive': file_info(config['prerequisite_tables_archive']),\n"
        "    'prerequisite_tables_parts_dir': directory_info(config['prerequisite_tables_parts_dir']),\n"
        "    'prerequisite_bundle_mode': config.get('prerequisite_bundle_mode'),\n"
        "    'detached_prerequisite': detached_prerequisite_status(),\n"
        "    'detached_full_proof': detached_full_proof_status(),\n"
        "    'processed_cloud_artifact_count': len(glob.glob('results/processed/cloud_hardtail*.json')),\n"
        "    'processed_workload_artifact_count': len(glob.glob('results/processed/cloud_hardtail_workload_*.json')),\n"
        "    'processed_evaluation_artifact_count': len(glob.glob('results/processed/cloud_hardtail_campaign_evaluation_*.json')),\n"
        "}\n"
        "table = payload.get('table') or {}\n"
        "expected = payload.get('expected_table_size_bytes')\n"
        "payload['target_table_size_matches_expected'] = bool(table.get('exists') and expected and table.get('size_bytes') == expected)\n"
        "checksum = checksum_status()\n"
        "payload['target_table_full_checksum_valid'] = checksum.get('valid')\n"
        "payload['target_table_full_checksum_message'] = checksum.get('message')\n"
        "payload['target_table_full_checksum_runtime_seconds'] = checksum.get('runtime_seconds')\n"
        "payload['target_table_full_checksum_details'] = checksum.get('details')\n"
        "payload['target_table_ready_for_resume'] = bool(payload['target_table_size_matches_expected'] and payload.get('metadata_trusted_table') is True and payload['target_table_full_checksum_valid'] is True)\n"
        "print(json.dumps(payload, sort_keys=True))\n"
        "PY"
    )


def _remote_wait_prerequisites_command(
    *,
    remote_root: str,
    run_suffix: str,
    solver: str | None,
    profile: str | None,
    seed: int | None,
    prerequisite_tables_archive: str,
    prerequisite_tables_parts_dir: str,
    prerequisite_bundle_mode: str,
    expected_table_size_bytes: int | None,
    prerequisite_wait_timeout_seconds: float,
    prerequisite_poll_interval_seconds: float,
) -> str:
    config = json.dumps(
        {
            "run_suffix": run_suffix,
            "solver": solver,
            "profile": profile,
            "seed": seed,
            "prerequisite_tables_archive": prerequisite_tables_archive,
            "prerequisite_tables_parts_dir": prerequisite_tables_parts_dir,
            "prerequisite_bundle_mode": prerequisite_bundle_mode,
            "expected_table_size_bytes": expected_table_size_bytes,
            "prerequisite_wait_timeout_seconds": prerequisite_wait_timeout_seconds,
            "prerequisite_poll_interval_seconds": prerequisite_poll_interval_seconds,
        },
        sort_keys=True,
    )
    return (
        f"cd {shlex.quote(remote_root)} && python - <<'PY'\n"
        "import json\n"
        "import os\n"
        "import time\n"
        "from pathlib import Path\n"
        "from rubik_optimal.tables.h48 import validate_trusted_h48_table_checksum\n"
        f"config = json.loads({config!r})\n"
        "root = Path('.')\n"
        "solver = config.get('solver')\n"
        "profile = config.get('profile')\n"
        "seed = config.get('seed')\n"
        "wait_timeout = float(config.get('prerequisite_wait_timeout_seconds') or 0.0)\n"
        "poll_interval = max(1.0, float(config.get('prerequisite_poll_interval_seconds') or 30.0))\n"
        "\n"
        "def safe_id(value):\n"
        "    return ''.join(char if char.isalnum() or char in '._-' else '_' for char in str(value))\n"
        "\n"
        "def resolve_path(relative):\n"
        "    path = Path(str(relative))\n"
        "    return path if path.is_absolute() else root / path\n"
        "\n"
        "def file_info(relative):\n"
        "    path = resolve_path(relative)\n"
        "    exists = path.exists()\n"
        "    info = {'path': str(relative), 'exists': exists}\n"
        "    if exists:\n"
        "        stat = path.stat()\n"
        "        info.update({'size_bytes': stat.st_size, 'mtime': stat.st_mtime})\n"
        "    return info\n"
        "\n"
        "def directory_info(relative):\n"
        "    path = resolve_path(relative)\n"
        "    exists = path.is_dir()\n"
        "    info = {'path': str(relative), 'exists': exists, 'is_dir': exists}\n"
        "    if exists:\n"
        "        stat = path.stat()\n"
        "        manifest = path / 'h48_table_bundle_manifest.json'\n"
        "        info.update({'size_bytes': stat.st_size, 'mtime': stat.st_mtime, 'manifest_exists': manifest.is_file(), 'part_file_count': len(list(path.glob('*.part*'))), 'manifest': file_info(str(manifest))})\n"
        "    return info\n"
        "\n"
        "def read_text_file(relative):\n"
        "    return resolve_path(relative).read_text(encoding='utf-8').strip()\n"
        "\n"
        "def read_json_file(relative):\n"
        "    path = resolve_path(relative)\n"
        "    if not path.exists():\n"
        "        return None\n"
        "    try:\n"
        "        parsed = json.loads(path.read_text(encoding='utf-8'))\n"
        "    except Exception as exc:\n"
        "        return {'load_error': str(exc)}\n"
        "    return parsed if isinstance(parsed, dict) else {'load_error': 'not a JSON object'}\n"
        "\n"
        "def file_tail_info(relative, max_bytes=8192, max_lines=40):\n"
        "    info = file_info(relative)\n"
        "    if not info.get('exists'):\n"
        "        return info\n"
        "    path = resolve_path(relative)\n"
        "    try:\n"
        "        with path.open('rb') as handle:\n"
        "            size = info.get('size_bytes') or 0\n"
        "            handle.seek(max(0, int(size) - max_bytes))\n"
        "            data = handle.read(max_bytes)\n"
        "        info['tail'] = data.decode('utf-8', errors='replace').splitlines()[-max_lines:]\n"
        "        info['tail_max_bytes'] = max_bytes\n"
        "        info['tail_max_lines'] = max_lines\n"
        "    except Exception as exc:\n"
        "        info['tail_error'] = str(exc)\n"
        "    return info\n"
        "\n"
        "def process_alive_for_pid(pid):\n"
        "    if pid is None:\n"
        "        return None, None\n"
        "    try:\n"
        "        os.kill(pid, 0)\n"
        "        return True, None\n"
        "    except ProcessLookupError:\n"
        "        return False, None\n"
        "    except PermissionError:\n"
        "        return True, 'permission denied, but process exists'\n"
        "    except Exception as exc:\n"
        "        return None, str(exc)\n"
        "\n"
        "def json_field(relative, key):\n"
        "    if relative is None:\n"
        "        return None\n"
        "    path = resolve_path(relative)\n"
        "    if not path.exists():\n"
        "        return None\n"
        "    try:\n"
        "        return json.loads(path.read_text(encoding='utf-8')).get(key)\n"
        "    except Exception:\n"
        "        return None\n"
        "\n"
        "def checksum_status(table_relative, metadata_relative):\n"
        "    if not (solver and profile and seed is not None and table_relative and metadata_relative):\n"
        "        return {'valid': None, 'message': 'missing solver/profile/seed', 'details': {}}\n"
        "    table_path = resolve_path(table_relative)\n"
        "    metadata_path = resolve_path(metadata_relative)\n"
        "    expected = config.get('expected_table_size_bytes')\n"
        "    if not table_path.exists() or not metadata_path.exists():\n"
        "        return {'valid': False, 'message': 'missing target table or metadata', 'details': {}}\n"
        "    if expected and table_path.stat().st_size != expected:\n"
        "        return {'valid': False, 'message': 'target table size does not match expected size', 'details': {'table_size_bytes': table_path.stat().st_size, 'expected_table_size_bytes': expected}}\n"
        "    begin = time.perf_counter()\n"
        "    try:\n"
        "        passed, message, details = validate_trusted_h48_table_checksum(root=root, profile=profile, seed=int(seed), solver=solver, use_cache=False, persistent_cache=True)\n"
        "    except Exception as exc:\n"
        "        return {'valid': False, 'message': f'checksum validation raised: {exc}', 'runtime_seconds': round(time.perf_counter() - begin, 6), 'details': {}}\n"
        "    return {'valid': bool(passed), 'message': message, 'runtime_seconds': round(time.perf_counter() - begin, 6), 'details': details}\n"
        "\n"
        "def snapshot():\n"
        "    safe_suffix = safe_id(config.get('run_suffix') or 'unknown')\n"
        "    launch_id = 'start_prerequisites'\n"
        "    launch_relative = f'results/processed/h48_fasttarget_{safe_suffix}_{launch_id}_launch.json'\n"
        "    pid_relative = f'results/processed/h48_fasttarget_{safe_suffix}_{launch_id}.pid'\n"
        "    log_relative = f'results/logs/h48_fasttarget_{safe_suffix}_{launch_id}.log'\n"
        "    launch_payload = read_json_file(launch_relative)\n"
        "    if not isinstance(launch_payload, dict) or launch_payload.get('load_error'):\n"
        "        launch_payload = None\n"
        "    if isinstance(launch_payload, dict):\n"
        "        pid_relative = launch_payload.get('pid_file') or pid_relative\n"
        "        log_relative = launch_payload.get('log_file') or log_relative\n"
        "    pid = None\n"
        "    pid_source = None\n"
        "    pid_parse_error = None\n"
        "    if file_info(pid_relative).get('exists'):\n"
        "        try:\n"
        "            pid = int(read_text_file(pid_relative).splitlines()[0].strip())\n"
        "            pid_source = 'pid_file'\n"
        "        except Exception as exc:\n"
        "            pid_parse_error = str(exc)\n"
        "    if pid is None and isinstance(launch_payload, dict) and launch_payload.get('pid') is not None:\n"
        "        try:\n"
        "            pid = int(launch_payload['pid'])\n"
        "            pid_source = 'launch_json'\n"
        "        except Exception as exc:\n"
        "            pid_parse_error = str(exc)\n"
        "    process_alive, process_check_error = process_alive_for_pid(pid)\n"
        "    table_relative = None\n"
        "    metadata_relative = None\n"
        "    h48_table_root = os.environ.get('RUBIK_OPTIMAL_H48_TABLE_ROOT', 'data/generated/h48')\n"
        "    if solver and profile and seed is not None:\n"
        "        table_relative = str(Path(h48_table_root) / f'{profile}_seed_{seed}' / f'{solver}.bin')\n"
        "        metadata_relative = f'results/processed/h48_metadata_seed_{seed}_{profile}_{solver}.json'\n"
        "    table = file_info(table_relative) if table_relative else None\n"
        "    metadata = file_info(metadata_relative) if metadata_relative else None\n"
        "    archive = file_info(config['prerequisite_tables_archive'])\n"
        "    parts_dir = directory_info(config['prerequisite_tables_parts_dir'])\n"
        "    expected = config.get('expected_table_size_bytes')\n"
        "    table_size_matches_expected = bool(table and table.get('exists') and expected and table.get('size_bytes') == expected)\n"
        "    archive_present = bool(archive.get('exists') and int(archive.get('size_bytes') or 0) > 0)\n"
        "    parts_present = bool(parts_dir.get('manifest_exists') and int(parts_dir.get('part_file_count') or 0) > 0)\n"
        "    bundle_mode = config.get('prerequisite_bundle_mode') or 'archive'\n"
        "    if bundle_mode == 'split':\n"
        "        prerequisite_transfer_ready = parts_present\n"
        "    elif bundle_mode == 'both':\n"
        "        prerequisite_transfer_ready = archive_present and parts_present\n"
        "    else:\n"
        "        prerequisite_transfer_ready = archive_present\n"
        "    metadata_present = bool(metadata and metadata.get('exists'))\n"
        "    metadata_trusted_table = json_field(metadata_relative, 'trusted_table') if metadata_relative else None\n"
        "    checksum = checksum_status(table_relative, metadata_relative)\n"
        "    target_table_full_checksum_valid = checksum.get('valid')\n"
        "    ready_for_resume = bool(prerequisite_transfer_ready and table_size_matches_expected and metadata_trusted_table is True and target_table_full_checksum_valid is True)\n"
        "    if ready_for_resume:\n"
        "        status = 'ready'\n"
        "    elif process_alive is True:\n"
        "        status = 'running'\n"
        "    elif launch_payload is None and pid is None:\n"
        "        status = 'not_started'\n"
        "    elif process_alive is False:\n"
        "        status = 'stopped_without_ready_artifacts'\n"
        "    else:\n"
        "        status = 'unknown'\n"
        "    return {\n"
        "        'schema_version': 1,\n"
        "        'run_suffix': config.get('run_suffix'),\n"
        "        'status': status,\n"
        "        'h48_table_root': h48_table_root,\n"
        "        'ready_for_resume': ready_for_resume,\n"
        "        'archive_present': archive_present,\n"
        "        'parts_present': parts_present,\n"
        "        'prerequisite_transfer_ready': prerequisite_transfer_ready,\n"
        "        'prerequisite_bundle_mode': bundle_mode,\n"
        "        'table_size_matches_expected': table_size_matches_expected,\n"
        "        'metadata_present': metadata_present,\n"
        "        'metadata_trusted_table': metadata_trusted_table,\n"
        "        'target_table_full_checksum_valid': target_table_full_checksum_valid,\n"
        "        'target_table_full_checksum_message': checksum.get('message'),\n"
        "        'target_table_full_checksum_runtime_seconds': checksum.get('runtime_seconds'),\n"
        "        'target_table_full_checksum_details': checksum.get('details'),\n"
        "        'expected_table_size_bytes': expected,\n"
        "        'launch_id': launch_id,\n"
        "        'launch_file': file_info(launch_relative),\n"
        "        'launch_payload': launch_payload,\n"
        "        'pid_file': file_info(pid_relative),\n"
        "        'pid': pid,\n"
        "        'pid_source': pid_source,\n"
        "        'pid_parse_error': pid_parse_error,\n"
        "        'process_alive': process_alive,\n"
        "        'process_check_error': process_check_error,\n"
        "        'log_file': file_tail_info(log_relative),\n"
        "        'table': table,\n"
        "        'metadata': metadata,\n"
        "        'prerequisite_tables_archive': archive,\n"
        "        'prerequisite_tables_parts_dir': parts_dir,\n"
        "    }\n"
        "\n"
        "begin = time.time()\n"
        "attempts = 0\n"
        "last = None\n"
        "while True:\n"
        "    attempts += 1\n"
        "    last = snapshot()\n"
        "    last['attempts'] = attempts\n"
        "    last['elapsed_seconds'] = round(time.time() - begin, 6)\n"
        "    last['prerequisite_wait_timeout_seconds'] = wait_timeout\n"
        "    last['prerequisite_poll_interval_seconds'] = poll_interval\n"
        "    if last.get('ready_for_resume') is True:\n"
        "        print(json.dumps(last, sort_keys=True))\n"
        "        raise SystemExit(0)\n"
        "    if last.get('status') in {'not_started', 'stopped_without_ready_artifacts'}:\n"
        "        print(json.dumps(last, sort_keys=True))\n"
        "        raise SystemExit(2)\n"
        "    if wait_timeout <= 0 or time.time() - begin >= wait_timeout:\n"
        "        last['status'] = 'wait_timeout'\n"
        "        print(json.dumps(last, sort_keys=True))\n"
        "        raise SystemExit(3)\n"
        "    time.sleep(min(poll_interval, max(0.0, wait_timeout - (time.time() - begin))))\n"
        "PY"
    )


def _remote_wait_full_command(
    *,
    remote_root: str,
    run_suffix: str,
    results_archive: str,
    full_wait_timeout_seconds: float,
    full_poll_interval_seconds: float,
) -> str:
    config = json.dumps(
        {
            "run_suffix": run_suffix,
            "results_archive": results_archive,
            "full_wait_timeout_seconds": full_wait_timeout_seconds,
            "full_poll_interval_seconds": full_poll_interval_seconds,
        },
        sort_keys=True,
    )
    return (
        f"cd {shlex.quote(remote_root)} && python - <<'PY'\n"
        "import json\n"
        "import os\n"
        "import time\n"
        "from pathlib import Path\n"
        f"config = json.loads({config!r})\n"
        "root = Path('.')\n"
        "wait_timeout = float(config.get('full_wait_timeout_seconds') or 0.0)\n"
        "poll_interval = max(1.0, float(config.get('full_poll_interval_seconds') or 30.0))\n"
        "\n"
        "def safe_id(value):\n"
        "    return ''.join(char if char.isalnum() or char in '._-' else '_' for char in str(value))\n"
        "\n"
        "def resolve_path(relative):\n"
        "    path = Path(str(relative))\n"
        "    return path if path.is_absolute() else root / path\n"
        "\n"
        "def file_info(relative):\n"
        "    path = resolve_path(relative)\n"
        "    exists = path.exists()\n"
        "    info = {'path': str(relative), 'exists': exists}\n"
        "    if exists:\n"
        "        stat = path.stat()\n"
        "        info.update({'size_bytes': stat.st_size, 'mtime': stat.st_mtime})\n"
        "    return info\n"
        "\n"
        "def read_text_file(relative):\n"
        "    return resolve_path(relative).read_text(encoding='utf-8').strip()\n"
        "\n"
        "def read_json_file(relative):\n"
        "    path = resolve_path(relative)\n"
        "    if not path.exists():\n"
        "        return None\n"
        "    try:\n"
        "        parsed = json.loads(path.read_text(encoding='utf-8'))\n"
        "    except Exception as exc:\n"
        "        return {'load_error': str(exc)}\n"
        "    return parsed if isinstance(parsed, dict) else {'load_error': 'not a JSON object'}\n"
        "\n"
        "def file_tail_info(relative, max_bytes=8192, max_lines=40):\n"
        "    info = file_info(relative)\n"
        "    if not info.get('exists'):\n"
        "        return info\n"
        "    path = resolve_path(relative)\n"
        "    try:\n"
        "        with path.open('rb') as handle:\n"
        "            size = info.get('size_bytes') or 0\n"
        "            handle.seek(max(0, int(size) - max_bytes))\n"
        "            data = handle.read(max_bytes)\n"
        "        info['tail'] = data.decode('utf-8', errors='replace').splitlines()[-max_lines:]\n"
        "        info['tail_max_bytes'] = max_bytes\n"
        "        info['tail_max_lines'] = max_lines\n"
        "    except Exception as exc:\n"
        "        info['tail_error'] = str(exc)\n"
        "    return info\n"
        "\n"
        "def process_alive_for_pid(pid):\n"
        "    if pid is None:\n"
        "        return None, None\n"
        "    try:\n"
        "        os.kill(pid, 0)\n"
        "        return True, None\n"
        "    except ProcessLookupError:\n"
        "        return False, None\n"
        "    except PermissionError:\n"
        "        return True, 'permission denied, but process exists'\n"
        "    except Exception as exc:\n"
        "        return None, str(exc)\n"
        "\n"
        "def snapshot():\n"
        "    safe_suffix = safe_id(config.get('run_suffix') or 'unknown')\n"
        "    launch_id = 'start_full'\n"
        "    launch_relative = f'results/processed/h48_fasttarget_{safe_suffix}_{launch_id}_launch.json'\n"
        "    pid_relative = f'results/processed/h48_fasttarget_{safe_suffix}_{launch_id}.pid'\n"
        "    log_relative = f'results/logs/h48_fasttarget_{safe_suffix}_{launch_id}.log'\n"
        "    launch_payload = read_json_file(launch_relative)\n"
        "    if not isinstance(launch_payload, dict) or launch_payload.get('load_error'):\n"
        "        launch_payload = None\n"
        "    if isinstance(launch_payload, dict):\n"
        "        pid_relative = launch_payload.get('pid_file') or pid_relative\n"
        "        log_relative = launch_payload.get('log_file') or log_relative\n"
        "    pid = None\n"
        "    pid_source = None\n"
        "    pid_parse_error = None\n"
        "    if file_info(pid_relative).get('exists'):\n"
        "        try:\n"
        "            pid = int(read_text_file(pid_relative).splitlines()[0].strip())\n"
        "            pid_source = 'pid_file'\n"
        "        except Exception as exc:\n"
        "            pid_parse_error = str(exc)\n"
        "    if pid is None and isinstance(launch_payload, dict) and launch_payload.get('pid') is not None:\n"
        "        try:\n"
        "            pid = int(launch_payload['pid'])\n"
        "            pid_source = 'launch_json'\n"
        "        except Exception as exc:\n"
        "            pid_parse_error = str(exc)\n"
        "    process_alive, process_check_error = process_alive_for_pid(pid)\n"
        "    archive = file_info(config['results_archive'])\n"
        "    archive_present = bool(archive.get('exists') and int(archive.get('size_bytes') or 0) > 0)\n"
        "    if archive_present:\n"
        "        status = 'ready'\n"
        "    elif process_alive is True:\n"
        "        status = 'running'\n"
        "    elif launch_payload is None and pid is None:\n"
        "        status = 'not_started'\n"
        "    elif process_alive is False:\n"
        "        status = 'stopped_without_ready_artifacts'\n"
        "    else:\n"
        "        status = 'unknown'\n"
        "    return {\n"
        "        'schema_version': 1,\n"
        "        'run_suffix': config.get('run_suffix'),\n"
        "        'status': status,\n"
        "        'ready_for_finalize': archive_present,\n"
        "        'archive_present': archive_present,\n"
        "        'launch_id': launch_id,\n"
        "        'launch_file': file_info(launch_relative),\n"
        "        'launch_payload': launch_payload,\n"
        "        'pid_file': file_info(pid_relative),\n"
        "        'pid': pid,\n"
        "        'pid_source': pid_source,\n"
        "        'pid_parse_error': pid_parse_error,\n"
        "        'process_alive': process_alive,\n"
        "        'process_check_error': process_check_error,\n"
        "        'log_file': file_tail_info(log_relative),\n"
        "        'results_archive': archive,\n"
        "    }\n"
        "\n"
        "begin = time.time()\n"
        "attempts = 0\n"
        "last = None\n"
        "while True:\n"
        "    attempts += 1\n"
        "    last = snapshot()\n"
        "    last['attempts'] = attempts\n"
        "    last['elapsed_seconds'] = round(time.time() - begin, 6)\n"
        "    last['full_wait_timeout_seconds'] = wait_timeout\n"
        "    last['full_poll_interval_seconds'] = poll_interval\n"
        "    if last.get('ready_for_finalize') is True:\n"
        "        print(json.dumps(last, sort_keys=True))\n"
        "        raise SystemExit(0)\n"
        "    if last.get('status') in {'not_started', 'stopped_without_ready_artifacts'}:\n"
        "        print(json.dumps(last, sort_keys=True))\n"
        "        raise SystemExit(2)\n"
        "    if wait_timeout <= 0 or time.time() - begin >= wait_timeout:\n"
        "        last['status'] = 'wait_timeout'\n"
        "        print(json.dumps(last, sort_keys=True))\n"
        "        raise SystemExit(3)\n"
        "    time.sleep(min(poll_interval, max(0.0, wait_timeout - (time.time() - begin))))\n"
        "PY"
    )


def _parse_last_json_object(output: str) -> dict[str, Any] | None:
    for line in reversed(output.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        return parsed if isinstance(parsed, dict) else None
    return None


def _remote_status_target_table_ready(status: dict[str, Any] | None) -> bool:
    if not isinstance(status, dict):
        return False
    table = status.get("table")
    metadata = status.get("metadata")
    return (
        isinstance(table, dict)
        and table.get("exists") is True
        and status.get("target_table_size_matches_expected") is True
        and isinstance(metadata, dict)
        and metadata.get("exists") is True
        and status.get("metadata_trusted_table") is True
        and status.get("target_table_full_checksum_valid") is True
    )


def _resume_decision_from_remote_status(status: dict[str, Any] | None) -> str:
    if isinstance(status, dict):
        results_archive = status.get("results_archive")
        if (
            isinstance(results_archive, dict)
            and results_archive.get("exists") is True
            and status.get("contract_fast_runtime_proven_for_every_possible_state") is True
        ):
            return "fetch_finalize"
    return "full" if _remote_status_target_table_ready(status) else "prerequisites_then_full"


def _staged_decision_from_remote_status(status: dict[str, Any] | None) -> str:
    if isinstance(status, dict):
        results_archive = status.get("results_archive")
        if (
            isinstance(results_archive, dict)
            and results_archive.get("exists") is True
            and status.get("contract_fast_runtime_proven_for_every_possible_state") is True
        ):
            return "fetch_finalize"
        if _remote_status_target_table_ready(status):
            return "full"
        detached = status.get("detached_prerequisite")
        if isinstance(detached, dict) and detached.get("process_alive") is True:
            return "wait_prerequisites_then_full"
    return "start_prerequisites_then_full"


def _detached_staged_decision_from_remote_status(status: dict[str, Any] | None) -> str:
    if isinstance(status, dict):
        results_archive = status.get("results_archive")
        if (
            isinstance(results_archive, dict)
            and results_archive.get("exists") is True
            and int(results_archive.get("size_bytes") or 0) > 0
        ):
            return "fetch_finalize"
        detached_full = status.get("detached_full_proof")
        if isinstance(detached_full, dict) and detached_full.get("process_alive") is True:
            return "wait_full"
        if _remote_status_target_table_ready(status):
            return "start_full_then_wait"
        detached_prerequisite = status.get("detached_prerequisite")
        if (
            isinstance(detached_prerequisite, dict)
            and detached_prerequisite.get("process_alive") is True
        ):
            return "wait_prerequisites_then_start_full"
    return "start_prerequisites_then_start_full"


def _final_contract_path(root: Path, context: dict[str, Any]) -> Path | None:
    solver = context.get("solver")
    profile = context.get("profile")
    seed = context.get("seed")
    if solver is None or profile is None or seed is None:
        return None
    return (
        root
        / "results"
        / "processed"
        / f"h48_oracle_contract_seed_{seed}_{profile}_{solver}.json"
    )


def _final_contract_summary(root: Path, context: dict[str, Any]) -> dict[str, Any]:
    path = _final_contract_path(root, context)
    if path is None:
        return {"exists": False, "path": None}
    relative = _relative(root, path)
    if not path.exists():
        return {"exists": False, "path": relative}
    try:
        payload = _load_json(path)
    except Exception as exc:  # pragma: no cover - defensive corruption report
        return {"exists": True, "path": relative, "load_error": str(exc)}
    cloud = payload.get("cloud_runtime_proof")
    cloud_runtime_proof_passed = cloud.get("passed") is True if isinstance(cloud, dict) else None
    all_required_workloads_passed = (
        cloud.get("all_required_workloads_passed") is True if isinstance(cloud, dict) else None
    )
    all_required_artifact_integrity_passed = (
        cloud.get("all_required_artifact_integrity_passed") is True
        if isinstance(cloud, dict)
        else None
    )
    cloud_runtime_evidence_passed = (
        cloud.get("cloud_runtime_evidence_passed") is True if isinstance(cloud, dict) else None
    )
    artifact_integrity_required_count = (
        cloud.get("artifact_integrity_required_workload_count")
        if isinstance(cloud, dict)
        else None
    )
    artifact_integrity_passed_count = (
        cloud.get("artifact_integrity_passed_workload_count")
        if isinstance(cloud, dict)
        else None
    )
    return {
        "exists": True,
        "path": relative,
        "passed": payload.get("passed") is True,
        "solver": payload.get("solver"),
        "all_state_exact_contract_supported": payload.get("all_state_exact_contract_supported")
        is True,
        "empirical_fast_corpus_supported": payload.get("empirical_fast_corpus_supported") is True,
        "fast_runtime_proven_for_every_possible_state": payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is True,
        "cloud_runtime_proof_passed": cloud_runtime_proof_passed,
        "all_required_workloads_passed": all_required_workloads_passed,
        "all_required_artifact_integrity_passed": all_required_artifact_integrity_passed,
        "cloud_runtime_evidence_passed": cloud_runtime_evidence_passed,
        "artifact_integrity_required_workload_count": artifact_integrity_required_count,
        "artifact_integrity_passed_workload_count": artifact_integrity_passed_count,
        "artifact_integrity_count_matches": (
            isinstance(artifact_integrity_required_count, int)
            and artifact_integrity_required_count > 0
            and artifact_integrity_required_count == artifact_integrity_passed_count
        ),
        "missing_or_failed_workload_count": (
            cloud.get("missing_or_failed_workload_count")
            if isinstance(cloud, dict)
            else None
        ),
    }


def _prerequisite_collection_keys(mode: str) -> list[str]:
    if mode == "split":
        return ["collect_prerequisite_table_parts"]
    if mode == "both":
        return ["collect_prerequisite_tables", "collect_prerequisite_table_parts"]
    return ["collect_prerequisite_tables"]


def _prerequisite_collection_step_ids(mode: str) -> list[tuple[str, str]]:
    if mode == "split":
        return [("remote_collect_prerequisite_table_parts", "collect_prerequisite_table_parts")]
    if mode == "both":
        return [
            ("remote_collect_prerequisite_tables", "collect_prerequisite_tables"),
            ("remote_collect_prerequisite_table_parts", "collect_prerequisite_table_parts"),
        ]
    return [("remote_collect_prerequisite_tables", "collect_prerequisite_tables")]


def _prerequisite_scripts_for_mode(generated: dict[str, Any], mode: str) -> list[str]:
    return [
        str(generated[key])
        for key in ["run_full_prerequisites", *_prerequisite_collection_keys(mode)]
    ]


def _prerequisite_fetch_resume_group(remote_action: str) -> str | None:
    if remote_action == "resume":
        return "prerequisites"
    if remote_action in {"staged-proof", "detached-staged-proof"}:
        return "prerequisite_wait"
    return None


def build_remote_proof_steps(
    *,
    root: Path,
    runbook_manifest_path: Path,
    host: str,
    remote_root: str,
    port: int | None = None,
    identity_file: Path | None = None,
    ssh_options: list[str] | None = None,
    rsync_excludes: list[str] | None = None,
    rsync_delete: bool = False,
    skip_sync: bool = False,
    skip_fetch: bool = False,
    skip_local_finalize: bool = False,
    install_fetched_prerequisites: bool = False,
    prerequisite_bundle_mode: str = "archive",
    fetch_diagnostics_on_fail: bool = True,
    remote_action: str = "end-to-end",
    prerequisite_wait_timeout_seconds: float = 0.0,
    prerequisite_poll_interval_seconds: float = 30.0,
    full_wait_timeout_seconds: float = 0.0,
    full_poll_interval_seconds: float = 30.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build the local/remote commands needed for a one-machine proof run."""

    root = root.resolve()
    if remote_action not in REMOTE_ACTION_CHOICES:
        raise ValueError(
            f"unsupported remote action {remote_action!r}; expected one of "
            f"{', '.join(REMOTE_ACTION_CHOICES)}"
        )
    if prerequisite_bundle_mode not in PREREQUISITE_BUNDLE_MODE_CHOICES:
        raise ValueError(
            f"unsupported prerequisite bundle mode {prerequisite_bundle_mode!r}; expected one of "
            f"{', '.join(PREREQUISITE_BUNDLE_MODE_CHOICES)}"
        )
    manifest_path = runbook_manifest_path if runbook_manifest_path.is_absolute() else root / runbook_manifest_path
    manifest = _load_json(manifest_path)
    generated = manifest.get("generated_files") or {}
    required_keys_by_action = {
        "end-to-end": [
            "run_end_to_end_single_machine",
            "unpack_results",
            "finalize_full_after_collect",
        ],
        "preflight": ["preflight_leader"],
        "canary": ["run_canary"],
        "canary-after-prerequisites": [
            "preflight_worker",
            "validate_prerequisite_tables",
            "run_canary_after_prerequisites",
        ],
        "start-prerequisites": [
            "preflight_leader",
            "run_full_prerequisites",
            "collect_prerequisite_tables",
        ],
        "prerequisites": ["run_full_prerequisites", "collect_prerequisite_tables"],
        "full": [
            "preflight_worker",
            "validate_prerequisite_tables",
            "run_full",
            "evaluate_full",
            "collect_results",
            "unpack_results",
            "finalize_full_after_collect",
        ],
        "start-full": [
            "preflight_worker",
            "validate_prerequisite_tables",
            "run_canary_after_prerequisites",
            "run_full",
            "evaluate_full",
            "collect_results",
        ],
        "wait-full": [
            "unpack_results",
            "finalize_full_after_collect",
        ],
        "status": [],
        "wait-prerequisites": [],
        "recover-prerequisite-metadata": ["recover_prerequisite_metadata"],
        "resume": [
            "run_full_prerequisites",
            "collect_prerequisite_tables",
            "preflight_worker",
            "validate_prerequisite_tables",
            "run_full",
            "evaluate_full",
            "collect_results",
            "unpack_results",
            "finalize_full_after_collect",
        ],
        "staged-proof": [
            "preflight_leader",
            "run_full_prerequisites",
            "collect_prerequisite_tables",
            "preflight_worker",
            "validate_prerequisite_tables",
            "run_canary_after_prerequisites",
            "run_full",
            "evaluate_full",
            "collect_results",
            "unpack_results",
            "finalize_full_after_collect",
        ],
        "detached-staged-proof": [
            "preflight_leader",
            "run_full_prerequisites",
            "collect_prerequisite_tables",
            "preflight_worker",
            "validate_prerequisite_tables",
            "run_canary_after_prerequisites",
            "run_full",
            "evaluate_full",
            "collect_results",
            "unpack_results",
            "finalize_full_after_collect",
        ],
    }
    prerequisite_collecting_actions = {
        "start-prerequisites",
        "prerequisites",
        "resume",
        "staged-proof",
        "detached-staged-proof",
    }
    required_keys = list(required_keys_by_action[remote_action])
    if remote_action in prerequisite_collecting_actions:
        required_keys = [
            key for key in required_keys if key != "collect_prerequisite_tables"
        ]
        required_keys.extend(_prerequisite_collection_keys(prerequisite_bundle_mode))
    if (
        install_fetched_prerequisites
        and not skip_fetch
        and remote_action
        in {
            "prerequisites",
            "wait-prerequisites",
            "resume",
            "staged-proof",
            "detached-staged-proof",
        }
    ):
        required_keys = [*required_keys, "install_prerequisite_tables"]
    missing = [key for key in required_keys if key not in generated]
    if missing:
        raise ValueError(f"runbook manifest is missing generated file(s): {', '.join(missing)}")

    run_suffix = str(manifest.get("run_suffix") or manifest_path.stem.removeprefix("cloud_hardtail_runbook_"))
    archive_relative = f"results/cloud_hardtail_artifacts_{run_suffix}.tar.gz"
    prerequisite_archive_relative = f"results/cloud_hardtail_prerequisite_tables_{run_suffix}.tar.gz"
    prerequisite_parts_relative = f"results/cloud_hardtail_prerequisite_tables_{run_suffix}_parts"
    remote_root_clean = remote_root.rstrip("/")
    ssh_options = list(ssh_options or [])
    excludes = list(DEFAULT_RSYNC_EXCLUDES)
    excludes.extend(rsync_excludes or [])
    expected_table_size = (
        (manifest.get("recommended_minimum_cloud_machine") or {}).get("h48_target_table_size_bytes")
        or manifest.get("h48_target_table_size_bytes")
    )
    expected_table_size_int = int(expected_table_size) if expected_table_size is not None else None

    steps: list[dict[str, Any]] = []
    if remote_action not in {"status", "wait-prerequisites", "wait-full"}:
        steps.append(
            {
                "id": "remote_prepare",
                "location": "local_ssh",
                "command": _remote_shell(
                    host=host,
                    port=port,
                    identity_file=identity_file,
                    ssh_options=ssh_options,
                    command=f"mkdir -p {shlex.quote(remote_root_clean)}",
                ),
                "required": True,
            }
        )
        if not skip_sync:
            steps.append(
                {
                    "id": "sync_repo_to_remote",
                    "location": "local_rsync",
                    "command": [
                        *_rsync_prefix(
                            port=port,
                            identity_file=identity_file,
                            ssh_options=ssh_options,
                            delete=rsync_delete,
                            excludes=excludes,
                        ),
                        f"{root}/",
                        f"{host}:{remote_root_clean}/",
                    ],
                    "required": True,
                }
            )
    elif remote_action == "status":
        steps.append(
            {
                "id": "remote_status",
                "location": "remote",
                "command": _remote_shell(
                    host=host,
                    port=port,
                    identity_file=identity_file,
                    ssh_options=ssh_options,
                    command=_remote_status_command(
                        remote_root=remote_root_clean,
                        run_suffix=run_suffix,
                        solver=manifest.get("solver"),
                        profile=manifest.get("profile"),
                        seed=manifest.get("seed"),
                        results_archive=archive_relative,
                        prerequisite_tables_archive=prerequisite_archive_relative,
                        prerequisite_tables_parts_dir=prerequisite_parts_relative,
                        prerequisite_bundle_mode=prerequisite_bundle_mode,
                        expected_table_size_bytes=expected_table_size_int,
                    ),
                ),
                "required": True,
            }
        )
    elif remote_action == "wait-prerequisites":
        steps.append(
            {
                "id": "remote_wait_prerequisites",
                "location": "remote",
                "command": _remote_shell(
                    host=host,
                    port=port,
                    identity_file=identity_file,
                    ssh_options=ssh_options,
                    command=_remote_wait_prerequisites_command(
                        remote_root=remote_root_clean,
                        run_suffix=run_suffix,
                        solver=manifest.get("solver"),
                        profile=manifest.get("profile"),
                        seed=manifest.get("seed"),
                        prerequisite_tables_archive=prerequisite_archive_relative,
                        prerequisite_tables_parts_dir=prerequisite_parts_relative,
                        prerequisite_bundle_mode=prerequisite_bundle_mode,
                        expected_table_size_bytes=expected_table_size_int,
                        prerequisite_wait_timeout_seconds=prerequisite_wait_timeout_seconds,
                        prerequisite_poll_interval_seconds=prerequisite_poll_interval_seconds,
                    ),
                ),
                "required": True,
            }
        )
    else:
        steps.append(
            {
                "id": "remote_wait_full",
                "location": "remote",
                "command": _remote_shell(
                    host=host,
                    port=port,
                    identity_file=identity_file,
                    ssh_options=ssh_options,
                    command=_remote_wait_full_command(
                        remote_root=remote_root_clean,
                        run_suffix=run_suffix,
                        results_archive=archive_relative,
                        full_wait_timeout_seconds=full_wait_timeout_seconds,
                        full_poll_interval_seconds=full_poll_interval_seconds,
                    ),
                ),
                "required": True,
            }
        )

    if remote_action in {"resume", "staged-proof", "detached-staged-proof"}:
        steps.append(
            {
                "id": "remote_status",
                "location": "remote",
                "command": _remote_shell(
                    host=host,
                    port=port,
                    identity_file=identity_file,
                    ssh_options=ssh_options,
                    command=_remote_status_command(
                        remote_root=remote_root_clean,
                        run_suffix=run_suffix,
                        solver=manifest.get("solver"),
                        profile=manifest.get("profile"),
                        seed=manifest.get("seed"),
                        results_archive=archive_relative,
                        prerequisite_tables_archive=prerequisite_archive_relative,
                        prerequisite_tables_parts_dir=prerequisite_parts_relative,
                        prerequisite_bundle_mode=prerequisite_bundle_mode,
                        expected_table_size_bytes=expected_table_size_int,
                    ),
                ),
                "required": True,
                "resume_group": "status",
            }
        )

    def add_remote_script_step(step_id: str, script_key: str) -> None:
        remote_script = str(generated[script_key])
        steps.append(
            {
                "id": step_id,
                "location": "remote",
                "command": _remote_shell(
                    host=host,
                    port=port,
                    identity_file=identity_file,
                    ssh_options=ssh_options,
                    command=(
                        f"cd {shlex.quote(remote_root_clean)} && "
                        f"bash {shlex.quote(remote_script)}"
                    ),
                ),
                "required": True,
                "script": remote_script,
            }
        )

    if (
        "bootstrap_cloud_machine" in generated
        and remote_action
        not in {"end-to-end", "status", "wait-prerequisites", "wait-full"}
    ):
        add_remote_script_step("remote_bootstrap_cloud_machine", "bootstrap_cloud_machine")

    if remote_action == "end-to-end":
        add_remote_script_step("remote_run_end_to_end", "run_end_to_end_single_machine")
    elif remote_action == "preflight":
        add_remote_script_step("remote_preflight_leader", "preflight_leader")
    elif remote_action == "canary":
        add_remote_script_step("remote_run_canary", "run_canary")
    elif remote_action == "canary-after-prerequisites":
        add_remote_script_step("remote_preflight_worker", "preflight_worker")
        add_remote_script_step("remote_validate_prerequisite_tables", "validate_prerequisite_tables")
        add_remote_script_step("remote_run_canary_after_prerequisites", "run_canary_after_prerequisites")
    elif remote_action == "start-prerequisites":
        add_remote_script_step("remote_preflight_leader", "preflight_leader")
        prerequisite_scripts = _prerequisite_scripts_for_mode(
            generated, prerequisite_bundle_mode
        )
        steps.append(
            {
                "id": "remote_start_prerequisites_detached",
                "location": "remote",
                "command": _remote_shell(
                    host=host,
                    port=port,
                    identity_file=identity_file,
                    ssh_options=ssh_options,
                    command=_remote_detached_scripts_command(
                        remote_root=remote_root_clean,
                        run_suffix=run_suffix,
                        launch_id="start_prerequisites",
                        scripts=prerequisite_scripts,
                    ),
                ),
                "required": True,
                "detached": True,
                "scripts": prerequisite_scripts,
            }
        )
    elif remote_action == "recover-prerequisite-metadata":
        add_remote_script_step(
            "remote_recover_prerequisite_metadata",
            "recover_prerequisite_metadata",
        )
    elif remote_action in {"staged-proof", "detached-staged-proof"}:
        add_remote_script_step("remote_preflight_leader", "preflight_leader")
        steps[-1]["resume_group"] = "prerequisite_start"
        prerequisite_scripts = _prerequisite_scripts_for_mode(
            generated, prerequisite_bundle_mode
        )
        steps.append(
            {
                "id": "remote_start_prerequisites_detached",
                "location": "remote",
                "command": _remote_shell(
                    host=host,
                    port=port,
                    identity_file=identity_file,
                    ssh_options=ssh_options,
                    command=_remote_detached_scripts_command(
                        remote_root=remote_root_clean,
                        run_suffix=run_suffix,
                        launch_id="start_prerequisites",
                        scripts=prerequisite_scripts,
                    ),
                ),
                "required": True,
                "detached": True,
                "scripts": prerequisite_scripts,
                "resume_group": "prerequisite_start",
            }
        )
        steps.append(
            {
                "id": "remote_wait_prerequisites",
                "location": "remote",
                "command": _remote_shell(
                    host=host,
                    port=port,
                    identity_file=identity_file,
                    ssh_options=ssh_options,
                    command=_remote_wait_prerequisites_command(
                        remote_root=remote_root_clean,
                        run_suffix=run_suffix,
                        solver=manifest.get("solver"),
                        profile=manifest.get("profile"),
                        seed=manifest.get("seed"),
                        prerequisite_tables_archive=prerequisite_archive_relative,
                        prerequisite_tables_parts_dir=prerequisite_parts_relative,
                        prerequisite_bundle_mode=prerequisite_bundle_mode,
                        expected_table_size_bytes=expected_table_size_int,
                        prerequisite_wait_timeout_seconds=prerequisite_wait_timeout_seconds,
                        prerequisite_poll_interval_seconds=prerequisite_poll_interval_seconds,
                    ),
                ),
                "required": True,
                "resume_group": "prerequisite_wait",
            }
        )
    elif remote_action == "start-full":
        full_scripts = [
            str(generated["preflight_worker"]),
            str(generated["validate_prerequisite_tables"]),
            str(generated["run_canary_after_prerequisites"]),
            str(generated["run_full"]),
            str(generated["evaluate_full"]),
            str(generated["collect_results"]),
        ]
        steps.append(
            {
                "id": "remote_start_full_detached",
                "location": "remote",
                "command": _remote_shell(
                    host=host,
                    port=port,
                    identity_file=identity_file,
                    ssh_options=ssh_options,
                    command=_remote_detached_scripts_command(
                        remote_root=remote_root_clean,
                        run_suffix=run_suffix,
                        launch_id="start_full",
                        scripts=full_scripts,
                    ),
                ),
                "required": True,
                "detached": True,
                "scripts": full_scripts,
            }
        )
    elif remote_action in {"prerequisites", "resume"}:
        add_remote_script_step("remote_run_prerequisites", "run_full_prerequisites")
        if remote_action == "resume":
            steps[-1]["resume_group"] = "prerequisites"
        for step_id, script_key in _prerequisite_collection_step_ids(
            prerequisite_bundle_mode
        ):
            add_remote_script_step(step_id, script_key)
            if remote_action == "resume":
                steps[-1]["resume_group"] = "prerequisites"
    if remote_action == "detached-staged-proof":
        full_scripts = [
            str(generated["preflight_worker"]),
            str(generated["validate_prerequisite_tables"]),
            str(generated["run_canary_after_prerequisites"]),
            str(generated["run_full"]),
            str(generated["evaluate_full"]),
            str(generated["collect_results"]),
        ]
        steps.append(
            {
                "id": "remote_start_full_detached",
                "location": "remote",
                "command": _remote_shell(
                    host=host,
                    port=port,
                    identity_file=identity_file,
                    ssh_options=ssh_options,
                    command=_remote_detached_scripts_command(
                        remote_root=remote_root_clean,
                        run_suffix=run_suffix,
                        launch_id="start_full",
                        scripts=full_scripts,
                    ),
                ),
                "required": True,
                "detached": True,
                "scripts": full_scripts,
                "resume_group": "full_start",
            }
        )
        steps.append(
            {
                "id": "remote_wait_full",
                "location": "remote",
                "command": _remote_shell(
                    host=host,
                    port=port,
                    identity_file=identity_file,
                    ssh_options=ssh_options,
                    command=_remote_wait_full_command(
                        remote_root=remote_root_clean,
                        run_suffix=run_suffix,
                        results_archive=archive_relative,
                        full_wait_timeout_seconds=full_wait_timeout_seconds,
                        full_poll_interval_seconds=full_poll_interval_seconds,
                    ),
                ),
                "required": True,
                "resume_group": "full_wait",
            }
        )

    if remote_action in {"full", "resume", "staged-proof"}:
        add_remote_script_step("remote_preflight_worker", "preflight_worker")
        if remote_action in {"resume", "staged-proof"}:
            steps[-1]["resume_group"] = "full"
        add_remote_script_step("remote_validate_prerequisite_tables", "validate_prerequisite_tables")
        if remote_action in {"resume", "staged-proof"}:
            steps[-1]["resume_group"] = "full"
        if remote_action == "staged-proof":
            add_remote_script_step("remote_run_canary_after_prerequisites", "run_canary_after_prerequisites")
            steps[-1]["resume_group"] = "full"
        add_remote_script_step("remote_run_full", "run_full")
        if remote_action in {"resume", "staged-proof"}:
            steps[-1]["resume_group"] = "full"
        add_remote_script_step("remote_evaluate_full", "evaluate_full")
        if remote_action in {"resume", "staged-proof"}:
            steps[-1]["resume_group"] = "full"
        add_remote_script_step("remote_collect_results", "collect_results")
        if remote_action in {"resume", "staged-proof"}:
            steps[-1]["resume_group"] = "full"

    if not skip_fetch and remote_action in {
        "end-to-end",
        "full",
        "wait-full",
        "staged-proof",
        "detached-staged-proof",
    }:
        steps.append(
            {
                "id": "fetch_results_archive",
                "location": "local_rsync",
                "command": [
                    *_rsync_prefix(
                        port=port,
                        identity_file=identity_file,
                        ssh_options=ssh_options,
                        delete=False,
                        excludes=[],
                    ),
                    f"{host}:{remote_root_clean}/{archive_relative}",
                    str(root / "results" / ""),
                ],
                "required": True,
                "archive": archive_relative,
            }
        )
    if not skip_fetch and remote_action in {
        "prerequisites",
        "wait-prerequisites",
        "resume",
        "staged-proof",
        "detached-staged-proof",
    }:
        prerequisite_fetch_resume_group = _prerequisite_fetch_resume_group(remote_action)
        prerequisite_install_source_relative = prerequisite_archive_relative
        prerequisite_install_source_path = root / prerequisite_archive_relative
        if prerequisite_bundle_mode in {"archive", "both"}:
            steps.append(
                {
                    "id": "fetch_prerequisite_tables_archive",
                    "location": "local_rsync",
                    "command": [
                        *_rsync_prefix(
                            port=port,
                            identity_file=identity_file,
                            ssh_options=ssh_options,
                            delete=False,
                            excludes=[],
                        ),
                        f"{host}:{remote_root_clean}/{prerequisite_archive_relative}",
                        str(root / "results" / ""),
                    ],
                    "required": True,
                    "archive": prerequisite_archive_relative,
                    "prerequisite_bundle_mode": prerequisite_bundle_mode,
                    "resume_group": prerequisite_fetch_resume_group,
                }
            )
        if prerequisite_bundle_mode in {"split", "both"}:
            prerequisite_install_source_relative = prerequisite_parts_relative
            prerequisite_install_source_path = root / prerequisite_parts_relative
            steps.append(
                {
                    "id": "fetch_prerequisite_table_parts",
                    "location": "local_rsync",
                    "command": [
                        *_rsync_prefix(
                            port=port,
                            identity_file=identity_file,
                            ssh_options=ssh_options,
                            delete=False,
                            excludes=[],
                        ),
                        f"{host}:{remote_root_clean}/{prerequisite_parts_relative}/",
                        str(root / prerequisite_parts_relative / ""),
                    ],
                    "required": True,
                    "parts_dir": prerequisite_parts_relative,
                    "prerequisite_bundle_mode": prerequisite_bundle_mode,
                    "resume_group": prerequisite_fetch_resume_group,
                }
            )
        if install_fetched_prerequisites:
            steps.append(
                {
                    "id": "install_fetched_prerequisite_tables",
                    "location": "local",
                    "command": [
                        "bash",
                        str(root / str(generated["install_prerequisite_tables"])),
                        str(prerequisite_install_source_path),
                    ],
                    "required": True,
                    "archive": prerequisite_archive_relative
                    if prerequisite_bundle_mode == "archive"
                    else None,
                    "parts_dir": prerequisite_parts_relative
                    if prerequisite_bundle_mode in {"split", "both"}
                    else None,
                    "install_source": prerequisite_install_source_relative,
                    "prerequisite_bundle_mode": prerequisite_bundle_mode,
                    "resume_group": prerequisite_fetch_resume_group,
                }
            )
    if not skip_fetch and remote_action in {
        "preflight",
        "canary",
        "canary-after-prerequisites",
        "start-prerequisites",
        "prerequisites",
        "wait-prerequisites",
        "recover-prerequisite-metadata",
        "start-full",
        "wait-full",
        "resume",
        "staged-proof",
        "detached-staged-proof",
    }:
        steps.append(
            {
                "id": "fetch_processed_artifacts",
                "location": "local_rsync",
                "command": [
                    *_rsync_prefix(
                        port=port,
                        identity_file=identity_file,
                        ssh_options=ssh_options,
                        delete=False,
                        excludes=[],
                    ),
                    f"{host}:{remote_root_clean}/results/processed/",
                    str(root / "results" / "processed" / ""),
                ],
                "required": True,
                "resume_group": (
                    "prerequisites"
                    if remote_action == "resume"
                    else "prerequisite_wait"
                    if remote_action == "staged-proof"
                    else "full"
                    if remote_action == "detached-staged-proof"
                    else None
                ),
            }
        )
    if not skip_fetch and remote_action == "resume":
        steps.append(
            {
                "id": "fetch_results_archive",
                "location": "local_rsync",
                "command": [
                    *_rsync_prefix(
                        port=port,
                        identity_file=identity_file,
                        ssh_options=ssh_options,
                        delete=False,
                        excludes=[],
                    ),
                    f"{host}:{remote_root_clean}/{archive_relative}",
                    str(root / "results" / ""),
                ],
                "required": True,
                "archive": archive_relative,
                "resume_group": "full",
            }
        )
    if not skip_local_finalize and remote_action in {
        "end-to-end",
        "full",
        "wait-full",
        "resume",
        "staged-proof",
        "detached-staged-proof",
    }:
        steps.append(
            _validate_results_archive_step(
                root=root,
                runbook_manifest_path=manifest_path,
                archive_relative=archive_relative,
                run_suffix=run_suffix,
            )
        )
        steps.append(
            {
                "id": "unpack_results_archive",
                "location": "local",
                "command": [
                    "bash",
                    str(root / str(generated["unpack_results"])),
                    archive_relative,
                ],
                "required": True,
                "resume_group": (
                    "full"
                    if remote_action in {"resume", "staged-proof", "detached-staged-proof"}
                    else None
                ),
            }
        )
        steps.append(
            {
                "id": "finalize_after_collect",
                "location": "local",
                "command": [
                    "bash",
                    str(root / str(generated["finalize_full_after_collect"])),
                ],
                "required": True,
                "resume_group": (
                    "full"
                    if remote_action in {"resume", "staged-proof", "detached-staged-proof"}
                    else None
                ),
            }
        )

    context = {
        "runbook_manifest_path": _relative(root, manifest_path),
        "run_suffix": run_suffix,
        "solver": manifest.get("solver"),
        "profile": manifest.get("profile"),
        "seed": manifest.get("seed"),
        "remote_host": host,
        "remote_root": remote_root_clean,
        "remote_action": remote_action,
        "results_archive": archive_relative,
        "prerequisite_tables_archive": prerequisite_archive_relative,
        "prerequisite_tables_parts_dir": prerequisite_parts_relative,
        "prerequisite_bundle_mode": prerequisite_bundle_mode,
        "prerequisite_install_source": (
            prerequisite_parts_relative
            if prerequisite_bundle_mode in {"split", "both"}
            else prerequisite_archive_relative
        ),
        "expected_table_size_bytes": expected_table_size_int,
        "install_fetched_prerequisites": bool(install_fetched_prerequisites),
        "fetch_diagnostics_on_fail": bool(fetch_diagnostics_on_fail and not skip_fetch),
        "diagnostic_fetch_command": (
            shlex.join(
                [
                    *_rsync_prefix(
                        port=port,
                        identity_file=identity_file,
                        ssh_options=ssh_options,
                        delete=False,
                        excludes=[],
                    ),
                    f"{host}:{remote_root_clean}/results/processed/",
                    str(root / "results" / "processed" / ""),
                ]
            )
            if fetch_diagnostics_on_fail and not skip_fetch
            else None
        ),
        "fetch_processed_command": (
            shlex.join(
                [
                    *_rsync_prefix(
                        port=port,
                        identity_file=identity_file,
                        ssh_options=ssh_options,
                        delete=False,
                        excludes=[],
                    ),
                    f"{host}:{remote_root_clean}/results/processed/",
                    str(root / "results" / "processed" / ""),
                ]
            )
            if not skip_fetch
            else None
        ),
        "recommended_minimum_cloud_machine": manifest.get("recommended_minimum_cloud_machine"),
        "parallel_estimate": manifest.get("parallel_estimate"),
        "resume_decision_policy": (
            "remote_status results archive exists and remote contract records "
            "fast_runtime_proven_for_every_possible_state=true -> fetch_finalize; "
            "otherwise target table exists, metadata exists, size matches expected, "
            "metadata_trusted_table=true, and full checksum validates -> full; "
            "otherwise prerequisites_then_full"
        )
        if remote_action == "resume"
        else (
            "remote_status results archive exists and remote contract records "
            "fast_runtime_proven_for_every_possible_state=true -> fetch_finalize; "
            "otherwise target table exists, metadata exists, size matches expected, "
            "metadata_trusted_table=true, and full checksum validates -> full; "
            "otherwise a live detached prerequisite process -> wait_prerequisites_then_full; "
            "otherwise start_prerequisites_then_full"
        )
        if remote_action == "staged-proof"
        else (
            "remote_status results archive exists -> fetch_finalize; "
            "otherwise a live detached full proof process -> wait_full; "
            "otherwise target table exists, metadata exists, size matches expected, "
            "metadata_trusted_table=true, and full checksum validates -> start_full_then_wait; "
            "otherwise a live detached prerequisite process -> wait_prerequisites_then_start_full; "
            "otherwise start_prerequisites_then_start_full"
        )
        if remote_action == "detached-staged-proof"
        else None,
        "prerequisite_wait_timeout_seconds": prerequisite_wait_timeout_seconds
        if remote_action in {"wait-prerequisites", "staged-proof", "detached-staged-proof"}
        else None,
        "prerequisite_poll_interval_seconds": prerequisite_poll_interval_seconds
        if remote_action in {"wait-prerequisites", "staged-proof", "detached-staged-proof"}
        else None,
        "full_wait_timeout_seconds": full_wait_timeout_seconds
        if remote_action in {"wait-full", "detached-staged-proof"}
        else None,
        "full_poll_interval_seconds": full_poll_interval_seconds
        if remote_action in {"wait-full", "detached-staged-proof"}
        else None,
        "fast_runtime_proven_for_every_possible_state": False,
    }
    return steps, context


def _diagnostic_fetch_step(
    *,
    root: Path,
    host: str,
    remote_root: str,
    port: int | None,
    identity_file: Path | None,
    ssh_options: list[str],
) -> dict[str, Any]:
    return {
        "id": "fetch_diagnostics_on_fail",
        "location": "local_rsync",
        "command": [
            *_rsync_prefix(
                port=port,
                identity_file=identity_file,
                ssh_options=ssh_options,
                delete=False,
                excludes=[],
            ),
            f"{host}:{remote_root.rstrip('/')}/results/processed/",
            str(root / "results" / "processed" / ""),
        ],
        "required": False,
    }


def _preserve_requested_prerequisite_install_step(
    *,
    step_id: str,
    install_fetched_prerequisites: bool,
) -> bool:
    return install_fetched_prerequisites and step_id in {
        "fetch_prerequisite_tables_archive",
        "fetch_prerequisite_table_parts",
        "install_fetched_prerequisite_tables",
    }


def _validate_results_archive_step(
    *,
    root: Path,
    runbook_manifest_path: Path,
    archive_relative: str,
    run_suffix: str,
) -> dict[str, Any]:
    return {
        "id": "validate_results_archive",
        "location": "local",
        "command": [
            "python",
            "scripts/validate_cloud_hardtail_archive.py",
            "--root",
            str(root),
            "--runbook",
            str(runbook_manifest_path),
            "--archive",
            archive_relative,
            "--artifact-suffix",
            f"h48_fasttarget_{_safe_id(run_suffix)}",
        ],
        "required": True,
        "archive": archive_relative,
        "resume_group": "full",
    }


def run_remote_fasttarget_proof(
    *,
    root: Path,
    runbook_manifest_path: Path,
    host: str,
    remote_root: str,
    port: int | None = None,
    identity_file: Path | None = None,
    ssh_options: list[str] | None = None,
    rsync_excludes: list[str] | None = None,
    rsync_delete: bool = False,
    skip_sync: bool = False,
    skip_fetch: bool = False,
    skip_local_finalize: bool = False,
    install_fetched_prerequisites: bool = False,
    prerequisite_bundle_mode: str = "archive",
    fetch_diagnostics_on_fail: bool = True,
    remote_action: str = "end-to-end",
    execute: bool = False,
    timeout_seconds: float | None = None,
    prerequisite_wait_timeout_seconds: float = 0.0,
    prerequisite_poll_interval_seconds: float = 30.0,
    full_wait_timeout_seconds: float = 0.0,
    full_poll_interval_seconds: float = 30.0,
    artifact_suffix: str = "remote",
) -> tuple[dict[str, Any], Path]:
    """Execute or dry-run the remote H48 proof command sequence."""

    root = root.resolve()
    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=runbook_manifest_path,
        host=host,
        remote_root=remote_root,
        port=port,
        identity_file=identity_file,
        ssh_options=ssh_options or [],
        rsync_excludes=rsync_excludes or [],
        rsync_delete=rsync_delete,
        skip_sync=skip_sync,
        skip_fetch=skip_fetch,
        skip_local_finalize=skip_local_finalize,
        install_fetched_prerequisites=install_fetched_prerequisites,
        prerequisite_bundle_mode=prerequisite_bundle_mode,
        fetch_diagnostics_on_fail=fetch_diagnostics_on_fail,
        remote_action=remote_action,
        prerequisite_wait_timeout_seconds=prerequisite_wait_timeout_seconds,
        prerequisite_poll_interval_seconds=prerequisite_poll_interval_seconds,
        full_wait_timeout_seconds=full_wait_timeout_seconds,
        full_poll_interval_seconds=full_poll_interval_seconds,
    )
    begin = time.perf_counter()
    rows: list[dict[str, Any]] = []
    halted = False
    resume_decision: str | None = None
    for step in steps:
        resume_group = step.get("resume_group")
        row = {
            "id": step["id"],
            "location": step["location"],
            "required": step.get("required") is True,
            "command": [str(part) for part in step["command"]],
            "shell_command": shlex.join([str(part) for part in step["command"]]),
            "executed": False,
            "passed": False,
            "return_code": None,
            "timed_out": False,
            "resume_group": resume_group,
            "detached": step.get("detached") is True,
            "skipped_by_resume_decision": False,
        }
        if (
            execute
            and remote_action in {"resume", "staged-proof", "detached-staged-proof"}
            and resume_decision in {"full", "fetch_finalize"}
            and resume_group in {"prerequisites", "prerequisite_start", "prerequisite_wait"}
            and not _preserve_requested_prerequisite_install_step(
                step_id=step["id"],
                install_fetched_prerequisites=install_fetched_prerequisites,
            )
        ):
            row.update(
                {
                    "passed": True,
                    "skipped_by_resume_decision": True,
                    "resume_decision": resume_decision,
                    "skip_reason": (
                        "remote target H48 table, metadata, size, and full checksum are already trusted"
                    ),
                }
            )
            rows.append(row)
            continue
        if (
            execute
            and remote_action in {"staged-proof", "detached-staged-proof"}
            and resume_decision
            in {"wait_prerequisites_then_full", "wait_prerequisites_then_start_full"}
            and resume_group == "prerequisite_start"
        ):
            row.update(
                {
                    "passed": True,
                    "skipped_by_resume_decision": True,
                    "resume_decision": resume_decision,
                    "skip_reason": "detached H48 prerequisite is already running remotely",
                }
            )
            rows.append(row)
            continue
        if (
            execute
            and remote_action == "detached-staged-proof"
            and resume_decision in {"wait_full", "start_full_then_wait", "fetch_finalize"}
            and resume_group in {"prerequisite_start", "prerequisite_wait"}
            and not _preserve_requested_prerequisite_install_step(
                step_id=step["id"],
                install_fetched_prerequisites=install_fetched_prerequisites,
            )
        ):
            row.update(
                {
                    "passed": True,
                    "skipped_by_resume_decision": True,
                    "resume_decision": resume_decision,
                    "skip_reason": "remote prerequisite table is no longer needed for this resume path",
                }
            )
            rows.append(row)
            continue
        if (
            execute
            and remote_action == "detached-staged-proof"
            and resume_decision in {"wait_full", "fetch_finalize"}
            and resume_group == "full_start"
        ):
            row.update(
                {
                    "passed": True,
                    "skipped_by_resume_decision": True,
                    "resume_decision": resume_decision,
                    "skip_reason": "detached full proof has already started or completed remotely",
                }
            )
            rows.append(row)
            continue
        if (
            execute
            and remote_action == "detached-staged-proof"
            and resume_decision == "fetch_finalize"
            and resume_group == "full_wait"
        ):
            row.update(
                {
                    "passed": True,
                    "skipped_by_resume_decision": True,
                    "resume_decision": resume_decision,
                    "skip_reason": "remote results archive already exists",
                }
            )
            rows.append(row)
            continue
        if (
            execute
            and remote_action in {"resume", "staged-proof", "detached-staged-proof"}
            and resume_decision == "fetch_finalize"
            and resume_group == "full"
            and step.get("location") == "remote"
        ):
            row.update(
                {
                    "passed": True,
                    "skipped_by_resume_decision": True,
                    "resume_decision": resume_decision,
                    "skip_reason": (
                        "remote results archive already exists and remote contract records "
                        "fast_runtime_proven_for_every_possible_state=true"
                    ),
                }
            )
            rows.append(row)
            continue
        if execute:
            completed = run_process_tree(
                [str(part) for part in step["command"]],
                cwd=root,
                timeout_seconds=timeout_seconds,
            )
            row.update(
                {
                    "executed": True,
                    "passed": completed.return_code == 0 and not completed.timed_out,
                    "return_code": completed.return_code,
                    "timed_out": completed.timed_out,
                    "runtime_seconds": completed.runtime_seconds,
                    "terminated_process_group": completed.terminated_process_group,
                    "stdout_tail": "\n".join(completed.stdout.splitlines()[-40:]),
                    "stderr_tail": "\n".join(completed.stderr.splitlines()[-40:]),
                }
            )
            if step["id"] == "remote_status":
                parsed_status = _parse_last_json_object(completed.stdout)
                if parsed_status is not None:
                    row["remote_status"] = parsed_status
                if remote_action == "resume":
                    resume_decision = _resume_decision_from_remote_status(parsed_status)
                    row["resume_decision"] = resume_decision
                elif remote_action == "staged-proof":
                    resume_decision = _staged_decision_from_remote_status(parsed_status)
                    row["resume_decision"] = resume_decision
                elif remote_action == "detached-staged-proof":
                    resume_decision = _detached_staged_decision_from_remote_status(
                        parsed_status
                    )
                    row["resume_decision"] = resume_decision
            if step["id"] == "remote_wait_prerequisites":
                parsed_wait = _parse_last_json_object(completed.stdout)
                if parsed_wait is not None:
                    row["remote_wait_prerequisites"] = parsed_wait
            if step["id"] == "remote_wait_full":
                parsed_wait_full = _parse_last_json_object(completed.stdout)
                if parsed_wait_full is not None:
                    row["remote_wait_full"] = parsed_wait_full
            if step.get("detached") is True:
                parsed_launch = _parse_last_json_object(completed.stdout)
                if parsed_launch is not None:
                    row["detached_launch"] = parsed_launch
        rows.append(row)
        if execute and row["passed"] is not True:
            if fetch_diagnostics_on_fail and not skip_fetch:
                diagnostic_step = _diagnostic_fetch_step(
                    root=root,
                    host=host,
                    remote_root=remote_root,
                    port=port,
                    identity_file=identity_file,
                    ssh_options=ssh_options or [],
                )
                completed = run_process_tree(
                    [str(part) for part in diagnostic_step["command"]],
                    cwd=root,
                    timeout_seconds=timeout_seconds,
                )
                rows.append(
                    {
                        "id": diagnostic_step["id"],
                        "location": diagnostic_step["location"],
                        "required": False,
                        "command": [str(part) for part in diagnostic_step["command"]],
                        "shell_command": shlex.join(
                            [str(part) for part in diagnostic_step["command"]]
                        ),
                        "executed": True,
                        "passed": completed.return_code == 0 and not completed.timed_out,
                        "return_code": completed.return_code,
                        "timed_out": completed.timed_out,
                        "runtime_seconds": completed.runtime_seconds,
                        "terminated_process_group": completed.terminated_process_group,
                        "stdout_tail": "\n".join(completed.stdout.splitlines()[-40:]),
                        "stderr_tail": "\n".join(completed.stderr.splitlines()[-40:]),
                        "triggered_by_failed_step": row["id"],
                    }
                )
            halted = True
            break

    all_steps_passed = bool(rows) and all(row.get("passed") is True for row in rows)
    remote_status = next(
        (
            row["remote_status"]
            for row in rows
            if row.get("id") == "remote_status" and isinstance(row.get("remote_status"), dict)
        ),
        None,
    )
    remote_wait_prerequisites = next(
        (
            row["remote_wait_prerequisites"]
            for row in rows
            if row.get("id") == "remote_wait_prerequisites"
            and isinstance(row.get("remote_wait_prerequisites"), dict)
        ),
        None,
    )
    remote_wait_full = next(
        (
            row["remote_wait_full"]
            for row in rows
            if row.get("id") == "remote_wait_full"
            and isinstance(row.get("remote_wait_full"), dict)
        ),
        None,
    )
    final_contract = _final_contract_summary(root, context)
    final_contract_required_for_pass = (
        execute
        and remote_action
        in {
            "end-to-end",
            "full",
            "wait-full",
            "resume",
            "staged-proof",
            "detached-staged-proof",
        }
        and all_steps_passed
    )
    final_contract_proof_passed = (
        final_contract.get("fast_runtime_proven_for_every_possible_state") is True
        and final_contract.get("passed") is True
        and final_contract.get("solver") == context.get("solver")
        and final_contract.get("all_state_exact_contract_supported") is True
        and final_contract.get("empirical_fast_corpus_supported") is True
        and final_contract.get("cloud_runtime_proof_passed") is True
        and final_contract.get("all_required_workloads_passed") is True
        and final_contract.get("all_required_artifact_integrity_passed") is True
        and final_contract.get("cloud_runtime_evidence_passed") is True
        and final_contract.get("artifact_integrity_count_matches") is True
        and final_contract.get("missing_or_failed_workload_count") == 0
    )
    passed = all_steps_passed and (
        not final_contract_required_for_pass or final_contract_proof_passed
    )
    payload = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        **context,
        "execute": execute,
        "dry_run": not execute,
        "rsync_delete": rsync_delete,
        "skip_sync": skip_sync,
        "skip_fetch": skip_fetch,
        "skip_local_finalize": skip_local_finalize,
        "install_fetched_prerequisites": install_fetched_prerequisites,
        "fetch_diagnostics_on_fail": bool(fetch_diagnostics_on_fail and not skip_fetch),
        "remote_action": remote_action,
        "resume_decision": resume_decision,
        "resume_prerequisites_skipped": any(
            row.get("skipped_by_resume_decision") is True
            and row.get("resume_group") in {"prerequisites", "prerequisite_start", "prerequisite_wait"}
            for row in rows
        ),
        "resume_remote_full_skipped": any(
            row.get("skipped_by_resume_decision") is True
            and row.get("resume_group") in {"full", "full_start", "full_wait"}
            and row.get("location") == "remote"
            for row in rows
        ),
        "timeout_seconds": timeout_seconds,
        "halted": halted,
        "step_count": len(rows),
        "executed_step_count": sum(1 for row in rows if row.get("executed") is True),
        "passed_step_count": sum(1 for row in rows if row.get("passed") is True),
        "all_steps_passed": all_steps_passed,
        "final_contract": final_contract,
        "final_contract_required_for_pass": final_contract_required_for_pass,
        "final_contract_proof_passed": final_contract_proof_passed,
        "remote_status": remote_status,
        "remote_wait_prerequisites": remote_wait_prerequisites,
        "remote_wait_full": remote_wait_full,
        "runtime_seconds": round(time.perf_counter() - begin, 6),
        "rows": rows,
        "passed": passed,
        "fast_runtime_proven_for_every_possible_state": (
            execute and all_steps_passed and final_contract_proof_passed
        ),
        "notes": (
            "Remote proof runner for the H48 fast-target runbook. For end-to-end, full, resume, "
            "wait-full, staged-proof, and detached-staged-proof "
            "execution, the runner passes only when the remote/fetch/finalize commands complete and "
            "the regenerated local H48 contract records fast_runtime_proven_for_every_possible_state=true."
        ),
    }
    run_suffix = _safe_id(str(context["run_suffix"]))
    suffix = f"_{_safe_id(artifact_suffix)}" if artifact_suffix else ""
    output = (
        root
        / "results"
        / "processed"
        / f"h48_fasttarget_remote_run_{run_suffix}{suffix}.json"
    )
    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runbook", type=Path, required=True)
    parser.add_argument("--host", required=True, help="SSH host, for example ubuntu@example")
    parser.add_argument("--remote-root", required=True, help="Remote checkout directory")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--identity-file", type=Path, default=None)
    parser.add_argument("--ssh-option", action="append", default=[])
    parser.add_argument("--rsync-exclude", action="append", default=[])
    parser.add_argument("--rsync-delete", action="store_true")
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--skip-fetch", action="store_true")
    parser.add_argument("--skip-local-finalize", action="store_true")
    parser.add_argument(
        "--install-fetched-prerequisites",
        action="store_true",
        help=(
            "After fetching a prerequisite table bundle, install it locally with "
            "the generated install_prerequisite_tables.sh script. This requires "
            "enough local disk for the target H48 table."
        ),
    )
    parser.add_argument(
        "--prerequisite-bundle-mode",
        choices=PREREQUISITE_BUNDLE_MODE_CHOICES,
        default="archive",
        help=(
            "How prerequisite H48 tables are collected and fetched: archive keeps the "
            "legacy tarball route, split uses the split-manifest parts directory, "
            "and both collects both transfer formats while installing from split parts."
        ),
    )
    parser.add_argument("--no-fetch-diagnostics-on-fail", action="store_true")
    parser.add_argument(
        "--remote-action",
        choices=REMOTE_ACTION_CHOICES,
        default="end-to-end",
        help=(
            "Remote runbook slice to execute. Use prerequisites to build/package the "
            "H48 target table first, canary-after-prerequisites to validate a "
            "shared-prerequisite canary without rebuilding the table, preflight to "
            "sync and run only the remote leader preflight before generation, "
            "start-prerequisites to launch the long H48 table prerequisite detached, "
            "wait-prerequisites to poll the detached prerequisite until its archive "
            "and target table metadata are ready, full to resume hard-tail execution, "
            "recover-prerequisite-metadata to adopt trusted metadata for an already "
            "completed canonical H48 table without accepting staged partial files, "
            "start-full to launch the canary/full/evaluate/collect proof phase detached, "
            "wait-full to poll that detached full proof until the result archive is ready, "
            "staged-proof to sync, status-check, start/wait detached prerequisites when needed, "
            "then run canary/full/finalize, detached-staged-proof to start/wait both "
            "the prerequisite and full proof phases as detached jobs, or status to inspect "
            "remote artifacts without syncing or mutating the remote root. Use resume to sync, probe status, skip "
            "prerequisites when the target table is already trusted, then run the full "
            "proof path."
        ),
    )
    parser.add_argument("--execute", action="store_true", help="Actually run SSH/rsync/local commands")
    parser.add_argument("--timeout", type=float, default=None, help="Per-step wall timeout")
    parser.add_argument(
        "--prerequisite-wait-timeout",
        type=float,
        default=0.0,
        help=(
            "Remote wait-prerequisites polling window in seconds. Zero performs one "
            "read-only probe and returns not-ready if the prerequisite is still running."
        ),
    )
    parser.add_argument(
        "--prerequisite-poll-interval",
        type=float,
        default=30.0,
        help="Seconds between remote wait-prerequisites status probes.",
    )
    parser.add_argument(
        "--full-wait-timeout",
        type=float,
        default=0.0,
        help=(
            "Remote wait-full polling window in seconds. Zero performs one read-only "
            "probe and returns not-ready if the detached full proof is still running."
        ),
    )
    parser.add_argument(
        "--full-poll-interval",
        type=float,
        default=30.0,
        help="Seconds between remote wait-full status probes.",
    )
    parser.add_argument("--artifact-suffix", default="remote")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload, output = run_remote_fasttarget_proof(
        root=args.root,
        runbook_manifest_path=args.runbook,
        host=args.host,
        remote_root=args.remote_root,
        port=args.port,
        identity_file=args.identity_file,
        ssh_options=args.ssh_option,
        rsync_excludes=args.rsync_exclude,
        rsync_delete=args.rsync_delete,
        skip_sync=args.skip_sync,
        skip_fetch=args.skip_fetch,
        skip_local_finalize=args.skip_local_finalize,
        install_fetched_prerequisites=args.install_fetched_prerequisites,
        prerequisite_bundle_mode=args.prerequisite_bundle_mode,
        fetch_diagnostics_on_fail=not args.no_fetch_diagnostics_on_fail,
        remote_action=args.remote_action,
        execute=args.execute,
        timeout_seconds=args.timeout,
        prerequisite_wait_timeout_seconds=args.prerequisite_wait_timeout,
        prerequisite_poll_interval_seconds=args.prerequisite_poll_interval,
        full_wait_timeout_seconds=args.full_wait_timeout,
        full_poll_interval_seconds=args.full_poll_interval,
        artifact_suffix=args.artifact_suffix,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "execute": payload["execute"],
                "passed": payload["passed"],
                "halted": payload["halted"],
                "step_count": payload["step_count"],
                "remote_action": payload["remote_action"],
                "prerequisite_bundle_mode": payload["prerequisite_bundle_mode"],
                "remote_host": payload["remote_host"],
                "remote_root": payload["remote_root"],
                "fast_runtime_proven_for_every_possible_state": payload[
                    "fast_runtime_proven_for_every_possible_state"
                ],
            },
            indent=2,
        )
    )
    return 0 if payload["passed"] or not args.execute else 1


if __name__ == "__main__":
    raise SystemExit(main())
