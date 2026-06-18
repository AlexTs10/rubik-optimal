#!/usr/bin/env python
"""Prepare, or dry-run, a dedicated AWS security group for H48 proof SSH."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from scripts.experimental.provision_h48_fasttarget_aws import (  # noqa: E402
    ARCHIVED_AWS_EXECUTION_ACK,
    ARCHIVED_AWS_EXECUTION_ENV,
    AWS_ARCHIVED_EXECUTION_MESSAGE,
    DEFAULT_REGION,
    _authorize_ssh_ingress_command,
    _dry_run_summary,
    _safe_id,
)


SECURITY_GROUP_ACK = "I understand this creates or changes an AWS security group"
DEFAULT_GROUP_NAME = "sgarbas-h48-fasttarget-proof"
DEFAULT_DESCRIPTION = "Temporary SSH access for sgarbas H48 fast-target proof host"
AWS_API_UNLOCK_ENV = "RUBIK_OPTIMAL_ENABLE_AWS"
AWS_API_UNLOCK_VALUE = "1"
AWS_API_LOCK_MESSAGE = (
    "AWS CLI call blocked by default. Set RUBIK_OPTIMAL_ENABLE_AWS=1 only after "
    "confirming the intended AWS account and explicit cost/resource authorization."
)


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


def _default_vpc(region: str) -> str:
    payload = _aws_json(
        [
            "ec2",
            "describe-vpcs",
            "--region",
            region,
            "--filters",
            "Name=is-default,Values=true",
            "--query",
            "Vpcs[0]",
        ]
    )
    vpc_id = payload.get("VpcId") if isinstance(payload, dict) else None
    if not vpc_id:
        raise RuntimeError(f"no default VPC found in {region}")
    return str(vpc_id)


def _create_security_group_command(
    *,
    region: str,
    vpc_id: str,
    group_name: str,
    description: str,
    dry_run: bool,
) -> list[str]:
    command = [
        "aws",
        "ec2",
        "create-security-group",
        "--region",
        region,
        "--group-name",
        group_name,
        "--description",
        description,
        "--vpc-id",
        vpc_id,
        "--tag-specifications",
        json.dumps(
            [
                {
                    "ResourceType": "security-group",
                    "Tags": [
                        {"Key": "Name", "Value": group_name},
                        {"Key": "Project", "Value": "sgarbas-h48-fasttarget"},
                        {"Key": "Purpose", "Value": "h48-fast-optimal-oracle-proof"},
                    ],
                }
            ],
            separators=(",", ":"),
        ),
    ]
    if dry_run:
        command.append("--dry-run")
    return command


def _delete_security_group_command(*, region: str, security_group_id: str) -> list[str]:
    return [
        "aws",
        "ec2",
        "delete-security-group",
        "--region",
        region,
        "--group-id",
        security_group_id,
    ]


def _revoke_ssh_ingress_command(
    *,
    region: str,
    security_group_id: str,
    ssh_cidr: str,
) -> list[str]:
    permission = [
        {
            "IpProtocol": "tcp",
            "FromPort": 22,
            "ToPort": 22,
            "IpRanges": [{"CidrIp": ssh_cidr}],
        }
    ]
    return [
        "aws",
        "ec2",
        "revoke-security-group-ingress",
        "--region",
        region,
        "--group-id",
        security_group_id,
        "--ip-permissions",
        json.dumps(permission, separators=(",", ":")),
    ]


def _created_group_id(create_payload: dict[str, Any] | None) -> str | None:
    if not isinstance(create_payload, dict):
        return None
    group_id = create_payload.get("GroupId")
    return str(group_id) if group_id else None


def prepare_security_group_plan(
    *,
    root: Path,
    region: str,
    vpc_id: str | None,
    group_name: str,
    description: str,
    ssh_cidr: str | None,
    artifact_suffix: str,
    execute: bool,
    security_group_ack: str | None,
) -> tuple[dict[str, Any], Path]:
    resolved_vpc_id = vpc_id or _default_vpc(region)
    if execute:
        if security_group_ack != SECURITY_GROUP_ACK:
            raise RuntimeError(
                "refusing security-group mutation without exact --security-group-ack acknowledgement"
            )
        if not ssh_cidr:
            raise RuntimeError("refusing security-group mutation without --ssh-cidr")

    safe_suffix = _safe_id(artifact_suffix)
    dry_run = not execute
    create_command = _create_security_group_command(
        region=region,
        vpc_id=resolved_vpc_id,
        group_name=group_name,
        description=description,
        dry_run=dry_run,
    )
    create_result: dict[str, Any] | None = None
    create_payload: dict[str, Any] | None = None
    if dry_run:
        create_result = _dry_run_summary(_run(create_command))
    else:
        completed = _run(create_command)
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout).strip())
        create_payload = json.loads(completed.stdout)
        create_result = {"returncode": completed.returncode, "passed": True}

    security_group_id = _created_group_id(create_payload) or "SECURITY_GROUP_ID_AFTER_CREATE"
    ingress_command = (
        _authorize_ssh_ingress_command(
            region=region,
            security_group_id=security_group_id,
            ssh_cidr=ssh_cidr,
            dry_run=False,
        )
        if ssh_cidr
        else None
    )
    ingress_result: dict[str, Any] | None = None
    if execute and ingress_command:
        completed = _run(ingress_command)
        output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
        duplicate = "InvalidPermission.Duplicate" in output
        if completed.returncode != 0 and not duplicate:
            raise RuntimeError(output)
        ingress_result = {
            "returncode": completed.returncode,
            "duplicate": duplicate,
            "message": output,
            "passed": True,
        }

    cleanup_commands = {
        "revoke_ssh_ingress": (
            _revoke_ssh_ingress_command(
                region=region,
                security_group_id=security_group_id,
                ssh_cidr=ssh_cidr,
            )
            if ssh_cidr
            else None
        ),
        "delete_security_group": _delete_security_group_command(
            region=region,
            security_group_id=security_group_id,
        ),
    }
    payload: dict[str, Any] = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "region": region,
        "vpc_id": resolved_vpc_id,
        "group_name": group_name,
        "description": description,
        "ssh_cidr": ssh_cidr,
        "execute": execute,
        "security_group_ack_required_for_execute": SECURITY_GROUP_ACK,
        "create_security_group_command": create_command,
        "create_security_group_dry_run": create_result if dry_run else None,
        "create_security_group_result": create_result if execute else None,
        "created_security_group_id": None if security_group_id.endswith("AFTER_CREATE") else security_group_id,
        "authorize_ssh_ingress_command_template": ingress_command,
        "authorize_ssh_ingress_result": ingress_result,
        "cleanup_commands": cleanup_commands,
        "dedicated_security_group_planned": True,
        "fast_runtime_proven_for_every_possible_state": False,
        "status": (
            "dedicated_security_group_dryrun_authorized_not_runtime_evidence"
            if dry_run and create_result and create_result.get("authorized")
            else "dedicated_security_group_created_not_runtime_evidence"
            if execute and create_result and create_result.get("passed")
            else "dedicated_security_group_plan_incomplete"
        ),
    }
    payload["passed"] = (
        (dry_run and bool(create_result and create_result.get("authorized")))
        or (execute and bool(create_result and create_result.get("passed")))
    )

    output = (
        root
        / "results"
        / "processed"
        / f"aws_h48_fasttarget_security_group_{safe_suffix}.json"
    )
    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--vpc-id")
    parser.add_argument("--group-name", default=DEFAULT_GROUP_NAME)
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    parser.add_argument("--ssh-cidr")
    parser.add_argument("--artifact-suffix", default="aws_sg_dryrun")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--security-group-ack")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload, output = prepare_security_group_plan(
        root=args.root,
        region=args.region,
        vpc_id=args.vpc_id,
        group_name=args.group_name,
        description=args.description,
        ssh_cidr=args.ssh_cidr,
        artifact_suffix=args.artifact_suffix,
        execute=args.execute,
        security_group_ack=args.security_group_ack,
    )
    print(json.dumps({"output": str(output), "passed": payload["passed"], "status": payload["status"]}))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
