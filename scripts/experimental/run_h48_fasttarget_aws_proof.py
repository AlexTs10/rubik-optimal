#!/usr/bin/env python
"""Launch, or dry-run, the AWS H48 fast-target proof workflow."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from scripts.experimental.prepare_h48_fasttarget_aws_security_group import (  # noqa: E402
    DEFAULT_DESCRIPTION as DEFAULT_SECURITY_GROUP_DESCRIPTION,
    DEFAULT_GROUP_NAME as DEFAULT_SECURITY_GROUP_NAME,
    SECURITY_GROUP_ACK,
    prepare_security_group_plan,
)
from scripts.experimental.provision_h48_fasttarget_aws import (  # noqa: E402
    ARCHIVED_AWS_EXECUTION_ACK,
    ARCHIVED_AWS_EXECUTION_ENV,
    AWS_ARCHIVED_EXECUTION_MESSAGE,
    DEFAULT_INSTANCE_TYPE,
    DEFAULT_REGION,
    DEFAULT_REMOTE_ROOT,
    DEFAULT_ROOT_VOLUME_GIB,
    PAID_EC2_ACK,
    _safe_id,
    provision_plan,
)

DEFAULT_PREREQUISITE_WAIT_TIMEOUT_SECONDS = 43_200.0
DEFAULT_PREREQUISITE_POLL_INTERVAL_SECONDS = 60.0
DEFAULT_FULL_WAIT_TIMEOUT_SECONDS = 28_800.0
DEFAULT_FULL_POLL_INTERVAL_SECONDS = 60.0
AWS_API_UNLOCK_ENV = "RUBIK_OPTIMAL_ENABLE_AWS"
AWS_API_UNLOCK_VALUE = "1"
AWS_API_LOCK_MESSAGE = (
    "AWS CLI call blocked by default. Set RUBIK_OPTIMAL_ENABLE_AWS=1 only after "
    "confirming the intended AWS account and explicit cost/resource authorization."
)


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    if command and command[0] == "aws":
        archive_ack_ok = os.environ.get(ARCHIVED_AWS_EXECUTION_ENV) == ARCHIVED_AWS_EXECUTION_ACK
        api_unlock_ok = os.environ.get(AWS_API_UNLOCK_ENV) == AWS_API_UNLOCK_VALUE
        if not archive_ack_ok or not api_unlock_ok:
            return subprocess.CompletedProcess(
                command,
                126,
                stdout="",
                stderr=f"{AWS_API_LOCK_MESSAGE} {AWS_ARCHIVED_EXECUTION_MESSAGE}",
            )
    return subprocess.run(command, text=True, capture_output=True, check=False)


def _completed_result(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "passed": completed.returncode == 0,
    }


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


def _first_instance_id(launch_result: dict[str, Any] | None) -> str | None:
    if not isinstance(launch_result, dict):
        return None
    reservations = launch_result.get("Reservations") or []
    for reservation in reservations:
        for instance in reservation.get("Instances") or []:
            instance_id = instance.get("InstanceId")
            if instance_id:
                return str(instance_id)
    for instance in launch_result.get("Instances") or []:
        instance_id = instance.get("InstanceId")
        if instance_id:
            return str(instance_id)
    return None


def _public_ip_from_describe(payload: dict[str, Any]) -> str | None:
    for reservation in payload.get("Reservations") or []:
        for instance in reservation.get("Instances") or []:
            public_ip = instance.get("PublicIpAddress")
            if public_ip:
                return str(public_ip)
    return None


def _wait_instance_status_command(*, region: str, instance_id: str) -> list[str]:
    return [
        "aws",
        "ec2",
        "wait",
        "instance-status-ok",
        "--region",
        region,
        "--instance-ids",
        instance_id,
    ]


def _describe_instance_command(*, region: str, instance_id: str) -> list[str]:
    return [
        "aws",
        "ec2",
        "describe-instances",
        "--region",
        region,
        "--instance-ids",
        instance_id,
        "--output",
        "json",
    ]


def _stop_instance_command(*, region: str, instance_id: str) -> list[str]:
    return [
        "aws",
        "ec2",
        "stop-instances",
        "--region",
        region,
        "--instance-ids",
        instance_id,
    ]


def _terminate_instance_command(*, region: str, instance_id: str) -> list[str]:
    return [
        "aws",
        "ec2",
        "terminate-instances",
        "--region",
        region,
        "--instance-ids",
        instance_id,
    ]


def _wait_instance_stopped_command(*, region: str, instance_id: str) -> list[str]:
    return [
        "aws",
        "ec2",
        "wait",
        "instance-stopped",
        "--region",
        region,
        "--instance-ids",
        instance_id,
    ]


def _wait_instance_terminated_command(*, region: str, instance_id: str) -> list[str]:
    return [
        "aws",
        "ec2",
        "wait",
        "instance-terminated",
        "--region",
        region,
        "--instance-ids",
        instance_id,
    ]


def _instance_cleanup_action(args: argparse.Namespace, *, success: bool) -> str | None:
    if success:
        if getattr(args, "terminate_instance_on_success", False):
            return "terminate"
        if getattr(args, "stop_instance_on_success", False):
            return "stop"
    else:
        if getattr(args, "terminate_instance_on_failure", False):
            return "terminate"
        if getattr(args, "stop_instance_on_failure", False):
            return "stop"
    return None


def _checkpoint_cleanup_flag(
    args: argparse.Namespace,
    checkpoint: dict[str, Any],
    name: str,
) -> bool:
    return bool(getattr(args, name, False) or checkpoint.get(name) is True)


def _instance_cleanup_action_from_checkpoint(
    args: argparse.Namespace,
    checkpoint: dict[str, Any],
    *,
    success: bool,
) -> str | None:
    if success:
        if _checkpoint_cleanup_flag(args, checkpoint, "terminate_instance_on_success"):
            return "terminate"
        if _checkpoint_cleanup_flag(args, checkpoint, "stop_instance_on_success"):
            return "stop"
    else:
        if _checkpoint_cleanup_flag(args, checkpoint, "terminate_instance_on_failure"):
            return "terminate"
        if _checkpoint_cleanup_flag(args, checkpoint, "stop_instance_on_failure"):
            return "stop"
    return None


def _cleanup_dedicated_security_group_enabled(
    args: argparse.Namespace,
    *,
    success: bool,
) -> bool:
    if not getattr(args, "create_dedicated_security_group", False):
        return False
    if success:
        return bool(getattr(args, "cleanup_dedicated_security_group_on_success", False))
    return bool(getattr(args, "cleanup_dedicated_security_group_on_failure", False))


def _checkpoint_dedicated_security_group_cleanup_enabled(
    args: argparse.Namespace,
    checkpoint: dict[str, Any],
    *,
    success: bool,
) -> bool:
    if not isinstance(checkpoint.get("dedicated_security_group_cleanup_commands"), dict):
        return False
    if success:
        return _checkpoint_cleanup_flag(
            args,
            checkpoint,
            "cleanup_dedicated_security_group_on_success",
        )
    return _checkpoint_cleanup_flag(
        args,
        checkpoint,
        "cleanup_dedicated_security_group_on_failure",
    )


def _run_instance_cleanup(
    *,
    region: str,
    instance_id: str,
    action: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if action is None:
        return None, None
    if action == "terminate":
        action_command = _terminate_instance_command(region=region, instance_id=instance_id)
        wait_command = _wait_instance_terminated_command(region=region, instance_id=instance_id)
    elif action == "stop":
        action_command = _stop_instance_command(region=region, instance_id=instance_id)
        wait_command = _wait_instance_stopped_command(region=region, instance_id=instance_id)
    else:
        raise ValueError(f"unsupported instance cleanup action: {action}")

    action_completed = _run(action_command)
    action_result = {
        **_completed_result(action_completed),
        "action": action,
        "command": action_command,
    }
    if action_completed.returncode != 0:
        return action_result, None

    wait_completed = _run(wait_command)
    wait_result = {
        **_completed_result(wait_completed),
        "action": action,
        "command": wait_command,
    }
    return action_result, wait_result


def _run_dedicated_security_group_cleanup(
    cleanup_commands: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(cleanup_commands, dict):
        return None
    results: dict[str, Any] = {}
    for key in ["revoke_ssh_ingress", "delete_security_group"]:
        command = cleanup_commands.get(key)
        if not command:
            results[key] = {"skipped": True, "passed": True}
            continue
        completed = _run([str(arg) for arg in command])
        results[key] = {
            **_completed_result(completed),
            "command": command,
        }
    results["passed"] = all(
        bool(value.get("passed")) for value in results.values() if isinstance(value, dict)
    )
    return results


def _add_remote_wait_args(
    command: list[str],
    *,
    prerequisite_wait_timeout_seconds: float,
    prerequisite_poll_interval_seconds: float,
    full_wait_timeout_seconds: float,
    full_poll_interval_seconds: float,
) -> None:
    command.extend(
        [
            "--prerequisite-wait-timeout",
            str(float(prerequisite_wait_timeout_seconds)),
            "--prerequisite-poll-interval",
            str(float(prerequisite_poll_interval_seconds)),
            "--full-wait-timeout",
            str(float(full_wait_timeout_seconds)),
            "--full-poll-interval",
            str(float(full_poll_interval_seconds)),
        ]
    )


def _append_cleanup_flags(
    command: list[str],
    *,
    stop_instance_on_success: bool = False,
    terminate_instance_on_success: bool = False,
    stop_instance_on_failure: bool = False,
    terminate_instance_on_failure: bool = False,
    cleanup_dedicated_security_group_on_success: bool = False,
    cleanup_dedicated_security_group_on_failure: bool = False,
) -> None:
    for enabled, flag in [
        (stop_instance_on_success, "--stop-instance-on-success"),
        (terminate_instance_on_success, "--terminate-instance-on-success"),
        (stop_instance_on_failure, "--stop-instance-on-failure"),
        (terminate_instance_on_failure, "--terminate-instance-on-failure"),
        (
            cleanup_dedicated_security_group_on_success,
            "--cleanup-dedicated-security-group-on-success",
        ),
        (
            cleanup_dedicated_security_group_on_failure,
            "--cleanup-dedicated-security-group-on-failure",
        ),
    ]:
        if enabled:
            command.append(flag)


def _append_cleanup_flags_from_args(command: list[str], args: argparse.Namespace) -> None:
    _append_cleanup_flags(
        command,
        stop_instance_on_success=bool(getattr(args, "stop_instance_on_success", False)),
        terminate_instance_on_success=bool(
            getattr(args, "terminate_instance_on_success", False)
        ),
        stop_instance_on_failure=bool(getattr(args, "stop_instance_on_failure", False)),
        terminate_instance_on_failure=bool(
            getattr(args, "terminate_instance_on_failure", False)
        ),
        cleanup_dedicated_security_group_on_success=bool(
            getattr(args, "cleanup_dedicated_security_group_on_success", False)
        ),
        cleanup_dedicated_security_group_on_failure=bool(
            getattr(args, "cleanup_dedicated_security_group_on_failure", False)
        ),
    )


def build_remote_start_command(
    *,
    root: Path,
    runbook_manifest_path: Path,
    public_ip: str,
    identity_file: Path,
    remote_root: str,
    remote_action: str = "detached-staged-proof",
    prerequisite_wait_timeout_seconds: float = DEFAULT_PREREQUISITE_WAIT_TIMEOUT_SECONDS,
    prerequisite_poll_interval_seconds: float = DEFAULT_PREREQUISITE_POLL_INTERVAL_SECONDS,
    full_wait_timeout_seconds: float = DEFAULT_FULL_WAIT_TIMEOUT_SECONDS,
    full_poll_interval_seconds: float = DEFAULT_FULL_POLL_INTERVAL_SECONDS,
) -> list[str]:
    manifest_path = (
        runbook_manifest_path if runbook_manifest_path.is_absolute() else root / runbook_manifest_path
    )
    command = [
        "python",
        "scripts/run_h48_fasttarget_remote.py",
        "--runbook",
        _relative(root, manifest_path),
        "--host",
        f"ubuntu@{public_ip}",
        "--identity-file",
        str(identity_file),
        "--remote-root",
        remote_root,
        "--remote-action",
        remote_action,
        "--install-fetched-prerequisites",
        "--execute",
    ]
    _add_remote_wait_args(
        command,
        prerequisite_wait_timeout_seconds=prerequisite_wait_timeout_seconds,
        prerequisite_poll_interval_seconds=prerequisite_poll_interval_seconds,
        full_wait_timeout_seconds=full_wait_timeout_seconds,
        full_poll_interval_seconds=full_poll_interval_seconds,
    )
    return command


def _checkpoint_path_argument(root: Path, checkpoint_path: Path | str) -> str:
    if isinstance(checkpoint_path, Path):
        return _relative(root, checkpoint_path)
    return str(checkpoint_path)


def build_checkpoint_resume_command(
    *,
    root: Path,
    checkpoint_path: Path | str,
    ssh_private_key_file: Path | None,
    artifact_suffix: str,
    remote_action: str = "detached-staged-proof",
    execute: bool = True,
    prerequisite_wait_timeout_seconds: float = DEFAULT_PREREQUISITE_WAIT_TIMEOUT_SECONDS,
    prerequisite_poll_interval_seconds: float = DEFAULT_PREREQUISITE_POLL_INTERVAL_SECONDS,
    full_wait_timeout_seconds: float = DEFAULT_FULL_WAIT_TIMEOUT_SECONDS,
    full_poll_interval_seconds: float = DEFAULT_FULL_POLL_INTERVAL_SECONDS,
    stop_instance_on_success: bool = False,
    terminate_instance_on_success: bool = False,
    stop_instance_on_failure: bool = False,
    terminate_instance_on_failure: bool = False,
    cleanup_dedicated_security_group_on_success: bool = False,
    cleanup_dedicated_security_group_on_failure: bool = False,
) -> list[str]:
    command = [
        "python",
        "scripts/run_h48_fasttarget_aws_proof.py",
        "--resume-from-checkpoint",
        _checkpoint_path_argument(root, checkpoint_path),
        "--artifact-suffix",
        artifact_suffix,
        "--resume-remote-action",
        remote_action,
    ]
    if ssh_private_key_file is not None:
        command.extend(["--ssh-private-key-file", str(ssh_private_key_file)])
    _add_remote_wait_args(
        command,
        prerequisite_wait_timeout_seconds=prerequisite_wait_timeout_seconds,
        prerequisite_poll_interval_seconds=prerequisite_poll_interval_seconds,
        full_wait_timeout_seconds=full_wait_timeout_seconds,
        full_poll_interval_seconds=full_poll_interval_seconds,
    )
    if execute:
        command.append("--execute")
    _append_cleanup_flags(
        command,
        stop_instance_on_success=stop_instance_on_success,
        terminate_instance_on_success=terminate_instance_on_success,
        stop_instance_on_failure=stop_instance_on_failure,
        terminate_instance_on_failure=terminate_instance_on_failure,
        cleanup_dedicated_security_group_on_success=(
            cleanup_dedicated_security_group_on_success
        ),
        cleanup_dedicated_security_group_on_failure=(
            cleanup_dedicated_security_group_on_failure
        ),
    )
    return command


def _path_from_checkpoint(root: Path, value: Any) -> Path | None:
    if value in {None, ""}:
        return None
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else root / path


def _identity_file_from_checkpoint(root: Path, checkpoint: dict[str, Any]) -> Path | None:
    command = checkpoint.get("remote_start_command")
    if not isinstance(command, list):
        return None
    try:
        index = command.index("--identity-file")
    except ValueError:
        return None
    if index + 1 >= len(command):
        return None
    return _path_from_checkpoint(root, command[index + 1])


def _load_checkpoint(root: Path, checkpoint_path: Path) -> tuple[dict[str, Any], Path]:
    path = checkpoint_path if checkpoint_path.is_absolute() else root / checkpoint_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"checkpoint is not a JSON object: {path}")
    return payload, path


def _checkpoint_validation_errors(
    checkpoint: dict[str, Any],
    *,
    identity_file: Path | None,
) -> list[str]:
    errors: list[str] = []
    for key in ["runbook_manifest_path", "region", "instance_id", "public_ip", "remote_root"]:
        value = checkpoint.get(key)
        if value is None or str(value).strip() == "":
            errors.append(f"checkpoint missing {key}")
    if identity_file is None or str(identity_file) == "PATH_TO_PRIVATE_KEY":
        errors.append("checkpoint resume requires an SSH private key")
    return errors


def build_remote_resume_command(
    *,
    root: Path,
    checkpoint: dict[str, Any],
    identity_file: Path,
    remote_action: str = "detached-staged-proof",
    prerequisite_wait_timeout_seconds: float = DEFAULT_PREREQUISITE_WAIT_TIMEOUT_SECONDS,
    prerequisite_poll_interval_seconds: float = DEFAULT_PREREQUISITE_POLL_INTERVAL_SECONDS,
    full_wait_timeout_seconds: float = DEFAULT_FULL_WAIT_TIMEOUT_SECONDS,
    full_poll_interval_seconds: float = DEFAULT_FULL_POLL_INTERVAL_SECONDS,
) -> list[str]:
    runbook_path = _path_from_checkpoint(root, checkpoint.get("runbook_manifest_path"))
    if runbook_path is None:
        raise ValueError("checkpoint missing runbook_manifest_path")
    return build_remote_start_command(
        root=root,
        runbook_manifest_path=runbook_path,
        public_ip=str(checkpoint.get("public_ip") or ""),
        identity_file=identity_file,
        remote_root=str(checkpoint.get("remote_root") or DEFAULT_REMOTE_ROOT),
        remote_action=remote_action,
        prerequisite_wait_timeout_seconds=prerequisite_wait_timeout_seconds,
        prerequisite_poll_interval_seconds=prerequisite_poll_interval_seconds,
        full_wait_timeout_seconds=full_wait_timeout_seconds,
        full_poll_interval_seconds=full_poll_interval_seconds,
    )


def _cleanup_passed(
    *,
    cleanup_attempted: bool,
    instance_cleanup_action: str | None,
    instance_cleanup_result: dict[str, Any] | None,
    instance_cleanup_wait_result: dict[str, Any] | None,
    dedicated_security_group_cleanup_requested: bool,
    dedicated_security_group_cleanup_result: dict[str, Any] | None,
) -> bool | None:
    if not cleanup_attempted:
        return None
    return (
        (
            (not instance_cleanup_action)
            or (
                instance_cleanup_result is not None
                and instance_cleanup_result.get("passed") is True
                and instance_cleanup_wait_result is not None
                and instance_cleanup_wait_result.get("passed") is True
            )
        )
        and (
            (not dedicated_security_group_cleanup_requested)
            or (
                dedicated_security_group_cleanup_result is not None
                and dedicated_security_group_cleanup_result.get("passed") is True
            )
        )
    )


def _command_for_artifact(root: Path, command: list[str]) -> list[str]:
    normalized: list[str] = []
    for arg in command:
        if arg.startswith("file://"):
            path = Path(arg[7:])
            normalized.append(f"file://{_relative(root, path)}")
        else:
            normalized.append(arg)
    return normalized


def _write_execute_script(
    *,
    root: Path,
    output_dir: Path,
    args: argparse.Namespace,
) -> Path:
    script = output_dir / "start_h48_fasttarget_aws_proof.sh"
    create_dedicated_security_group = bool(
        getattr(args, "create_dedicated_security_group", False)
    )
    proof_command = [
        "python",
        "scripts/run_h48_fasttarget_aws_proof.py",
        "--runbook",
        str(args.runbook),
        "--region",
        args.region,
        "--instance-type",
        args.instance_type,
        "--ssh-cidr",
        "${SSH_CIDR}",
        "--ssh-public-key-file",
        str(args.ssh_public_key_file or Path("~/.ssh/id_ed25519.pub")),
        "--ssh-private-key-file",
        str(args.ssh_private_key_file or Path("~/.ssh/id_ed25519")),
        "--remote-root",
        args.remote_root,
        "--artifact-suffix",
        args.artifact_suffix,
        "--execute",
        "--start-remote-proof",
        "--paid-ec2-ack",
        "${PAID_EC2_ACK}",
    ]
    _add_remote_wait_args(
        proof_command,
        prerequisite_wait_timeout_seconds=float(
            getattr(
                args,
                "prerequisite_wait_timeout",
                DEFAULT_PREREQUISITE_WAIT_TIMEOUT_SECONDS,
            )
        ),
        prerequisite_poll_interval_seconds=float(
            getattr(
                args,
                "prerequisite_poll_interval",
                DEFAULT_PREREQUISITE_POLL_INTERVAL_SECONDS,
            )
        ),
        full_wait_timeout_seconds=float(
            getattr(args, "full_wait_timeout", DEFAULT_FULL_WAIT_TIMEOUT_SECONDS)
        ),
        full_poll_interval_seconds=float(
            getattr(args, "full_poll_interval", DEFAULT_FULL_POLL_INTERVAL_SECONDS)
        ),
    )
    if create_dedicated_security_group:
        proof_command.extend(["--security-group-id", "${SECURITY_GROUP_ID}"])
    else:
        proof_command.extend(["--security-group-id", args.security_group_id or "SECURITY_GROUP_ID"])
    if args.subnet_id:
        proof_command.extend(["--subnet-id", args.subnet_id])
    if args.ami_id:
        proof_command.extend(["--ami-id", args.ami_id])
    _append_cleanup_flags_from_args(proof_command, args)
    shell_command = (
        shlex.join(proof_command)
        .replace("'${PAID_EC2_ACK}'", '"${PAID_EC2_ACK}"')
        .replace("'${SSH_CIDR}'", '"${SSH_CIDR}"')
        .replace("'${SECURITY_GROUP_ID}'", '"${SECURITY_GROUP_ID}"')
    )
    security_group_setup = ""
    security_group_guard = (
        ': "${SECURITY_GROUP_ID:?set SECURITY_GROUP_ID before running or rerun with '
        '--create-dedicated-security-group}"\n'
    )
    if create_dedicated_security_group:
        sg_command = [
            "python",
            "scripts/prepare_h48_fasttarget_aws_security_group.py",
            "--region",
            args.region,
            "--group-name",
            getattr(args, "security_group_name", DEFAULT_SECURITY_GROUP_NAME),
            "--description",
            getattr(
                args,
                "security_group_description",
                DEFAULT_SECURITY_GROUP_DESCRIPTION,
            ),
            "--ssh-cidr",
            "${SSH_CIDR}",
            "--artifact-suffix",
            f"{args.artifact_suffix}_sg",
            "--execute",
            "--security-group-ack",
            "${SECURITY_GROUP_ACK}",
        ]
        if getattr(args, "vpc_id", None):
            sg_command.extend(["--vpc-id", args.vpc_id])
        sg_shell_command = (
            shlex.join(sg_command)
            .replace("'${SSH_CIDR}'", '"${SSH_CIDR}"')
            .replace("'${SECURITY_GROUP_ACK}'", '"${SECURITY_GROUP_ACK}"')
        )
        security_group_guard = (
            f": \"${{SECURITY_GROUP_ACK:?set SECURITY_GROUP_ACK='{SECURITY_GROUP_ACK}' before running}}\"\n"
        )
        security_group_setup = (
            f"SG_JSON=\"$({sg_shell_command})\"\n"
            "SG_ARTIFACT=\"$(python -c 'import json,sys; print(json.load(sys.stdin)[\"output\"])' <<< \"$SG_JSON\")\"\n"
            "SECURITY_GROUP_ID=\"$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))[\"created_security_group_id\"])' \"$SG_ARTIFACT\")\"\n"
            "if [ -z \"$SECURITY_GROUP_ID\" ] || [ \"$SECURITY_GROUP_ID\" = \"None\" ]; then\n"
            "  echo \"failed to resolve created security group id from $SG_ARTIFACT\" >&2\n"
            "  exit 1\n"
            "fi\n"
            "echo \"Created dedicated proof security group: $SECURITY_GROUP_ID\"\n"
            "echo \"Cleanup commands are recorded in: $SG_ARTIFACT\"\n"
        )
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "# This starts paid AWS compute and then starts the detached H48H10 proof.\n"
        f": \"${{PAID_EC2_ACK:?set PAID_EC2_ACK='{PAID_EC2_ACK}' before running}}\"\n"
        ": \"${SSH_CIDR:?set SSH_CIDR='your.public.ip/32' before running}\"\n"
        f"{security_group_guard}"
        f"{security_group_setup}"
        f"{shell_command}\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _write_checkpoint_resume_script(
    *,
    output_dir: Path,
    resume_command_template: list[str],
) -> Path:
    script = output_dir / "resume_h48_fasttarget_aws_proof_from_checkpoint.sh"
    shell_command = shlex.join(resume_command_template).replace(
        "'${CHECKPOINT_PATH}'",
        '"${CHECKPOINT_PATH}"',
    )
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "# This resumes an already-launched proof host from a pre-remote checkpoint.\n"
        "# It does not launch a new EC2 instance.\n"
        ": \"${CHECKPOINT_PATH:?set CHECKPOINT_PATH to the pre-remote checkpoint JSON artifact}\"\n"
        f"{shell_command}\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def run_aws_proof_plan(
    *,
    root: Path,
    runbook_manifest_path: Path,
    region: str,
    instance_type: str,
    ami_id: str | None,
    subnet_id: str | None,
    security_group_id: str | None,
    root_volume_gib: int,
    remote_root: str,
    ssh_cidr: str | None,
    ssh_public_key_file: Path | None,
    ssh_private_key_file: Path | None,
    artifact_suffix: str,
    execute: bool,
    start_remote_proof: bool,
    paid_ec2_ack: str | None,
    args_for_script: argparse.Namespace,
    prerequisite_wait_timeout_seconds: float = DEFAULT_PREREQUISITE_WAIT_TIMEOUT_SECONDS,
    prerequisite_poll_interval_seconds: float = DEFAULT_PREREQUISITE_POLL_INTERVAL_SECONDS,
    full_wait_timeout_seconds: float = DEFAULT_FULL_WAIT_TIMEOUT_SECONDS,
    full_poll_interval_seconds: float = DEFAULT_FULL_POLL_INTERVAL_SECONDS,
) -> tuple[dict[str, Any], Path]:
    create_dedicated_security_group = bool(
        getattr(args_for_script, "create_dedicated_security_group", False)
    )
    dedicated_security_group_payload: dict[str, Any] | None = None
    dedicated_security_group_output: Path | None = None
    effective_security_group_id = security_group_id
    if create_dedicated_security_group:
        dedicated_security_group_payload, dedicated_security_group_output = prepare_security_group_plan(
            root=root,
            region=region,
            vpc_id=getattr(args_for_script, "vpc_id", None),
            group_name=getattr(
                args_for_script,
                "security_group_name",
                DEFAULT_SECURITY_GROUP_NAME,
            ),
            description=getattr(
                args_for_script,
                "security_group_description",
                DEFAULT_SECURITY_GROUP_DESCRIPTION,
            ),
            ssh_cidr=ssh_cidr,
            artifact_suffix=f"{artifact_suffix}_sg",
            execute=execute,
            security_group_ack=getattr(args_for_script, "security_group_ack", None),
        )
        if execute:
            effective_security_group_id = dedicated_security_group_payload.get(
                "created_security_group_id"
            )
            if not effective_security_group_id:
                raise RuntimeError("dedicated security-group creation returned no group id")

    provision_payload, provision_output = provision_plan(
        root=root,
        runbook_manifest_path=runbook_manifest_path,
        region=region,
        instance_type=instance_type,
        ami_id=ami_id,
        subnet_id=subnet_id,
        security_group_id=effective_security_group_id,
        root_volume_gib=root_volume_gib,
        remote_root=remote_root,
        ssh_cidr=ssh_cidr,
        ssh_public_key_file=ssh_public_key_file,
        ssh_private_key_file=ssh_private_key_file,
        artifact_suffix=artifact_suffix,
        execute=execute,
        skip_aws_dry_run=False,
        paid_ec2_ack=paid_ec2_ack,
    )
    run_suffix = str(provision_payload.get("run_suffix") or "h48_fasttarget")
    safe_suffix = _safe_id(artifact_suffix or run_suffix)
    output_dir = root / "results" / f"aws_h48_fasttarget_{safe_suffix}"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = (
        root
        / "results"
        / "processed"
        / f"aws_h48_fasttarget_proof_run_{_safe_id(run_suffix)}_{safe_suffix}.json"
    )
    execute_script = _write_execute_script(root=root, output_dir=output_dir, args=args_for_script)
    checkpoint_resume_suffix = f"{artifact_suffix}_checkpoint_resume"
    checkpoint_resume_template = build_checkpoint_resume_command(
        root=root,
        checkpoint_path="${CHECKPOINT_PATH}",
        ssh_private_key_file=(
            ssh_private_key_file
            or getattr(args_for_script, "ssh_private_key_file", None)
            or Path("~/.ssh/id_ed25519")
        ),
        artifact_suffix=checkpoint_resume_suffix,
        remote_action=getattr(args_for_script, "resume_remote_action", "detached-staged-proof"),
        prerequisite_wait_timeout_seconds=prerequisite_wait_timeout_seconds,
        prerequisite_poll_interval_seconds=prerequisite_poll_interval_seconds,
        full_wait_timeout_seconds=full_wait_timeout_seconds,
        full_poll_interval_seconds=full_poll_interval_seconds,
        stop_instance_on_success=bool(
            getattr(args_for_script, "stop_instance_on_success", False)
        ),
        terminate_instance_on_success=bool(
            getattr(args_for_script, "terminate_instance_on_success", False)
        ),
        stop_instance_on_failure=bool(
            getattr(args_for_script, "stop_instance_on_failure", False)
        ),
        terminate_instance_on_failure=bool(
            getattr(args_for_script, "terminate_instance_on_failure", False)
        ),
        cleanup_dedicated_security_group_on_success=bool(
            getattr(args_for_script, "cleanup_dedicated_security_group_on_success", False)
        ),
        cleanup_dedicated_security_group_on_failure=bool(
            getattr(args_for_script, "cleanup_dedicated_security_group_on_failure", False)
        ),
    )
    checkpoint_resume_script = _write_checkpoint_resume_script(
        output_dir=output_dir,
        resume_command_template=checkpoint_resume_template,
    )
    pre_remote_checkpoint_written = False
    pre_remote_checkpoint_status: str | None = None

    placeholder_instance_id = "INSTANCE_ID_AFTER_LAUNCH"
    placeholder_public_ip = "PUBLIC_IP_AFTER_LAUNCH"
    instance_id = _first_instance_id(provision_payload.get("launch_result")) or placeholder_instance_id
    public_ip = placeholder_public_ip
    wait_result: dict[str, Any] | None = None
    describe_result: dict[str, Any] | None = None
    remote_start_result: dict[str, Any] | None = None
    execution_error: str | None = None
    instance_cleanup_result: dict[str, Any] | None = None
    instance_cleanup_wait_result: dict[str, Any] | None = None
    dedicated_security_group_cleanup_result: dict[str, Any] | None = None

    wait_command = _wait_instance_status_command(region=region, instance_id=instance_id)
    describe_command = _describe_instance_command(region=region, instance_id=instance_id)
    stop_command = _stop_instance_command(region=region, instance_id=instance_id)
    terminate_command = _terminate_instance_command(region=region, instance_id=instance_id)
    wait_stopped_command = _wait_instance_stopped_command(region=region, instance_id=instance_id)
    wait_terminated_command = _wait_instance_terminated_command(
        region=region,
        instance_id=instance_id,
    )

    if execute:
        if not instance_id or instance_id == placeholder_instance_id:
            raise RuntimeError("paid launch did not return an EC2 instance id")
        wait_completed = _run(wait_command)
        wait_result = _completed_result(wait_completed)
        if wait_completed.returncode != 0:
            execution_error = wait_completed.stderr or wait_completed.stdout
        else:
            describe_completed = _run(describe_command)
            if describe_completed.returncode != 0:
                describe_result = _completed_result(describe_completed)
                execution_error = describe_completed.stderr or describe_completed.stdout
            else:
                try:
                    describe_payload = json.loads(describe_completed.stdout)
                    public_ip = _public_ip_from_describe(describe_payload) or ""
                    describe_result = {
                        **_completed_result(describe_completed),
                        "public_ip": public_ip,
                        "passed": bool(public_ip),
                    }
                    if not public_ip:
                        execution_error = "EC2 instance has no public IPv4 address"
                except json.JSONDecodeError as exc:
                    describe_result = {
                        **_completed_result(describe_completed),
                        "passed": False,
                        "json_error": str(exc),
                    }
                    execution_error = f"failed to parse describe-instances JSON: {exc}"

    if ssh_private_key_file is not None:
        remote_start_command = build_remote_start_command(
            root=root,
            runbook_manifest_path=runbook_manifest_path,
            public_ip=public_ip,
            identity_file=ssh_private_key_file,
            remote_root=remote_root,
            prerequisite_wait_timeout_seconds=prerequisite_wait_timeout_seconds,
            prerequisite_poll_interval_seconds=prerequisite_poll_interval_seconds,
            full_wait_timeout_seconds=full_wait_timeout_seconds,
            full_poll_interval_seconds=full_poll_interval_seconds,
        )
    else:
        remote_start_command = [
            "python",
            "scripts/run_h48_fasttarget_remote.py",
            "--host",
            f"ubuntu@{public_ip}",
            "--identity-file",
            "PATH_TO_PRIVATE_KEY",
            "--remote-action",
            "detached-staged-proof",
            "--install-fetched-prerequisites",
            "--execute",
        ]
        _add_remote_wait_args(
            remote_start_command,
            prerequisite_wait_timeout_seconds=prerequisite_wait_timeout_seconds,
            prerequisite_poll_interval_seconds=prerequisite_poll_interval_seconds,
            full_wait_timeout_seconds=full_wait_timeout_seconds,
            full_poll_interval_seconds=full_poll_interval_seconds,
        )

    checkpoint_resume_command = build_checkpoint_resume_command(
        root=root,
        checkpoint_path=output,
        ssh_private_key_file=ssh_private_key_file or Path("PATH_TO_PRIVATE_KEY"),
        artifact_suffix=checkpoint_resume_suffix,
        remote_action=getattr(args_for_script, "resume_remote_action", "detached-staged-proof"),
        prerequisite_wait_timeout_seconds=prerequisite_wait_timeout_seconds,
        prerequisite_poll_interval_seconds=prerequisite_poll_interval_seconds,
        full_wait_timeout_seconds=full_wait_timeout_seconds,
        full_poll_interval_seconds=full_poll_interval_seconds,
        stop_instance_on_success=bool(
            getattr(args_for_script, "stop_instance_on_success", False)
        ),
        terminate_instance_on_success=bool(
            getattr(args_for_script, "terminate_instance_on_success", False)
        ),
        stop_instance_on_failure=bool(
            getattr(args_for_script, "stop_instance_on_failure", False)
        ),
        terminate_instance_on_failure=bool(
            getattr(args_for_script, "terminate_instance_on_failure", False)
        ),
        cleanup_dedicated_security_group_on_success=bool(
            getattr(args_for_script, "cleanup_dedicated_security_group_on_success", False)
        ),
        cleanup_dedicated_security_group_on_failure=bool(
            getattr(args_for_script, "cleanup_dedicated_security_group_on_failure", False)
        ),
    )

    if execute and start_remote_proof and not execution_error:
        pre_remote_checkpoint_status = (
            "aws_h48_fasttarget_instance_ready_pre_remote_checkpoint_not_runtime_evidence"
        )
        checkpoint_payload: dict[str, Any] = {
            "schema_version": 1,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "checkpoint_kind": "pre_remote_detached_proof",
            "status": pre_remote_checkpoint_status,
            "passed": False,
            "runbook_manifest_path": provision_payload.get("runbook_manifest_path"),
            "provision_artifact_path": _relative(root, provision_output),
            "run_suffix": run_suffix,
            "profile": provision_payload.get("profile"),
            "seed": provision_payload.get("seed"),
            "solver": provision_payload.get("solver"),
            "region": region,
            "instance_type": instance_type,
            "security_group_id": provision_payload.get("security_group_id"),
            "requested_security_group_id": security_group_id,
            "dedicated_security_group_artifact_path": (
                _relative(root, dedicated_security_group_output)
                if dedicated_security_group_output is not None
                else None
            ),
            "dedicated_security_group_created_id": (
                dedicated_security_group_payload.get("created_security_group_id")
                if dedicated_security_group_payload
                else None
            ),
            "dedicated_security_group_cleanup_commands": (
                dedicated_security_group_payload.get("cleanup_commands")
                if dedicated_security_group_payload
                else None
            ),
            "ssh_cidr": ssh_cidr,
            "remote_root": remote_root,
            "prerequisite_wait_timeout_seconds": prerequisite_wait_timeout_seconds,
            "prerequisite_poll_interval_seconds": prerequisite_poll_interval_seconds,
            "full_wait_timeout_seconds": full_wait_timeout_seconds,
            "full_poll_interval_seconds": full_poll_interval_seconds,
            "execute": execute,
            "start_remote_proof": start_remote_proof,
            "provision_status": provision_payload.get("status"),
            "provision_passed": provision_payload.get("passed") is True,
            "instance_id": instance_id,
            "public_ip": public_ip,
            "aws_wait_instance_status_command": _command_for_artifact(root, wait_command),
            "aws_describe_instance_command": _command_for_artifact(root, describe_command),
            "remote_start_command": _command_for_artifact(root, remote_start_command),
            "aws_checkpoint_resume_command": _command_for_artifact(
                root,
                checkpoint_resume_command,
            ),
            "aws_stop_instance_command": _command_for_artifact(root, stop_command),
            "aws_terminate_instance_command": _command_for_artifact(root, terminate_command),
            "aws_wait_instance_stopped_command": _command_for_artifact(root, wait_stopped_command),
            "aws_wait_instance_terminated_command": _command_for_artifact(
                root,
                wait_terminated_command,
            ),
            "execute_script_path": _relative(root, execute_script),
            "checkpoint_resume_script_path": _relative(root, checkpoint_resume_script),
            "wait_result": wait_result,
            "describe_result": describe_result,
            "pre_remote_checkpoint_written": True,
            "checkpoint_written_before_remote_start": True,
            "terminate_instance_on_success": bool(
                getattr(args_for_script, "terminate_instance_on_success", False)
            ),
            "stop_instance_on_success": bool(
                getattr(args_for_script, "stop_instance_on_success", False)
            ),
            "terminate_instance_on_failure": bool(
                getattr(args_for_script, "terminate_instance_on_failure", False)
            ),
            "stop_instance_on_failure": bool(
                getattr(args_for_script, "stop_instance_on_failure", False)
            ),
            "cleanup_dedicated_security_group_on_success": bool(
                getattr(
                    args_for_script,
                    "cleanup_dedicated_security_group_on_success",
                    False,
                )
            ),
            "cleanup_dedicated_security_group_on_failure": bool(
                getattr(
                    args_for_script,
                    "cleanup_dedicated_security_group_on_failure",
                    False,
                )
            ),
            "fast_runtime_proven_for_every_possible_state": False,
        }
        write_json(output, checkpoint_payload)
        pre_remote_checkpoint_written = True

    if execute and start_remote_proof and not execution_error:
        remote_completed = _run(remote_start_command)
        remote_start_result = _completed_result(remote_completed)
        if remote_completed.returncode != 0:
            execution_error = remote_completed.stderr or remote_completed.stdout

    workflow_succeeded = (
        provision_payload.get("passed") is True
        and wait_result is not None
        and wait_result.get("passed") is True
        and describe_result is not None
        and describe_result.get("passed") is True
        and (
            not start_remote_proof
            or (
                remote_start_result is not None
                and remote_start_result.get("passed") is True
            )
        )
    )

    cleanup_outcome = "success" if workflow_succeeded else "failure"
    instance_cleanup_action = (
        _instance_cleanup_action(args_for_script, success=workflow_succeeded)
        if execute
        else None
    )
    dedicated_security_group_cleanup_requested = (
        _cleanup_dedicated_security_group_enabled(
            args_for_script,
            success=workflow_succeeded,
        )
        if execute
        else False
    )
    if execute and instance_cleanup_action:
        instance_cleanup_result, instance_cleanup_wait_result = _run_instance_cleanup(
            region=region,
            instance_id=instance_id,
            action=instance_cleanup_action,
        )
    if execute and dedicated_security_group_cleanup_requested:
        dedicated_security_group_cleanup_result = _run_dedicated_security_group_cleanup(
            dedicated_security_group_payload.get("cleanup_commands")
            if dedicated_security_group_payload
            else None
        )
    cleanup_attempted = bool(
        instance_cleanup_action or dedicated_security_group_cleanup_requested
    )
    cleanup_results = [
        instance_cleanup_result,
        instance_cleanup_wait_result,
        dedicated_security_group_cleanup_result,
    ]
    cleanup_passed = (
        None
        if not cleanup_attempted
        else all(
            result is not None and result.get("passed") is True
            for result in cleanup_results
            if result is not None
        )
        and (
            (not instance_cleanup_action)
            or (
                instance_cleanup_result is not None
                and instance_cleanup_result.get("passed") is True
                and instance_cleanup_wait_result is not None
                and instance_cleanup_wait_result.get("passed") is True
            )
        )
        and (
            (not dedicated_security_group_cleanup_requested)
            or (
                dedicated_security_group_cleanup_result is not None
                and dedicated_security_group_cleanup_result.get("passed") is True
            )
        )
    )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "runbook_manifest_path": provision_payload.get("runbook_manifest_path"),
        "provision_artifact_path": _relative(root, provision_output),
        "run_suffix": run_suffix,
        "profile": provision_payload.get("profile"),
        "seed": provision_payload.get("seed"),
        "solver": provision_payload.get("solver"),
        "region": region,
        "instance_type": instance_type,
        "security_group_id": provision_payload.get("security_group_id"),
        "requested_security_group_id": security_group_id,
        "dedicated_security_group_artifact_path": (
            _relative(root, dedicated_security_group_output)
            if dedicated_security_group_output is not None
            else None
        ),
        "dedicated_security_group_created_id": (
            dedicated_security_group_payload.get("created_security_group_id")
            if dedicated_security_group_payload
            else None
        ),
        "dedicated_security_group_status": (
            dedicated_security_group_payload.get("status") if dedicated_security_group_payload else None
        ),
        "dedicated_security_group_passed": (
            dedicated_security_group_payload.get("passed") is True
            if dedicated_security_group_payload
            else None
        ),
        "dedicated_security_group_cleanup_commands": (
            dedicated_security_group_payload.get("cleanup_commands")
            if dedicated_security_group_payload
            else None
        ),
        "ssh_cidr": ssh_cidr,
        "remote_root": remote_root,
        "prerequisite_wait_timeout_seconds": prerequisite_wait_timeout_seconds,
        "prerequisite_poll_interval_seconds": prerequisite_poll_interval_seconds,
        "full_wait_timeout_seconds": full_wait_timeout_seconds,
        "full_poll_interval_seconds": full_poll_interval_seconds,
        "execute": execute,
        "start_remote_proof": start_remote_proof,
        "provision_status": provision_payload.get("status"),
        "provision_passed": provision_payload.get("passed") is True,
        "proof_host_launch_dry_run_authorized": provision_payload.get(
            "proof_host_launch_dry_run_authorized"
        )
        is True,
        "instance_id": None if instance_id == placeholder_instance_id else instance_id,
        "public_ip": None if public_ip == placeholder_public_ip else public_ip,
        "aws_wait_instance_status_command": _command_for_artifact(root, wait_command),
        "aws_describe_instance_command": _command_for_artifact(root, describe_command),
        "remote_start_command": _command_for_artifact(root, remote_start_command),
        "aws_checkpoint_resume_command_template": _command_for_artifact(
            root,
            checkpoint_resume_template,
        ),
        "aws_stop_instance_command": _command_for_artifact(root, stop_command),
        "aws_terminate_instance_command": _command_for_artifact(root, terminate_command),
        "aws_wait_instance_stopped_command": _command_for_artifact(root, wait_stopped_command),
        "aws_wait_instance_terminated_command": _command_for_artifact(
            root,
            wait_terminated_command,
        ),
        "execute_script_path": _relative(root, execute_script),
        "checkpoint_resume_script_path": _relative(root, checkpoint_resume_script),
        "wait_result": wait_result,
        "describe_result": describe_result,
        "remote_start_result": remote_start_result,
        "execution_error": execution_error.strip() if execution_error else None,
        "pre_remote_checkpoint_written": pre_remote_checkpoint_written,
        "pre_remote_checkpoint_status": pre_remote_checkpoint_status,
        "pre_remote_checkpoint_path": (
            _relative(root, output) if pre_remote_checkpoint_written else None
        ),
        "checkpoint_written_before_remote_start": pre_remote_checkpoint_written,
        "cleanup_outcome": cleanup_outcome if execute else None,
        "cleanup_attempted": cleanup_attempted,
        "cleanup_passed": cleanup_passed,
        "instance_cleanup_action": instance_cleanup_action,
        "instance_cleanup_result": instance_cleanup_result,
        "instance_cleanup_wait_result": instance_cleanup_wait_result,
        "dedicated_security_group_cleanup_requested": (
            dedicated_security_group_cleanup_requested
        ),
        "dedicated_security_group_cleanup_result": (
            dedicated_security_group_cleanup_result
        ),
        "stop_instance_on_success": bool(
            getattr(args_for_script, "stop_instance_on_success", False)
        ),
        "terminate_instance_on_success": bool(
            getattr(args_for_script, "terminate_instance_on_success", False)
        ),
        "stop_instance_on_failure": bool(
            getattr(args_for_script, "stop_instance_on_failure", False)
        ),
        "terminate_instance_on_failure": bool(
            getattr(args_for_script, "terminate_instance_on_failure", False)
        ),
        "cleanup_dedicated_security_group_on_success": bool(
            getattr(args_for_script, "cleanup_dedicated_security_group_on_success", False)
        ),
        "cleanup_dedicated_security_group_on_failure": bool(
            getattr(args_for_script, "cleanup_dedicated_security_group_on_failure", False)
        ),
        "paid_ec2_ack_required_for_execute": PAID_EC2_ACK,
        "security_group_ack_required_for_dedicated_security_group_execute": SECURITY_GROUP_ACK,
        "create_dedicated_security_group_for_execute": bool(
            getattr(args_for_script, "create_dedicated_security_group", False)
        ),
        "security_group_execute_helper_group_name": getattr(
            args_for_script, "security_group_name", DEFAULT_SECURITY_GROUP_NAME
        ),
        "security_group_execute_helper_description": getattr(
            args_for_script,
            "security_group_description",
            DEFAULT_SECURITY_GROUP_DESCRIPTION,
        ),
        "execute_script_uses_dedicated_security_group": bool(
            getattr(args_for_script, "create_dedicated_security_group", False)
        ),
        "fast_runtime_proven_for_every_possible_state": False,
    }
    if not execute:
        payload["status"] = "aws_h48_fasttarget_proof_dryrun_planned_not_runtime_evidence"
        payload["passed"] = provision_payload.get("proof_host_launch_dry_run_authorized") is True
    elif start_remote_proof:
        payload["status"] = "aws_h48_fasttarget_detached_proof_started_not_runtime_evidence"
        payload["passed"] = workflow_succeeded and cleanup_passed is not False
    else:
        payload["status"] = "aws_h48_fasttarget_instance_ready_not_runtime_evidence"
        payload["passed"] = workflow_succeeded and cleanup_passed is not False

    write_json(output, payload)
    return payload, output


def run_aws_checkpoint_resume_plan(
    *,
    root: Path,
    checkpoint_path: Path,
    ssh_private_key_file: Path | None,
    artifact_suffix: str,
    execute: bool,
    args_for_script: argparse.Namespace,
    remote_action: str = "detached-staged-proof",
    prerequisite_wait_timeout_seconds: float = DEFAULT_PREREQUISITE_WAIT_TIMEOUT_SECONDS,
    prerequisite_poll_interval_seconds: float = DEFAULT_PREREQUISITE_POLL_INTERVAL_SECONDS,
    full_wait_timeout_seconds: float = DEFAULT_FULL_WAIT_TIMEOUT_SECONDS,
    full_poll_interval_seconds: float = DEFAULT_FULL_POLL_INTERVAL_SECONDS,
) -> tuple[dict[str, Any], Path]:
    checkpoint, resolved_checkpoint_path = _load_checkpoint(root, checkpoint_path)
    identity_file = ssh_private_key_file or _identity_file_from_checkpoint(root, checkpoint)
    validation_errors = _checkpoint_validation_errors(
        checkpoint,
        identity_file=identity_file,
    )

    run_suffix = str(checkpoint.get("run_suffix") or "h48_fasttarget")
    safe_suffix = _safe_id(artifact_suffix or "checkpoint_resume")
    output = (
        root
        / "results"
        / "processed"
        / f"aws_h48_fasttarget_checkpoint_resume_{_safe_id(run_suffix)}_{safe_suffix}.json"
    )
    region = str(checkpoint.get("region") or DEFAULT_REGION)
    instance_id = str(checkpoint.get("instance_id") or "")
    stop_command = _stop_instance_command(region=region, instance_id=instance_id)
    terminate_command = _terminate_instance_command(region=region, instance_id=instance_id)
    wait_stopped_command = _wait_instance_stopped_command(region=region, instance_id=instance_id)
    wait_terminated_command = _wait_instance_terminated_command(
        region=region,
        instance_id=instance_id,
    )
    remote_resume_command: list[str] | None = None
    if identity_file is not None and not validation_errors:
        remote_resume_command = build_remote_resume_command(
            root=root,
            checkpoint=checkpoint,
            identity_file=identity_file,
            remote_action=remote_action,
            prerequisite_wait_timeout_seconds=prerequisite_wait_timeout_seconds,
            prerequisite_poll_interval_seconds=prerequisite_poll_interval_seconds,
            full_wait_timeout_seconds=full_wait_timeout_seconds,
            full_poll_interval_seconds=full_poll_interval_seconds,
        )

    remote_resume_result: dict[str, Any] | None = None
    remote_resume_summary: dict[str, Any] | None = None
    execution_error: str | None = None
    instance_cleanup_result: dict[str, Any] | None = None
    instance_cleanup_wait_result: dict[str, Any] | None = None
    dedicated_security_group_cleanup_result: dict[str, Any] | None = None
    workflow_succeeded = False

    if execute:
        if validation_errors:
            execution_error = "; ".join(validation_errors)
        elif remote_resume_command is None:
            execution_error = "checkpoint resume command could not be built"
        else:
            completed = _run(remote_resume_command)
            remote_resume_result = _completed_result(completed)
            remote_resume_summary = _parse_last_json_object(completed.stdout)
            if remote_resume_summary is not None:
                remote_resume_result["summary"] = remote_resume_summary
            workflow_succeeded = completed.returncode == 0
            if completed.returncode != 0:
                execution_error = completed.stderr or completed.stdout

    cleanup_outcome = "success" if workflow_succeeded else "failure"
    instance_cleanup_action = (
        _instance_cleanup_action_from_checkpoint(
            args_for_script,
            checkpoint,
            success=workflow_succeeded,
        )
        if execute and not validation_errors
        else None
    )
    dedicated_security_group_cleanup_requested = (
        _checkpoint_dedicated_security_group_cleanup_enabled(
            args_for_script,
            checkpoint,
            success=workflow_succeeded,
        )
        if execute and not validation_errors
        else False
    )
    if execute and instance_cleanup_action:
        instance_cleanup_result, instance_cleanup_wait_result = _run_instance_cleanup(
            region=region,
            instance_id=instance_id,
            action=instance_cleanup_action,
        )
    if execute and dedicated_security_group_cleanup_requested:
        dedicated_security_group_cleanup_result = _run_dedicated_security_group_cleanup(
            checkpoint.get("dedicated_security_group_cleanup_commands")
        )
    cleanup_attempted = bool(
        instance_cleanup_action or dedicated_security_group_cleanup_requested
    )
    cleanup_passed = _cleanup_passed(
        cleanup_attempted=cleanup_attempted,
        instance_cleanup_action=instance_cleanup_action,
        instance_cleanup_result=instance_cleanup_result,
        instance_cleanup_wait_result=instance_cleanup_wait_result,
        dedicated_security_group_cleanup_requested=dedicated_security_group_cleanup_requested,
        dedicated_security_group_cleanup_result=dedicated_security_group_cleanup_result,
    )
    remote_fast_runtime_proven = (
        isinstance(remote_resume_summary, dict)
        and remote_resume_summary.get("fast_runtime_proven_for_every_possible_state") is True
    )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "resume_from_checkpoint": True,
        "checkpoint_path": _relative(root, resolved_checkpoint_path),
        "checkpoint_status": checkpoint.get("status"),
        "checkpoint_kind": checkpoint.get("checkpoint_kind"),
        "runbook_manifest_path": checkpoint.get("runbook_manifest_path"),
        "run_suffix": run_suffix,
        "profile": checkpoint.get("profile"),
        "seed": checkpoint.get("seed"),
        "solver": checkpoint.get("solver"),
        "region": region,
        "instance_id": instance_id or None,
        "public_ip": checkpoint.get("public_ip"),
        "remote_root": checkpoint.get("remote_root"),
        "remote_action": remote_action,
        "execute": execute,
        "validation_errors": validation_errors,
        "remote_resume_command": (
            _command_for_artifact(root, remote_resume_command)
            if remote_resume_command is not None
            else None
        ),
        "prerequisite_wait_timeout_seconds": prerequisite_wait_timeout_seconds,
        "prerequisite_poll_interval_seconds": prerequisite_poll_interval_seconds,
        "full_wait_timeout_seconds": full_wait_timeout_seconds,
        "full_poll_interval_seconds": full_poll_interval_seconds,
        "aws_stop_instance_command": _command_for_artifact(root, stop_command),
        "aws_terminate_instance_command": _command_for_artifact(root, terminate_command),
        "aws_wait_instance_stopped_command": _command_for_artifact(root, wait_stopped_command),
        "aws_wait_instance_terminated_command": _command_for_artifact(
            root,
            wait_terminated_command,
        ),
        "dedicated_security_group_cleanup_commands": checkpoint.get(
            "dedicated_security_group_cleanup_commands"
        ),
        "remote_resume_result": remote_resume_result,
        "remote_resume_summary": remote_resume_summary,
        "execution_error": execution_error.strip() if execution_error else None,
        "cleanup_outcome": cleanup_outcome if execute else None,
        "cleanup_attempted": cleanup_attempted,
        "cleanup_passed": cleanup_passed,
        "instance_cleanup_action": instance_cleanup_action,
        "instance_cleanup_result": instance_cleanup_result,
        "instance_cleanup_wait_result": instance_cleanup_wait_result,
        "dedicated_security_group_cleanup_requested": (
            dedicated_security_group_cleanup_requested
        ),
        "dedicated_security_group_cleanup_result": (
            dedicated_security_group_cleanup_result
        ),
        "stop_instance_on_success": _checkpoint_cleanup_flag(
            args_for_script,
            checkpoint,
            "stop_instance_on_success",
        ),
        "terminate_instance_on_success": _checkpoint_cleanup_flag(
            args_for_script,
            checkpoint,
            "terminate_instance_on_success",
        ),
        "stop_instance_on_failure": _checkpoint_cleanup_flag(
            args_for_script,
            checkpoint,
            "stop_instance_on_failure",
        ),
        "terminate_instance_on_failure": _checkpoint_cleanup_flag(
            args_for_script,
            checkpoint,
            "terminate_instance_on_failure",
        ),
        "cleanup_dedicated_security_group_on_success": _checkpoint_cleanup_flag(
            args_for_script,
            checkpoint,
            "cleanup_dedicated_security_group_on_success",
        ),
        "cleanup_dedicated_security_group_on_failure": _checkpoint_cleanup_flag(
            args_for_script,
            checkpoint,
            "cleanup_dedicated_security_group_on_failure",
        ),
        "fast_runtime_proven_for_every_possible_state": remote_fast_runtime_proven,
    }
    if not execute:
        payload["status"] = "aws_h48_fasttarget_checkpoint_resume_dryrun_planned_not_runtime_evidence"
        payload["passed"] = not validation_errors and remote_resume_command is not None
    else:
        payload["status"] = "aws_h48_fasttarget_checkpoint_resume_finished"
        payload["passed"] = workflow_succeeded and cleanup_passed is not False

    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runbook",
        type=Path,
        default=Path(
            "results/processed/"
            "cloud_hardtail_runbook_cloud_20260601_h48h10_fasttarget_batch10.json"
        ),
    )
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--instance-type", default=DEFAULT_INSTANCE_TYPE)
    parser.add_argument("--ami-id")
    parser.add_argument("--subnet-id")
    parser.add_argument("--security-group-id")
    parser.add_argument("--root-volume-gib", type=int, default=DEFAULT_ROOT_VOLUME_GIB)
    parser.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT)
    parser.add_argument("--ssh-cidr")
    parser.add_argument("--ssh-public-key-file", type=Path)
    parser.add_argument("--ssh-private-key-file", type=Path)
    parser.add_argument("--artifact-suffix", default="aws_proof_dryrun")
    parser.add_argument(
        "--resume-from-checkpoint",
        type=Path,
        help=(
            "Resume/recover an executed proof host from a pre-remote checkpoint "
            "artifact instead of launching a new EC2 instance."
        ),
    )
    parser.add_argument(
        "--resume-remote-action",
        choices=["detached-staged-proof", "resume"],
        default="detached-staged-proof",
    )
    parser.add_argument(
        "--prerequisite-wait-timeout",
        type=float,
        default=DEFAULT_PREREQUISITE_WAIT_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--prerequisite-poll-interval",
        type=float,
        default=DEFAULT_PREREQUISITE_POLL_INTERVAL_SECONDS,
    )
    parser.add_argument(
        "--full-wait-timeout",
        type=float,
        default=DEFAULT_FULL_WAIT_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--full-poll-interval",
        type=float,
        default=DEFAULT_FULL_POLL_INTERVAL_SECONDS,
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--start-remote-proof", action="store_true")
    parser.add_argument("--paid-ec2-ack")
    parser.add_argument("--create-dedicated-security-group", action="store_true")
    parser.add_argument("--security-group-ack")
    parser.add_argument("--security-group-name", default=DEFAULT_SECURITY_GROUP_NAME)
    parser.add_argument("--security-group-description", default=DEFAULT_SECURITY_GROUP_DESCRIPTION)
    parser.add_argument("--vpc-id")
    parser.add_argument("--stop-instance-on-success", action="store_true")
    parser.add_argument("--terminate-instance-on-success", action="store_true")
    parser.add_argument("--stop-instance-on-failure", action="store_true")
    parser.add_argument("--terminate-instance-on-failure", action="store_true")
    parser.add_argument("--cleanup-dedicated-security-group-on-success", action="store_true")
    parser.add_argument("--cleanup-dedicated-security-group-on-failure", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    if args.resume_from_checkpoint is not None:
        payload, output = run_aws_checkpoint_resume_plan(
            root=args.root,
            checkpoint_path=args.resume_from_checkpoint,
            ssh_private_key_file=args.ssh_private_key_file,
            artifact_suffix=args.artifact_suffix,
            execute=args.execute,
            args_for_script=args,
            remote_action=args.resume_remote_action,
            prerequisite_wait_timeout_seconds=args.prerequisite_wait_timeout,
            prerequisite_poll_interval_seconds=args.prerequisite_poll_interval,
            full_wait_timeout_seconds=args.full_wait_timeout,
            full_poll_interval_seconds=args.full_poll_interval,
        )
        print(json.dumps({"output": str(output), "passed": payload["passed"], "status": payload["status"]}))
        return 0 if payload["passed"] else 1

    payload, output = run_aws_proof_plan(
        root=args.root,
        runbook_manifest_path=args.runbook,
        region=args.region,
        instance_type=args.instance_type,
        ami_id=args.ami_id,
        subnet_id=args.subnet_id,
        security_group_id=args.security_group_id,
        root_volume_gib=args.root_volume_gib,
        remote_root=args.remote_root,
        ssh_cidr=args.ssh_cidr,
        ssh_public_key_file=args.ssh_public_key_file,
        ssh_private_key_file=args.ssh_private_key_file,
        artifact_suffix=args.artifact_suffix,
        execute=args.execute,
        start_remote_proof=args.start_remote_proof,
        paid_ec2_ack=args.paid_ec2_ack,
        args_for_script=args,
        prerequisite_wait_timeout_seconds=args.prerequisite_wait_timeout,
        prerequisite_poll_interval_seconds=args.prerequisite_poll_interval,
        full_wait_timeout_seconds=args.full_wait_timeout,
        full_poll_interval_seconds=args.full_poll_interval,
    )
    print(json.dumps({"output": str(output), "passed": payload["passed"], "status": payload["status"]}))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
