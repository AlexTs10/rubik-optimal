#!/usr/bin/env python
"""Provision, or dry-run, an AWS EC2 host for the H48 fast-target proof."""

from __future__ import annotations

import argparse
import hashlib
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


DEFAULT_REGION = "eu-west-1"
DEFAULT_INSTANCE_TYPE = "m6id.4xlarge"
DEFAULT_REMOTE_ROOT = "/mnt/sgarbas-h48-proof"
DEFAULT_ROOT_VOLUME_GIB = 80
UBUNTU_2404_AMI_PARAMETER = (
    "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
)
PAID_EC2_ACK = "I understand this starts a paid EC2 instance"
AWS_API_UNLOCK_ENV = "RUBIK_OPTIMAL_ENABLE_AWS"
AWS_API_UNLOCK_VALUE = "1"
ARCHIVED_AWS_EXECUTION_ENV = "RUBIK_OPTIMAL_REENABLE_ARCHIVED_AWS_FASTTARGET"
ARCHIVED_AWS_EXECUTION_ACK = (
    "I understand this re-enables the archived AWS H48 fast-target helper "
    "for an explicitly approved AWS account"
)
AWS_API_LOCK_MESSAGE = (
    "AWS CLI call blocked by default. Set RUBIK_OPTIMAL_ENABLE_AWS=1 only after "
    "confirming the intended AWS account and explicit cost/resource authorization."
)
AWS_ARCHIVED_EXECUTION_MESSAGE = (
    "The AWS H48 fast-target helper is archived for the current project route. "
    "Use scripts/run_h48_fasttarget_nonaws_proof.py for an approved non-AWS or "
    "otherwise explicitly approved proof host. Re-enable this archived helper only "
    f"by setting {ARCHIVED_AWS_EXECUTION_ENV} to the exact acknowledgement string."
)


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _aws_json(args: list[str]) -> Any:
    completed = _run(["aws", *args, "--output", "json"])
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip())
    return json.loads(completed.stdout)


def _aws_text(args: list[str]) -> str:
    completed = _run(["aws", *args, "--output", "text"])
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip())
    return completed.stdout.strip()


def _runbook_requirements(manifest: dict[str, Any]) -> dict[str, Any]:
    machine = manifest.get("recommended_minimum_cloud_machine") or {}
    return {
        "cpu_count": int(machine.get("cpu_count") or 16),
        "memory_gib": float(machine.get("memory_gib") or 64.0),
        "local_nvme_gib": float(machine.get("local_nvme_gib") or 250.0),
        "h48_target_solver": machine.get("h48_target_solver") or manifest.get("solver"),
        "h48_target_table_size_bytes": machine.get("h48_target_table_size_bytes"),
        "h48_target_table_size_gib": machine.get("h48_target_table_size_gib"),
    }


def _instance_storage_gib(instance_type_payload: dict[str, Any]) -> float:
    storage = instance_type_payload.get("InstanceStorageInfo") or {}
    return float(storage.get("TotalSizeInGB") or 0.0)


def summarize_instance_type(instance_type_payload: dict[str, Any]) -> dict[str, Any]:
    storage = instance_type_payload.get("InstanceStorageInfo") or {}
    return {
        "instance_type": instance_type_payload.get("InstanceType"),
        "cpu_count": int((instance_type_payload.get("VCpuInfo") or {}).get("DefaultVCpus") or 0),
        "memory_gib": round(
            float((instance_type_payload.get("MemoryInfo") or {}).get("SizeInMiB") or 0) / 1024.0,
            6,
        ),
        "local_nvme_gib": _instance_storage_gib(instance_type_payload),
        "nvme_support": storage.get("NvmeSupport"),
        "instance_storage_disks": storage.get("Disks") or [],
        "architectures": (instance_type_payload.get("ProcessorInfo") or {}).get(
            "SupportedArchitectures"
        )
        or [],
    }


def instance_type_satisfies_requirements(
    summary: dict[str, Any],
    requirements: dict[str, Any],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if int(summary.get("cpu_count") or 0) < int(requirements["cpu_count"]):
        reasons.append(
            f"instance CPU count {summary.get('cpu_count')} is below required {requirements['cpu_count']}"
        )
    if float(summary.get("memory_gib") or 0.0) < float(requirements["memory_gib"]):
        reasons.append(
            f"instance memory {summary.get('memory_gib')} GiB is below required {requirements['memory_gib']} GiB"
        )
    if float(summary.get("local_nvme_gib") or 0.0) < float(requirements["local_nvme_gib"]):
        reasons.append(
            "instance local NVMe storage "
            f"{summary.get('local_nvme_gib')} GiB is below required {requirements['local_nvme_gib']} GiB"
        )
    if summary.get("nvme_support") not in {"required", "supported"}:
        reasons.append("instance type does not report local NVMe support")
    if "x86_64" not in set(summary.get("architectures") or []):
        reasons.append("instance type does not support x86_64")
    return not reasons, reasons


def build_cloud_init(*, remote_root: str, ssh_public_key: str | None) -> str:
    key_block = ""
    if ssh_public_key:
        key_block = f"ssh_authorized_keys:\n  - {ssh_public_key.strip()}\n"
    return f"""#cloud-config
package_update: true
packages:
  - build-essential
  - clang
  - gcc
  - g++
  - git
  - make
  - nvme-cli
  - python3
  - python3-pip
  - python3-venv
  - rsync
  - tar
  - gzip
{key_block}runcmd:
  - |
    set -eux
    remote_root={shlex.quote(remote_root)}
    mkdir -p "$remote_root"
    instance_disk="$(ls -1 /dev/disk/by-id/nvme-Amazon_EC2_NVMe_Instance_Storage* 2>/dev/null | head -n1 || true)"
    if [ -n "$instance_disk" ]; then
      mkfs.ext4 -F "$instance_disk"
      mount "$instance_disk" "$remote_root"
    fi
    chown ubuntu:ubuntu "$remote_root"
    chmod 0775 "$remote_root"
"""


def build_remote_command_template(
    *,
    root: Path,
    runbook_manifest_path: Path,
    remote_root: str,
    identity_file: Path | None,
) -> str:
    identity = str(identity_file) if identity_file else "PATH_TO_PRIVATE_KEY"
    return shlex.join(
        [
            "python",
            "scripts/run_h48_fasttarget_remote.py",
            "--runbook",
            _relative(root, runbook_manifest_path),
            "--host",
            "ubuntu@PUBLIC_IP",
            "--identity-file",
            identity,
            "--remote-root",
            remote_root,
            "--remote-action",
            "detached-staged-proof",
            "--install-fetched-prerequisites",
            "--execute",
        ]
    )


def _default_ubuntu_ami(region: str) -> str:
    return _aws_text(
        [
            "ssm",
            "get-parameter",
            "--region",
            region,
            "--name",
            UBUNTU_2404_AMI_PARAMETER,
            "--query",
            "Parameter.Value",
        ]
    )


def _describe_instance_type(region: str, instance_type: str) -> dict[str, Any]:
    payload = _aws_json(
        [
            "ec2",
            "describe-instance-types",
            "--region",
            region,
            "--instance-types",
            instance_type,
        ]
    )
    rows = payload.get("InstanceTypes") or []
    if not rows:
        raise RuntimeError(f"instance type not found in {region}: {instance_type}")
    return rows[0]


def _default_subnet(region: str) -> str:
    payload = _aws_json(
        [
            "ec2",
            "describe-subnets",
            "--region",
            region,
            "--filters",
            "Name=default-for-az,Values=true",
            "--query",
            "Subnets | sort_by(@, &AvailabilityZone)[0]",
        ]
    )
    subnet_id = payload.get("SubnetId") if isinstance(payload, dict) else None
    if not subnet_id:
        raise RuntimeError(f"no default subnet found in {region}")
    return str(subnet_id)


def _default_security_group(region: str) -> str | None:
    payload = _aws_json(
        [
            "ec2",
            "describe-security-groups",
            "--region",
            region,
            "--filters",
            "Name=group-name,Values=default",
            "--query",
            "SecurityGroups[0]",
        ]
    )
    if isinstance(payload, dict):
        return str(payload.get("GroupId") or "") or None
    return None


def _run_instances_command(
    *,
    region: str,
    ami_id: str,
    instance_type: str,
    subnet_id: str,
    security_group_id: str | None,
    root_volume_gib: int,
    instance_name: str,
    cloud_init_path: Path,
    dry_run: bool,
) -> list[str]:
    tags = [
        {"Key": "Name", "Value": instance_name},
        {"Key": "Project", "Value": "sgarbas-h48-fasttarget"},
        {"Key": "Purpose", "Value": "h48-fast-optimal-oracle-proof"},
    ]
    command = [
        "aws",
        "ec2",
        "run-instances",
        "--region",
        region,
        "--image-id",
        ami_id,
        "--instance-type",
        instance_type,
        "--subnet-id",
        subnet_id,
        "--block-device-mappings",
        json.dumps(
            [
                {
                    "DeviceName": "/dev/sda1",
                    "Ebs": {
                        "VolumeSize": root_volume_gib,
                        "VolumeType": "gp3",
                        "DeleteOnTermination": True,
                    },
                }
            ],
            separators=(",", ":"),
        ),
        "--tag-specifications",
        json.dumps(
            [{"ResourceType": "instance", "Tags": tags}],
            separators=(",", ":"),
        ),
        "--user-data",
        f"file://{cloud_init_path}",
    ]
    if security_group_id:
        command.extend(["--security-group-ids", security_group_id])
    if dry_run:
        command.append("--dry-run")
    return command


def _authorize_ssh_ingress_command(
    *,
    region: str,
    security_group_id: str,
    ssh_cidr: str,
    dry_run: bool,
) -> list[str]:
    permission = [
        {
            "IpProtocol": "tcp",
            "FromPort": 22,
            "ToPort": 22,
            "IpRanges": [
                {
                    "CidrIp": ssh_cidr,
                    "Description": "sgarbas H48 proof SSH",
                }
            ],
        }
    ]
    command = [
        "aws",
        "ec2",
        "authorize-security-group-ingress",
        "--region",
        region,
        "--group-id",
        security_group_id,
        "--ip-permissions",
        json.dumps(permission, separators=(",", ":")),
    ]
    if dry_run:
        command.append("--dry-run")
    return command


def _dry_run_summary(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
    authorized = "DryRunOperation" in output
    unauthorized = "UnauthorizedOperation" in output
    return {
        "attempted": True,
        "authorized": authorized,
        "unauthorized": unauthorized,
        "returncode": completed.returncode,
        "message": output,
        "passed": authorized,
    }


def provision_plan(
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
    skip_aws_dry_run: bool,
    paid_ec2_ack: str | None,
) -> tuple[dict[str, Any], Path]:
    manifest_path = runbook_manifest_path if runbook_manifest_path.is_absolute() else root / runbook_manifest_path
    manifest = _load_json(manifest_path)
    run_suffix = str(manifest.get("run_suffix") or manifest_path.stem.removeprefix("cloud_hardtail_runbook_"))
    safe_suffix = _safe_id(artifact_suffix or run_suffix)
    output_dir = root / "results" / f"aws_h48_fasttarget_{safe_suffix}"
    output_dir.mkdir(parents=True, exist_ok=True)

    resolved_ami = ami_id or _default_ubuntu_ami(region)
    resolved_subnet = subnet_id or _default_subnet(region)
    resolved_security_group = security_group_id or _default_security_group(region)
    instance_payload = _describe_instance_type(region, instance_type)
    instance_summary = summarize_instance_type(instance_payload)
    requirements = _runbook_requirements(manifest)
    instance_ok, instance_reasons = instance_type_satisfies_requirements(instance_summary, requirements)

    ssh_public_key = None
    if ssh_public_key_file is not None:
        ssh_public_key = ssh_public_key_file.read_text(encoding="utf-8").strip()
    if execute:
        if paid_ec2_ack != PAID_EC2_ACK:
            raise RuntimeError(
                "refusing paid EC2 launch without exact --paid-ec2-ack acknowledgement"
            )
        if not ssh_public_key:
            raise RuntimeError("refusing paid EC2 launch without --ssh-public-key-file")
        if not security_group_id:
            raise RuntimeError(
                "refusing paid EC2 launch without explicit --security-group-id for SSH access"
            )
        if not ssh_cidr:
            raise RuntimeError("refusing paid EC2 launch without --ssh-cidr for SSH ingress")
        if not instance_ok:
            raise RuntimeError("refusing paid EC2 launch because instance target is undersized")

    cloud_init = build_cloud_init(remote_root=remote_root, ssh_public_key=ssh_public_key)
    cloud_init_path = output_dir / "cloud-init.yaml"
    cloud_init_path.write_text(cloud_init, encoding="utf-8")

    instance_name = f"sgarbas-h48-fasttarget-{_safe_id(run_suffix)}"
    dry_run = not execute
    command = _run_instances_command(
        region=region,
        ami_id=resolved_ami,
        instance_type=instance_type,
        subnet_id=resolved_subnet,
        security_group_id=resolved_security_group,
        root_volume_gib=root_volume_gib,
        instance_name=instance_name,
        cloud_init_path=cloud_init_path,
        dry_run=dry_run,
    )

    aws_dry_run: dict[str, Any] | None = None
    ssh_ingress_result: dict[str, Any] | None = None
    launch_result: dict[str, Any] | None = None
    ssh_ingress_command: list[str] | None = None
    if ssh_cidr and resolved_security_group:
        ssh_ingress_command = _authorize_ssh_ingress_command(
            region=region,
            security_group_id=resolved_security_group,
            ssh_cidr=ssh_cidr,
            dry_run=dry_run,
        )
        if dry_run:
            ssh_ingress_result = _dry_run_summary(_run(ssh_ingress_command))
        elif execute:
            completed = _run(ssh_ingress_command)
            output = "\n".join(
                part for part in [completed.stdout.strip(), completed.stderr.strip()] if part
            )
            duplicate = "InvalidPermission.Duplicate" in output
            if completed.returncode != 0 and not duplicate:
                raise RuntimeError(output)
            ssh_ingress_result = {
                "attempted": True,
                "authorized": True,
                "duplicate": duplicate,
                "returncode": completed.returncode,
                "message": output,
                "passed": True,
            }
    if dry_run and not skip_aws_dry_run:
        aws_dry_run = _dry_run_summary(_run(command))
    elif execute:
        completed = _run(command)
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout).strip())
        launch_result = json.loads(completed.stdout)

    remote_command_template = build_remote_command_template(
        root=root,
        runbook_manifest_path=manifest_path,
        remote_root=remote_root,
        identity_file=ssh_private_key_file,
    )
    remote_command_path = output_dir / "run_detached_staged_proof_after_launch.sh"
    remote_command_path.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "# Replace PUBLIC_IP with the EC2 public IPv4 address after launch.\n"
        f"{remote_command_template}\n",
        encoding="utf-8",
    )
    remote_command_path.chmod(0o755)

    payload: dict[str, Any] = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "runbook_manifest_path": _relative(root, manifest_path),
        "run_suffix": run_suffix,
        "profile": manifest.get("profile"),
        "seed": manifest.get("seed"),
        "solver": manifest.get("solver"),
        "region": region,
        "ami_id": resolved_ami,
        "ami_parameter": None if ami_id else UBUNTU_2404_AMI_PARAMETER,
        "instance_type": instance_type,
        "instance_name": instance_name,
        "subnet_id": resolved_subnet,
        "security_group_id": resolved_security_group,
        "security_group_explicit": security_group_id is not None,
        "ssh_cidr": ssh_cidr,
        "root_volume_gib": root_volume_gib,
        "remote_root": remote_root,
        "runbook_requirements": requirements,
        "instance_summary": instance_summary,
        "instance_satisfies_runbook_requirements": instance_ok,
        "instance_sizing_reasons": instance_reasons,
        "cloud_init_path": _relative(root, cloud_init_path),
        "cloud_init_sha256": hashlib.sha256(cloud_init.encode("utf-8")).hexdigest(),
        "cloud_init_has_ssh_key": ssh_public_key is not None,
        "remote_command_template_path": _relative(root, remote_command_path),
        "remote_command_template": remote_command_template,
        "ssh_ingress_command": (
            [
                arg if not arg.startswith("file://") else f"file://{_relative(root, Path(arg[7:]))}"
                for arg in ssh_ingress_command
            ]
            if ssh_ingress_command
            else None
        ),
        "ssh_ingress_dry_run": ssh_ingress_result if dry_run else None,
        "ssh_ingress_result": ssh_ingress_result if execute else None,
        "aws_run_instances_command": [arg if not arg.startswith("file://") else f"file://{_relative(root, Path(arg[7:]))}" for arg in command],
        "execute": execute,
        "aws_dry_run": aws_dry_run,
        "launch_result_present": launch_result is not None,
        "launch_result": launch_result,
        "paid_ec2_ack_required_for_execute": PAID_EC2_ACK,
        "fast_runtime_proven_for_every_possible_state": False,
        "status": (
            "ec2_launch_dryrun_authorized_not_runtime_evidence"
            if aws_dry_run and aws_dry_run.get("authorized") and instance_ok
            else "ec2_instance_launched_not_runtime_evidence"
            if execute and launch_result is not None and instance_ok
            else "ec2_launch_plan_incomplete"
        ),
    }
    payload["passed"] = (
        (execute and launch_result is not None and instance_ok)
        or (not execute and bool(aws_dry_run and aws_dry_run.get("authorized")) and instance_ok)
    )
    payload["remote_access_dry_run_authorized"] = bool(
        dry_run and ssh_ingress_result and ssh_ingress_result.get("authorized")
    )
    payload["proof_host_launch_dry_run_authorized"] = bool(
        not execute
        and instance_ok
        and aws_dry_run
        and aws_dry_run.get("authorized")
        and ssh_public_key is not None
        and security_group_id is not None
        and ssh_ingress_result
        and ssh_ingress_result.get("authorized")
    )
    if payload["proof_host_launch_dry_run_authorized"]:
        payload["status"] = "ec2_and_ssh_dryrun_authorized_not_runtime_evidence"

    output = (
        root
        / "results"
        / "processed"
        / f"aws_h48_fasttarget_provision_{_safe_id(run_suffix)}_{safe_suffix}.json"
    )
    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runbook",
        type=Path,
        default=Path("results/processed/cloud_hardtail_runbook_cloud_20260601_h48h10_fasttarget_batch10.json"),
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
    parser.add_argument("--artifact-suffix", default="aws_dryrun")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--skip-aws-dry-run", action="store_true")
    parser.add_argument("--paid-ec2-ack")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload, output = provision_plan(
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
        skip_aws_dry_run=args.skip_aws_dry_run,
        paid_ec2_ack=args.paid_ec2_ack,
    )
    print(json.dumps({"output": str(output), "passed": payload["passed"], "status": payload["status"]}))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
