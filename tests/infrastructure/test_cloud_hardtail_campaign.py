from pathlib import Path
import hashlib
import json
import os
import sys
import tarfile
from types import SimpleNamespace

import scripts.experimental.provision_h48_fasttarget_aws as aws_provision
import scripts.experimental.prepare_h48_fasttarget_aws_security_group as aws_security_group
import scripts.experimental.run_h48_fasttarget_aws_proof as aws_proof
import scripts.experimental.cloud_hardtail_preflight as cloud_preflight
from scripts.experimental.evaluate_cloud_hardtail_campaign import (
    _evaluate_hardtail_batch_artifact,
    _evaluate_stronger_table_artifact,
    evaluate_campaign,
)
from scripts.experimental.cloud_hardtail_preflight import build_preflight_payload
from scripts.experimental.plan_cloud_hardtail_campaign import build_cloud_hardtail_plan
from scripts.experimental.provision_h48_fasttarget_aws import (
    _authorize_ssh_ingress_command,
    build_cloud_init,
    build_remote_command_template,
    instance_type_satisfies_requirements,
    provision_plan,
    summarize_instance_type,
)
from scripts.experimental.prepare_h48_fasttarget_aws_security_group import (
    _create_security_group_command,
    prepare_security_group_plan,
)
from scripts.experimental.run_h48_fasttarget_aws_proof import (
    _first_instance_id,
    _public_ip_from_describe,
    build_checkpoint_resume_command,
    build_remote_resume_command,
    build_remote_start_command,
)
from scripts.experimental.render_cloud_hardtail_runbook import build_cloud_hardtail_runbook
from scripts.experimental.run_h48_fasttarget_remote import build_remote_proof_steps, run_remote_fasttarget_proof
from scripts.experimental.run_cloud_hardtail_campaign import run_campaign
from scripts.experimental.run_cloud_hardtail_workload import fingerprint_json, run_workload
from scripts.experimental.validate_cloud_hardtail_archive import validate_archive
from rubik_optimal.tables.h48 import estimated_h48_table_size_bytes


def _write_scrambles(root: Path, distance: int, count: int) -> None:
    path = root / ".codex_external" / "nissy-core" / "benchmarks" / "scrambles" / f"scrambles-{distance}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join("R U F2" for _ in range(count)) + "\n", encoding="utf-8")


def _write_minimal_cloud_scripts(root: Path) -> None:
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for name in [
        "run_cloud_hardtail_campaign.py",
        "evaluate_cloud_hardtail_campaign.py",
        "generate_h48_oracle_contract.py",
        "thesis_audit.py",
    ]:
        (scripts / name).write_text("# test placeholder\n", encoding="utf-8")


def _fingerprinted_workload_result(plan: dict, workload: dict, **extra: object) -> dict:
    root = extra.pop("root", None)
    summaries = extra.get("artifact_summaries")
    if root is not None and isinstance(summaries, list):
        extra["artifact_integrity_algorithm"] = "sha256-size-v1"
        extra["artifact_integrity_scope"] = "test artifact bytes at workload completion"
        extra["artifact_summaries"] = [
            _test_artifact_summary(Path(root), summary)
            if isinstance(summary, dict) and "path" in summary and "sha256" not in summary
            else summary
            for summary in summaries
        ]
    payload = {
        "executed": True,
        "passed": True,
        "workload_id": workload["id"],
        "plan_fingerprint": fingerprint_json(plan),
        "workload_fingerprint": fingerprint_json(workload),
        "fingerprint_algorithm": "sha256-canonical-json-v1",
    }
    payload.update(extra)
    return payload


def _test_artifact_summary(root: Path, summary: dict) -> dict:
    path = root / str(summary["path"])
    payload = dict(summary)
    payload["size_bytes"] = path.stat().st_size
    payload["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return payload


def _successful_h48h10_fast_contract() -> dict:
    return {
        "passed": True,
        "solver": "h48h10",
        "all_state_exact_contract_supported": True,
        "empirical_fast_corpus_supported": True,
        "fast_runtime_proven_for_every_possible_state": True,
        "cloud_runtime_proof": {
            "passed": True,
            "all_required_workloads_passed": True,
            "all_required_artifact_integrity_passed": True,
            "cloud_runtime_evidence_passed": True,
            "artifact_integrity_required_workload_count": 7,
            "artifact_integrity_passed_workload_count": 7,
            "missing_or_failed_workload_count": 0,
        },
    }


def test_cloud_preflight_records_machine_gate_without_heavy_generation(tmp_path):
    _write_minimal_cloud_scripts(tmp_path)

    payload = build_preflight_payload(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        min_cpus=1,
        min_memory_gib=0.001,
        min_free_disk_gib=0.001,
        min_storage_gib=0.001,
        threads=1,
        require_external_assets=False,
        require_target_table=False,
    )

    assert payload["passed"] is True
    assert payload["solver"] == "h48h8"
    assert payload["require_target_table"] is False
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert payload["generation_safety"]["solver"] == "h48h8"

    impossible = build_preflight_payload(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        min_cpus=10**6,
        min_memory_gib=0.001,
        min_free_disk_gib=0.001,
        min_storage_gib=0.001,
        threads=1,
        require_external_assets=False,
        require_target_table=False,
    )
    assert impossible["passed"] is False
    assert any("cpu_count" in reason for reason in impossible["reasons"])


def test_cloud_preflight_enforces_target_h48_workspace(monkeypatch, tmp_path):
    _write_minimal_cloud_scripts(tmp_path)
    target_size = estimated_h48_table_size_bytes("h48h10")

    monkeypatch.setattr(
        cloud_preflight,
        "evaluate_h48_generation_safety",
        lambda **_kwargs: {
            "solver": "h48h10",
            "estimated_table_size_bytes": target_size,
            "safe_to_start": True,
            "reasons": [],
            "policy": {"disk_multiplier": 2.0},
            "machine": {
                "cpu_count": 32,
                "memory_bytes": 128 * 1024**3,
                "data_generated_h48_free_bytes": target_size,
                "load_average": (0.1, 0.1, 0.1),
            },
        },
    )

    payload = cloud_preflight.build_preflight_payload(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h10",
        min_cpus=1,
        min_memory_gib=0.001,
        min_free_disk_gib=0.001,
        min_storage_gib=0.001,
        threads=1,
        require_external_assets=False,
        require_target_table=False,
    )

    workspace = payload["target_h48_workspace"]
    assert payload["passed"] is False
    assert workspace["target_table_size_bytes"] == target_size
    assert workspace["required_workspace_bytes"] == target_size * 2
    assert workspace["available_workspace_bytes"] == target_size
    assert workspace["workspace_headroom_bytes"] == -target_size
    assert workspace["satisfies_workspace"] is False
    assert any("required H48 workspace" in reason for reason in payload["reasons"])


def test_cloud_preflight_splits_total_storage_from_free_workspace(monkeypatch, tmp_path):
    _write_minimal_cloud_scripts(tmp_path)
    target_size = estimated_h48_table_size_bytes("h48h10")
    free_workspace_bytes = int(target_size * 1.15) + 10 * 1024**3

    monkeypatch.setattr(
        cloud_preflight,
        "evaluate_h48_generation_safety",
        lambda **_kwargs: {
            "solver": "h48h10",
            "estimated_table_size_bytes": target_size,
            "safe_to_start": True,
            "reasons": [],
            "policy": {"disk_multiplier": 1.15},
            "machine": {
                "cpu_count": 16,
                "memory_bytes": 64 * 1024**3,
                "data_generated_h48_free_bytes": free_workspace_bytes,
                "load_average": (0.1, 0.1, 0.1),
            },
        },
    )
    monkeypatch.setattr(
        cloud_preflight.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(
            total=250 * 1024**3,
            used=250 * 1024**3 - free_workspace_bytes,
            free=free_workspace_bytes,
        ),
    )

    payload = cloud_preflight.build_preflight_payload(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h10",
        min_cpus=16,
        min_memory_gib=64.0,
        min_free_disk_gib=0.0,
        min_storage_gib=250.0,
        threads=16,
        require_external_assets=False,
        require_target_table=False,
    )

    assert payload["passed"] is True
    assert payload["min_storage_gib"] == 250.0
    assert payload["min_free_disk_gib"] == 0.0
    assert payload["machine"]["data_generated_h48_total_gib"] == 250.0
    assert payload["target_h48_workspace"]["satisfies_workspace"] is True
    assert payload["target_h48_workspace"]["available_workspace_bytes"] == free_workspace_bytes
    assert payload["reasons"] == []


def test_cloud_preflight_can_audit_assumed_nonaws_machine_shape(tmp_path):
    _write_minimal_cloud_scripts(tmp_path)

    payload = cloud_preflight.build_preflight_payload(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h10",
        min_cpus=16,
        min_memory_gib=64.0,
        min_free_disk_gib=0.0,
        min_storage_gib=250.0,
        threads=16,
        require_external_assets=False,
        require_target_table=False,
        disk_multiplier=1.15,
        assume_cpu_count=16,
        assume_memory_gib=64.0,
        assume_free_disk_gib=40.0,
        assume_total_storage_gib=250.0,
    )

    assert payload["passed"] is True
    assert payload["machine_source"] == "assumed"
    assert payload["assumed_machine_not_runtime_evidence"] is True
    assert payload["machine"]["cpu_count"] == 16
    assert payload["machine"]["memory_gib"] == 64.0
    assert payload["machine"]["data_generated_h48_total_gib"] == 250.0
    assert payload["target_h48_workspace"]["solver"] == "h48h10"
    assert payload["target_h48_workspace"]["satisfies_workspace"] is True
    assert payload["generation_safety"]["assumed_machine"] is True
    assert payload["generation_safety"]["safe_to_start"] is True
    assert payload["require_target_table"] is False
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert "not evidence" in payload["notes"]


def test_aws_fasttarget_provisioner_accepts_m6id_target_and_rejects_ebs_only():
    requirements = {
        "cpu_count": 16,
        "memory_gib": 64.0,
        "local_nvme_gib": 250.0,
    }
    m6id_summary = summarize_instance_type(
        {
            "InstanceType": "m6id.4xlarge",
            "VCpuInfo": {"DefaultVCpus": 16},
            "MemoryInfo": {"SizeInMiB": 65536},
            "InstanceStorageInfo": {
                "TotalSizeInGB": 950,
                "NvmeSupport": "required",
                "Disks": [{"SizeInGB": 950, "Count": 1, "Type": "ssd"}],
            },
            "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
        }
    )
    ebs_only_summary = summarize_instance_type(
        {
            "InstanceType": "m7i.4xlarge",
            "VCpuInfo": {"DefaultVCpus": 16},
            "MemoryInfo": {"SizeInMiB": 65536},
            "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
        }
    )

    ok, reasons = instance_type_satisfies_requirements(m6id_summary, requirements)
    assert ok is True
    assert reasons == []
    assert m6id_summary["local_nvme_gib"] == 950.0

    ok, reasons = instance_type_satisfies_requirements(ebs_only_summary, requirements)
    assert ok is False
    assert any("local NVMe" in reason for reason in reasons)


def test_aws_fasttarget_provisioner_writes_cloud_init_and_remote_command(tmp_path):
    public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKeyOnly h48-test"
    cloud_init = build_cloud_init(
        remote_root="/mnt/sgarbas-h48-proof",
        ssh_public_key=public_key,
    )
    runbook = tmp_path / "results" / "processed" / "cloud_hardtail_runbook_cloud_test.json"
    runbook.parent.mkdir(parents=True)
    runbook.write_text("{}", encoding="utf-8")

    command = build_remote_command_template(
        root=tmp_path,
        runbook_manifest_path=runbook,
        remote_root="/mnt/sgarbas-h48-proof",
        identity_file=tmp_path / "h48-key",
    )

    assert public_key in cloud_init
    assert "nvme-Amazon_EC2_NVMe_Instance_Storage" in cloud_init
    assert "mkfs.ext4 -F" in cloud_init
    assert "--remote-action detached-staged-proof" in command
    assert "--install-fetched-prerequisites" in command
    assert "--execute" in command


def test_aws_fasttarget_provisioner_builds_ssh_ingress_dryrun_command():
    command = _authorize_ssh_ingress_command(
        region="eu-west-1",
        security_group_id="sg-test",
        ssh_cidr="203.0.113.10/32",
        dry_run=True,
    )

    assert command[:4] == ["aws", "ec2", "authorize-security-group-ingress", "--region"]
    assert "--dry-run" in command
    permission = json.loads(command[command.index("--ip-permissions") + 1])
    assert permission[0]["IpProtocol"] == "tcp"
    assert permission[0]["FromPort"] == 22
    assert permission[0]["ToPort"] == 22
    assert permission[0]["IpRanges"][0]["CidrIp"] == "203.0.113.10/32"


def test_aws_fasttarget_provisioner_refuses_execute_without_ssh_cidr(tmp_path, monkeypatch):
    runbook = tmp_path / "results" / "processed" / "cloud_hardtail_runbook_cloud_test.json"
    runbook.parent.mkdir(parents=True)
    runbook.write_text(
        json.dumps(
            {
                "run_suffix": "cloud_test",
                "solver": "h48h10",
                "profile": "thesis",
                "seed": 2026,
                "recommended_minimum_cloud_machine": {
                    "cpu_count": 16,
                    "memory_gib": 64,
                    "local_nvme_gib": 250,
                    "h48_target_solver": "h48h10",
                },
            }
        ),
        encoding="utf-8",
    )
    public_key = tmp_path / "id_ed25519.pub"
    public_key.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest h48-test\n", encoding="utf-8")
    monkeypatch.setattr(
        aws_provision,
        "_describe_instance_type",
        lambda region, instance_type: {
            "InstanceType": instance_type,
            "VCpuInfo": {"DefaultVCpus": 16},
            "MemoryInfo": {"SizeInMiB": 65536},
            "InstanceStorageInfo": {
                "TotalSizeInGB": 950,
                "NvmeSupport": "required",
            },
            "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
        },
    )

    try:
        provision_plan(
            root=tmp_path,
            runbook_manifest_path=runbook,
            region="eu-west-1",
            instance_type="m6id.4xlarge",
            ami_id="ami-test",
            subnet_id="subnet-test",
            security_group_id="sg-test",
            root_volume_gib=80,
            remote_root="/mnt/sgarbas-h48-proof",
            ssh_cidr=None,
            ssh_public_key_file=public_key,
            ssh_private_key_file=None,
            artifact_suffix="test",
            execute=True,
            skip_aws_dry_run=True,
            paid_ec2_ack="I understand this starts a paid EC2 instance",
        )
    except RuntimeError as exc:
        assert "without --ssh-cidr" in str(exc)
    else:
        raise AssertionError("expected provision_plan to refuse paid launch without ssh_cidr")


def test_aws_fasttarget_security_group_builds_dedicated_create_command():
    command = _create_security_group_command(
        region="eu-west-1",
        vpc_id="vpc-test",
        group_name="sgarbas-h48-fasttarget-proof",
        description="Temporary SSH access",
        dry_run=True,
    )

    assert command[:4] == ["aws", "ec2", "create-security-group", "--region"]
    assert "--dry-run" in command
    assert command[command.index("--vpc-id") + 1] == "vpc-test"
    tag_spec = json.loads(command[command.index("--tag-specifications") + 1])
    assert tag_spec[0]["ResourceType"] == "security-group"
    assert {"Key": "Project", "Value": "sgarbas-h48-fasttarget"} in tag_spec[0]["Tags"]


def test_aws_helpers_block_cli_calls_by_default(monkeypatch):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)

    for module in [aws_provision, aws_security_group, aws_proof]:
        completed = module._run(["aws", "sts", "get-caller-identity"])
        assert completed.returncode == 126
        assert completed.stdout == ""
        assert "AWS CLI call blocked by default" in completed.stderr
        assert "AWS H48 fast-target helper is archived" in completed.stderr


def test_aws_fasttarget_security_group_dryrun_records_cleanup_templates(tmp_path, monkeypatch):
    monkeypatch.setattr(aws_security_group, "_default_vpc", lambda region: "vpc-test")

    class Completed:
        returncode = 255
        stdout = ""
        stderr = "An error occurred (DryRunOperation) when calling the CreateSecurityGroup operation"

    monkeypatch.setattr(aws_security_group, "_run", lambda command: Completed())

    payload, output = prepare_security_group_plan(
        root=tmp_path,
        region="eu-west-1",
        vpc_id=None,
        group_name="sgarbas-h48-fasttarget-proof",
        description="Temporary SSH access",
        ssh_cidr="203.0.113.10/32",
        artifact_suffix="sg_test",
        execute=False,
        security_group_ack=None,
    )

    assert output.exists()
    assert payload["passed"] is True
    assert payload["status"] == "dedicated_security_group_dryrun_authorized_not_runtime_evidence"
    assert payload["vpc_id"] == "vpc-test"
    assert payload["dedicated_security_group_planned"] is True
    assert "authorize-security-group-ingress" in payload["authorize_ssh_ingress_command_template"]
    assert payload["cleanup_commands"]["revoke_ssh_ingress"][2] == "revoke-security-group-ingress"
    assert payload["cleanup_commands"]["delete_security_group"][2] == "delete-security-group"


def test_aws_fasttarget_security_group_refuses_execute_without_ack(tmp_path, monkeypatch):
    monkeypatch.setattr(aws_security_group, "_default_vpc", lambda region: "vpc-test")

    try:
        prepare_security_group_plan(
            root=tmp_path,
            region="eu-west-1",
            vpc_id=None,
            group_name="sgarbas-h48-fasttarget-proof",
            description="Temporary SSH access",
            ssh_cidr="203.0.113.10/32",
            artifact_suffix="sg_test",
            execute=True,
            security_group_ack=None,
        )
    except RuntimeError as exc:
        assert "without exact --security-group-ack" in str(exc)
    else:
        raise AssertionError("expected security-group mutation guard to reject missing ack")


def test_aws_fasttarget_proof_runner_extracts_instance_id_and_public_ip():
    assert _first_instance_id({"Instances": [{"InstanceId": "i-direct"}]}) == "i-direct"
    assert (
        _first_instance_id(
            {"Reservations": [{"Instances": [{"InstanceId": "i-reservation"}]}]}
        )
        == "i-reservation"
    )
    assert (
        _public_ip_from_describe(
            {"Reservations": [{"Instances": [{"PublicIpAddress": "198.51.100.44"}]}]}
        )
        == "198.51.100.44"
    )


def test_aws_fasttarget_proof_runner_builds_remote_detached_start_command(tmp_path):
    runbook = tmp_path / "results" / "processed" / "cloud_hardtail_runbook_cloud_test.json"
    runbook.parent.mkdir(parents=True)
    runbook.write_text("{}", encoding="utf-8")

    command = build_remote_start_command(
        root=tmp_path,
        runbook_manifest_path=runbook,
        public_ip="198.51.100.44",
        identity_file=tmp_path / "id_ed25519",
        remote_root="/mnt/sgarbas-h48-proof",
    )

    assert command[0:2] == ["python", "scripts/run_h48_fasttarget_remote.py"]
    assert command[command.index("--host") + 1] == "ubuntu@198.51.100.44"
    assert command[command.index("--remote-action") + 1] == "detached-staged-proof"
    assert "--install-fetched-prerequisites" in command
    assert "--execute" in command
    assert command[command.index("--prerequisite-wait-timeout") + 1] == "43200.0"
    assert command[command.index("--prerequisite-poll-interval") + 1] == "60.0"
    assert command[command.index("--full-wait-timeout") + 1] == "28800.0"
    assert command[command.index("--full-poll-interval") + 1] == "60.0"


def test_aws_fasttarget_proof_runner_builds_checkpoint_resume_command(tmp_path):
    runbook = tmp_path / "results" / "processed" / "cloud_hardtail_runbook_cloud_test.json"
    runbook.parent.mkdir(parents=True)
    runbook.write_text("{}", encoding="utf-8")
    private_key = tmp_path / "id_ed25519"
    private_key.write_text("test key\n", encoding="utf-8")
    checkpoint = {
        "runbook_manifest_path": "results/processed/cloud_hardtail_runbook_cloud_test.json",
        "public_ip": "198.51.100.44",
        "remote_root": "/mnt/sgarbas-h48-proof",
    }

    command = build_remote_resume_command(
        root=tmp_path,
        checkpoint=checkpoint,
        identity_file=private_key,
    )

    assert command[0:2] == ["python", "scripts/run_h48_fasttarget_remote.py"]
    assert command[command.index("--host") + 1] == "ubuntu@198.51.100.44"
    assert command[command.index("--identity-file") + 1] == str(private_key)
    assert command[command.index("--remote-action") + 1] == "detached-staged-proof"
    assert command[command.index("--prerequisite-wait-timeout") + 1] == "43200.0"
    assert command[command.index("--full-wait-timeout") + 1] == "28800.0"


def test_aws_fasttarget_proof_runner_builds_local_checkpoint_resume_command(tmp_path):
    checkpoint = tmp_path / "results" / "processed" / "checkpoint.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("{}", encoding="utf-8")
    private_key = tmp_path / "id_ed25519"
    private_key.write_text("test key\n", encoding="utf-8")

    command = build_checkpoint_resume_command(
        root=tmp_path,
        checkpoint_path=checkpoint,
        ssh_private_key_file=private_key,
        artifact_suffix="resume_test",
        terminate_instance_on_success=True,
        cleanup_dedicated_security_group_on_success=True,
    )

    assert command[0:2] == ["python", "scripts/run_h48_fasttarget_aws_proof.py"]
    assert command[command.index("--resume-from-checkpoint") + 1] == (
        "results/processed/checkpoint.json"
    )
    assert command[command.index("--ssh-private-key-file") + 1] == str(private_key)
    assert command[command.index("--artifact-suffix") + 1] == "resume_test"
    assert command[command.index("--resume-remote-action") + 1] == "detached-staged-proof"
    assert command[command.index("--prerequisite-wait-timeout") + 1] == "43200.0"
    assert command[command.index("--full-wait-timeout") + 1] == "28800.0"
    assert "--execute" in command
    assert "--terminate-instance-on-success" in command
    assert "--cleanup-dedicated-security-group-on-success" in command


def test_aws_fasttarget_proof_runner_writes_dryrun_plan_without_launching(tmp_path, monkeypatch):
    runbook = tmp_path / "results" / "processed" / "cloud_hardtail_runbook_cloud_test.json"
    runbook.parent.mkdir(parents=True)
    runbook.write_text(
        json.dumps(
            {
                "run_suffix": "cloud_test",
                "solver": "h48h10",
                "profile": "thesis",
                "seed": 2026,
            }
        ),
        encoding="utf-8",
    )
    public_key = tmp_path / "id_ed25519.pub"
    public_key.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest h48-test\n", encoding="utf-8")
    private_key = tmp_path / "id_ed25519"
    private_key.write_text("test key\n", encoding="utf-8")
    provision_output = tmp_path / "results" / "processed" / "provision.json"
    provision_output.write_text("{}", encoding="utf-8")

    def fake_provision_plan(**kwargs):
        assert kwargs["execute"] is False
        return (
            {
                "runbook_manifest_path": "results/processed/cloud_hardtail_runbook_cloud_test.json",
                "run_suffix": "cloud_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "security_group_id": "sg-test",
                "status": "ec2_and_ssh_dryrun_authorized_not_runtime_evidence",
                "passed": True,
                "proof_host_launch_dry_run_authorized": True,
            },
            provision_output,
        )

    monkeypatch.setattr(aws_proof, "provision_plan", fake_provision_plan)
    args_for_script = SimpleNamespace(
        runbook=runbook,
        region="eu-west-1",
        instance_type="m6id.4xlarge",
        security_group_id="sg-test",
        ssh_cidr="203.0.113.10/32",
        ssh_public_key_file=public_key,
        ssh_private_key_file=private_key,
        remote_root="/mnt/sgarbas-h48-proof",
        artifact_suffix="dryrun_test",
        subnet_id=None,
        ami_id=None,
    )

    payload, output = aws_proof.run_aws_proof_plan(
        root=tmp_path,
        runbook_manifest_path=runbook,
        region="eu-west-1",
        instance_type="m6id.4xlarge",
        ami_id=None,
        subnet_id=None,
        security_group_id="sg-test",
        root_volume_gib=80,
        remote_root="/mnt/sgarbas-h48-proof",
        ssh_cidr="203.0.113.10/32",
        ssh_public_key_file=public_key,
        ssh_private_key_file=private_key,
        artifact_suffix="dryrun_test",
        execute=False,
        start_remote_proof=False,
        paid_ec2_ack=None,
        args_for_script=args_for_script,
    )

    assert output.exists()
    assert payload["passed"] is True
    assert payload["status"] == "aws_h48_fasttarget_proof_dryrun_planned_not_runtime_evidence"
    assert payload["provision_status"] == "ec2_and_ssh_dryrun_authorized_not_runtime_evidence"
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert payload["aws_wait_instance_status_command"][0:4] == [
        "aws",
        "ec2",
        "wait",
        "instance-status-ok",
    ]
    assert payload["aws_stop_instance_command"][2] == "stop-instances"
    assert payload["aws_terminate_instance_command"][2] == "terminate-instances"
    assert payload["remote_start_command"][payload["remote_start_command"].index("--host") + 1] == (
        "ubuntu@PUBLIC_IP_AFTER_LAUNCH"
    )
    execute_script = tmp_path / payload["execute_script_path"]
    script_text = execute_script.read_text(encoding="utf-8")
    assert "PAID_EC2_ACK" in script_text
    assert "SSH_CIDR" in script_text
    assert "--start-remote-proof" in script_text
    assert "--prerequisite-wait-timeout 43200.0" in script_text
    assert "--full-wait-timeout 28800.0" in script_text
    assert payload["aws_checkpoint_resume_command_template"][
        payload["aws_checkpoint_resume_command_template"].index("--resume-from-checkpoint") + 1
    ] == "${CHECKPOINT_PATH}"
    assert "--execute" in payload["aws_checkpoint_resume_command_template"]
    resume_script = tmp_path / payload["checkpoint_resume_script_path"]
    resume_script_text = resume_script.read_text(encoding="utf-8")
    assert "CHECKPOINT_PATH" in resume_script_text
    assert "--resume-from-checkpoint \"${CHECKPOINT_PATH}\"" in resume_script_text
    assert "--prerequisite-wait-timeout 43200.0" in resume_script_text
    assert "--full-wait-timeout 28800.0" in resume_script_text


def test_aws_fasttarget_proof_runner_plans_checkpoint_resume_without_launching(
    tmp_path,
    monkeypatch,
):
    runbook = tmp_path / "results" / "processed" / "cloud_hardtail_runbook_cloud_test.json"
    runbook.parent.mkdir(parents=True)
    runbook.write_text("{}", encoding="utf-8")
    private_key = tmp_path / "id_ed25519"
    private_key.write_text("test key\n", encoding="utf-8")
    checkpoint = tmp_path / "results" / "processed" / "checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "checkpoint_kind": "pre_remote_detached_proof",
                "status": "aws_h48_fasttarget_instance_ready_pre_remote_checkpoint_not_runtime_evidence",
                "runbook_manifest_path": "results/processed/cloud_hardtail_runbook_cloud_test.json",
                "run_suffix": "cloud_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "region": "eu-west-1",
                "instance_id": "i-test",
                "public_ip": "198.51.100.44",
                "remote_root": "/mnt/sgarbas-h48-proof",
                "remote_start_command": [
                    "python",
                    "scripts/run_h48_fasttarget_remote.py",
                    "--identity-file",
                    str(private_key),
                ],
                "terminate_instance_on_success": True,
                "cleanup_dedicated_security_group_on_success": True,
                "dedicated_security_group_cleanup_commands": {
                    "revoke_ssh_ingress": ["aws", "ec2", "revoke-security-group-ingress"],
                    "delete_security_group": ["aws", "ec2", "delete-security-group"],
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(aws_proof, "_run", lambda command: (_ for _ in ()).throw(AssertionError(command)))
    args_for_script = SimpleNamespace()

    payload, output = aws_proof.run_aws_checkpoint_resume_plan(
        root=tmp_path,
        checkpoint_path=checkpoint,
        ssh_private_key_file=None,
        artifact_suffix="checkpoint_resume_dryrun",
        execute=False,
        args_for_script=args_for_script,
    )

    assert output.exists()
    assert payload["passed"] is True
    assert payload["status"] == "aws_h48_fasttarget_checkpoint_resume_dryrun_planned_not_runtime_evidence"
    assert payload["resume_from_checkpoint"] is True
    assert payload["checkpoint_path"] == "results/processed/checkpoint.json"
    assert payload["instance_id"] == "i-test"
    assert payload["public_ip"] == "198.51.100.44"
    assert payload["remote_resume_command"][payload["remote_resume_command"].index("--host") + 1] == (
        "ubuntu@198.51.100.44"
    )
    assert payload["remote_resume_command"][
        payload["remote_resume_command"].index("--remote-action") + 1
    ] == "detached-staged-proof"
    assert payload["remote_resume_command"][
        payload["remote_resume_command"].index("--prerequisite-wait-timeout") + 1
    ] == "43200.0"
    assert "terminate-instances" in payload["aws_terminate_instance_command"]
    assert payload["terminate_instance_on_success"] is True
    assert payload["cleanup_dedicated_security_group_on_success"] is True


def test_aws_fasttarget_proof_runner_resumes_checkpoint_and_cleans_up_success(
    tmp_path,
    monkeypatch,
):
    runbook = tmp_path / "results" / "processed" / "cloud_hardtail_runbook_cloud_test.json"
    runbook.parent.mkdir(parents=True)
    runbook.write_text("{}", encoding="utf-8")
    private_key = tmp_path / "id_ed25519"
    private_key.write_text("test key\n", encoding="utf-8")
    checkpoint = tmp_path / "results" / "processed" / "checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "checkpoint_kind": "pre_remote_detached_proof",
                "status": "aws_h48_fasttarget_instance_ready_pre_remote_checkpoint_not_runtime_evidence",
                "runbook_manifest_path": "results/processed/cloud_hardtail_runbook_cloud_test.json",
                "run_suffix": "cloud_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "region": "eu-west-1",
                "instance_id": "i-test",
                "public_ip": "198.51.100.44",
                "remote_root": "/mnt/sgarbas-h48-proof",
                "remote_start_command": [
                    "python",
                    "scripts/run_h48_fasttarget_remote.py",
                    "--identity-file",
                    str(private_key),
                ],
                "terminate_instance_on_success": True,
                "cleanup_dedicated_security_group_on_success": True,
                "dedicated_security_group_cleanup_commands": {
                    "revoke_ssh_ingress": ["aws", "ec2", "revoke-security-group-ingress"],
                    "delete_security_group": ["aws", "ec2", "delete-security-group"],
                },
            }
        ),
        encoding="utf-8",
    )

    class Completed:
        def __init__(self, stdout="", stderr="", returncode=0):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    commands = []

    def fake_run(command):
        commands.append(command)
        if command[0:2] == ["python", "scripts/run_h48_fasttarget_remote.py"]:
            return Completed(
                stdout=json.dumps(
                    {
                        "passed": True,
                        "fast_runtime_proven_for_every_possible_state": True,
                    }
                )
            )
        if command[0:3] == ["aws", "ec2", "terminate-instances"]:
            return Completed(stdout="terminating")
        if command[0:4] == ["aws", "ec2", "wait", "instance-terminated"]:
            return Completed()
        if command[0:3] in [
            ["aws", "ec2", "revoke-security-group-ingress"],
            ["aws", "ec2", "delete-security-group"],
        ]:
            return Completed()
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(aws_proof, "_run", fake_run)
    args_for_script = SimpleNamespace()

    payload, output = aws_proof.run_aws_checkpoint_resume_plan(
        root=tmp_path,
        checkpoint_path=checkpoint,
        ssh_private_key_file=None,
        artifact_suffix="checkpoint_resume_success",
        execute=True,
        args_for_script=args_for_script,
    )

    assert output.exists()
    assert payload["passed"] is True
    assert payload["status"] == "aws_h48_fasttarget_checkpoint_resume_finished"
    assert payload["fast_runtime_proven_for_every_possible_state"] is True
    assert payload["cleanup_outcome"] == "success"
    assert payload["cleanup_attempted"] is True
    assert payload["cleanup_passed"] is True
    assert payload["instance_cleanup_action"] == "terminate"
    assert payload["dedicated_security_group_cleanup_requested"] is True
    command_names = [
        command[2] if command[0:2] == ["aws", "ec2"] else command[1]
        for command in commands
    ]
    assert command_names == [
        "scripts/run_h48_fasttarget_remote.py",
        "terminate-instances",
        "wait",
        "revoke-security-group-ingress",
        "delete-security-group",
    ]


def test_aws_fasttarget_proof_runner_can_create_dedicated_sg_before_paid_launch(
    tmp_path,
    monkeypatch,
):
    runbook = tmp_path / "results" / "processed" / "cloud_hardtail_runbook_cloud_test.json"
    runbook.parent.mkdir(parents=True)
    runbook.write_text(
        json.dumps(
            {
                "run_suffix": "cloud_test",
                "solver": "h48h10",
                "profile": "thesis",
                "seed": 2026,
            }
        ),
        encoding="utf-8",
    )
    public_key = tmp_path / "id_ed25519.pub"
    public_key.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest h48-test\n", encoding="utf-8")
    private_key = tmp_path / "id_ed25519"
    private_key.write_text("test key\n", encoding="utf-8")
    sg_output = tmp_path / "results" / "processed" / "sg.json"
    provision_output = tmp_path / "results" / "processed" / "provision.json"
    sg_output.parent.mkdir(parents=True, exist_ok=True)
    sg_output.write_text("{}", encoding="utf-8")
    provision_output.write_text("{}", encoding="utf-8")

    calls = []

    def fake_prepare_security_group_plan(**kwargs):
        calls.append(("sg", kwargs))
        assert kwargs["execute"] is True
        assert kwargs["security_group_ack"] == aws_security_group.SECURITY_GROUP_ACK
        return (
            {
                "created_security_group_id": "sg-created",
                "status": "dedicated_security_group_created_not_runtime_evidence",
                "passed": True,
                "cleanup_commands": {"delete_security_group": ["aws", "ec2", "delete-security-group"]},
            },
            sg_output,
        )

    def fake_provision_plan(**kwargs):
        calls.append(("provision", kwargs))
        assert kwargs["execute"] is True
        assert kwargs["security_group_id"] == "sg-created"
        return (
            {
                "runbook_manifest_path": "results/processed/cloud_hardtail_runbook_cloud_test.json",
                "run_suffix": "cloud_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "security_group_id": "sg-created",
                "status": "ec2_instance_launched_not_runtime_evidence",
                "passed": True,
                "proof_host_launch_dry_run_authorized": False,
                "launch_result": {"Instances": [{"InstanceId": "i-test"}]},
            },
            provision_output,
        )

    class Completed:
        def __init__(self, stdout="", stderr="", returncode=0):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    def fake_run(command):
        if command[0:4] == ["aws", "ec2", "wait", "instance-status-ok"]:
            return Completed()
        if command[0:3] == ["aws", "ec2", "describe-instances"]:
            return Completed(
                stdout=json.dumps(
                    {"Reservations": [{"Instances": [{"PublicIpAddress": "198.51.100.44"}]}]}
                )
            )
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(aws_proof, "prepare_security_group_plan", fake_prepare_security_group_plan)
    monkeypatch.setattr(aws_proof, "provision_plan", fake_provision_plan)
    monkeypatch.setattr(aws_proof, "_run", fake_run)
    args_for_script = SimpleNamespace(
        runbook=runbook,
        region="eu-west-1",
        instance_type="m6id.4xlarge",
        security_group_id=None,
        ssh_cidr="203.0.113.10/32",
        ssh_public_key_file=public_key,
        ssh_private_key_file=private_key,
        remote_root="/mnt/sgarbas-h48-proof",
        artifact_suffix="paid_test",
        subnet_id=None,
        ami_id=None,
        create_dedicated_security_group=True,
        security_group_ack=aws_security_group.SECURITY_GROUP_ACK,
        security_group_name="sgarbas-h48-fasttarget-proof",
        security_group_description="Temporary SSH access",
        vpc_id=None,
    )

    payload, output = aws_proof.run_aws_proof_plan(
        root=tmp_path,
        runbook_manifest_path=runbook,
        region="eu-west-1",
        instance_type="m6id.4xlarge",
        ami_id=None,
        subnet_id=None,
        security_group_id=None,
        root_volume_gib=80,
        remote_root="/mnt/sgarbas-h48-proof",
        ssh_cidr="203.0.113.10/32",
        ssh_public_key_file=public_key,
        ssh_private_key_file=private_key,
        artifact_suffix="paid_test",
        execute=True,
        start_remote_proof=False,
        paid_ec2_ack="I understand this starts a paid EC2 instance",
        args_for_script=args_for_script,
    )

    assert output.exists()
    assert [name for name, _ in calls] == ["sg", "provision"]
    assert payload["passed"] is True
    assert payload["status"] == "aws_h48_fasttarget_instance_ready_not_runtime_evidence"
    assert payload["security_group_id"] == "sg-created"
    assert payload["requested_security_group_id"] is None
    assert payload["dedicated_security_group_created_id"] == "sg-created"
    assert payload["dedicated_security_group_artifact_path"].endswith("sg.json")
    assert payload["create_dedicated_security_group_for_execute"] is True
    assert payload["execute_script_uses_dedicated_security_group"] is True
    execute_script = tmp_path / payload["execute_script_path"]
    script_text = execute_script.read_text(encoding="utf-8")
    assert "prepare_h48_fasttarget_aws_security_group.py" in script_text
    assert "SECURITY_GROUP_ACK" in script_text
    assert "--security-group-id \"${SECURITY_GROUP_ID}\"" in script_text


def test_aws_fasttarget_proof_runner_can_cleanup_paid_success(
    tmp_path,
    monkeypatch,
):
    runbook = tmp_path / "results" / "processed" / "cloud_hardtail_runbook_cloud_test.json"
    runbook.parent.mkdir(parents=True)
    runbook.write_text(
        json.dumps(
            {
                "run_suffix": "cloud_test",
                "solver": "h48h10",
                "profile": "thesis",
                "seed": 2026,
            }
        ),
        encoding="utf-8",
    )
    public_key = tmp_path / "id_ed25519.pub"
    public_key.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest h48-test\n", encoding="utf-8")
    private_key = tmp_path / "id_ed25519"
    private_key.write_text("test key\n", encoding="utf-8")
    sg_output = tmp_path / "results" / "processed" / "sg.json"
    provision_output = tmp_path / "results" / "processed" / "provision.json"
    sg_output.parent.mkdir(parents=True, exist_ok=True)
    sg_output.write_text("{}", encoding="utf-8")
    provision_output.write_text("{}", encoding="utf-8")

    def fake_prepare_security_group_plan(**kwargs):
        return (
            {
                "created_security_group_id": "sg-created",
                "status": "dedicated_security_group_created_not_runtime_evidence",
                "passed": True,
                "cleanup_commands": {
                    "revoke_ssh_ingress": ["aws", "ec2", "revoke-security-group-ingress"],
                    "delete_security_group": ["aws", "ec2", "delete-security-group"],
                },
            },
            sg_output,
        )

    def fake_provision_plan(**kwargs):
        return (
            {
                "runbook_manifest_path": "results/processed/cloud_hardtail_runbook_cloud_test.json",
                "run_suffix": "cloud_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "security_group_id": "sg-created",
                "status": "ec2_instance_launched_not_runtime_evidence",
                "passed": True,
                "proof_host_launch_dry_run_authorized": False,
                "launch_result": {"Instances": [{"InstanceId": "i-test"}]},
            },
            provision_output,
        )

    class Completed:
        def __init__(self, stdout="", stderr="", returncode=0):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    commands = []
    events = []
    writes = []
    original_write_json = aws_proof.write_json

    def recording_write_json(path, payload):
        events.append(("write", payload.get("status")))
        writes.append(dict(payload))
        return original_write_json(path, payload)

    def fake_run(command):
        commands.append(command)
        if command[0:4] == ["aws", "ec2", "wait", "instance-status-ok"]:
            return Completed()
        if command[0:3] == ["aws", "ec2", "describe-instances"]:
            return Completed(
                stdout=json.dumps(
                    {"Reservations": [{"Instances": [{"PublicIpAddress": "198.51.100.44"}]}]}
                )
            )
        if command[0:2] == ["python", "scripts/run_h48_fasttarget_remote.py"]:
            events.append(("run", "remote_start_command"))
            return Completed(stdout='{"passed": true}')
        if command[0:3] == ["aws", "ec2", "terminate-instances"]:
            return Completed(stdout="terminating")
        if command[0:4] == ["aws", "ec2", "wait", "instance-terminated"]:
            return Completed()
        if command[0:3] in [
            ["aws", "ec2", "revoke-security-group-ingress"],
            ["aws", "ec2", "delete-security-group"],
        ]:
            return Completed()
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(aws_proof, "prepare_security_group_plan", fake_prepare_security_group_plan)
    monkeypatch.setattr(aws_proof, "provision_plan", fake_provision_plan)
    monkeypatch.setattr(aws_proof, "_run", fake_run)
    monkeypatch.setattr(aws_proof, "write_json", recording_write_json)
    args_for_script = SimpleNamespace(
        runbook=runbook,
        region="eu-west-1",
        instance_type="m6id.4xlarge",
        security_group_id=None,
        ssh_cidr="203.0.113.10/32",
        ssh_public_key_file=public_key,
        ssh_private_key_file=private_key,
        remote_root="/mnt/sgarbas-h48-proof",
        artifact_suffix="paid_cleanup_success",
        subnet_id=None,
        ami_id=None,
        create_dedicated_security_group=True,
        security_group_ack=aws_security_group.SECURITY_GROUP_ACK,
        security_group_name="sgarbas-h48-fasttarget-proof",
        security_group_description="Temporary SSH access",
        vpc_id=None,
        terminate_instance_on_success=True,
        cleanup_dedicated_security_group_on_success=True,
    )

    payload, output = aws_proof.run_aws_proof_plan(
        root=tmp_path,
        runbook_manifest_path=runbook,
        region="eu-west-1",
        instance_type="m6id.4xlarge",
        ami_id=None,
        subnet_id=None,
        security_group_id=None,
        root_volume_gib=80,
        remote_root="/mnt/sgarbas-h48-proof",
        ssh_cidr="203.0.113.10/32",
        ssh_public_key_file=public_key,
        ssh_private_key_file=private_key,
        artifact_suffix="paid_cleanup_success",
        execute=True,
        start_remote_proof=True,
        paid_ec2_ack="I understand this starts a paid EC2 instance",
        args_for_script=args_for_script,
    )

    assert output.exists()
    assert payload["passed"] is True
    assert payload["pre_remote_checkpoint_written"] is True
    assert payload["pre_remote_checkpoint_status"] == (
        "aws_h48_fasttarget_instance_ready_pre_remote_checkpoint_not_runtime_evidence"
    )
    assert payload["checkpoint_written_before_remote_start"] is True
    assert payload["cleanup_outcome"] == "success"
    assert payload["cleanup_attempted"] is True
    assert payload["cleanup_passed"] is True
    assert payload["instance_cleanup_action"] == "terminate"
    assert payload["instance_cleanup_result"]["passed"] is True
    assert payload["instance_cleanup_wait_result"]["passed"] is True
    assert payload["dedicated_security_group_cleanup_requested"] is True
    assert payload["dedicated_security_group_cleanup_result"]["passed"] is True
    assert [event for event in events if event[0] in {"write", "run"}][0:2] == [
        ("write", "aws_h48_fasttarget_instance_ready_pre_remote_checkpoint_not_runtime_evidence"),
        ("run", "remote_start_command"),
    ]
    assert events[-1] == (
        "write",
        "aws_h48_fasttarget_detached_proof_started_not_runtime_evidence",
    )
    assert writes[0]["checkpoint_kind"] == "pre_remote_detached_proof"
    assert writes[0]["instance_id"] == "i-test"
    assert writes[0]["public_ip"] == "198.51.100.44"
    assert "terminate-instances" in writes[0]["aws_terminate_instance_command"]
    assert writes[0]["aws_checkpoint_resume_command"][
        writes[0]["aws_checkpoint_resume_command"].index("--resume-from-checkpoint") + 1
    ].endswith("aws_h48_fasttarget_proof_run_cloud_test_paid_cleanup_success.json")
    assert "--terminate-instance-on-success" in writes[0]["aws_checkpoint_resume_command"]
    assert (
        "--cleanup-dedicated-security-group-on-success"
        in writes[0]["aws_checkpoint_resume_command"]
    )
    assert writes[0]["dedicated_security_group_created_id"] == "sg-created"
    command_names = [command[2] if command[0:2] == ["aws", "ec2"] else command[1] for command in commands]
    assert command_names == [
        "wait",
        "describe-instances",
        "scripts/run_h48_fasttarget_remote.py",
        "terminate-instances",
        "wait",
        "revoke-security-group-ingress",
        "delete-security-group",
    ]
    script_text = (tmp_path / payload["execute_script_path"]).read_text(encoding="utf-8")
    assert "--terminate-instance-on-success" in script_text
    assert "--cleanup-dedicated-security-group-on-success" in script_text


def test_aws_fasttarget_proof_runner_writes_artifact_and_cleans_up_on_remote_failure(
    tmp_path,
    monkeypatch,
):
    runbook = tmp_path / "results" / "processed" / "cloud_hardtail_runbook_cloud_test.json"
    runbook.parent.mkdir(parents=True)
    runbook.write_text(
        json.dumps(
            {
                "run_suffix": "cloud_test",
                "solver": "h48h10",
                "profile": "thesis",
                "seed": 2026,
            }
        ),
        encoding="utf-8",
    )
    private_key = tmp_path / "id_ed25519"
    private_key.write_text("test key\n", encoding="utf-8")
    sg_output = tmp_path / "results" / "processed" / "sg.json"
    provision_output = tmp_path / "results" / "processed" / "provision.json"
    sg_output.parent.mkdir(parents=True, exist_ok=True)
    sg_output.write_text("{}", encoding="utf-8")
    provision_output.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        aws_proof,
        "prepare_security_group_plan",
        lambda **kwargs: (
            {
                "created_security_group_id": "sg-created",
                "status": "dedicated_security_group_created_not_runtime_evidence",
                "passed": True,
                "cleanup_commands": {
                    "revoke_ssh_ingress": ["aws", "ec2", "revoke-security-group-ingress"],
                    "delete_security_group": ["aws", "ec2", "delete-security-group"],
                },
            },
            sg_output,
        ),
    )
    monkeypatch.setattr(
        aws_proof,
        "provision_plan",
        lambda **kwargs: (
            {
                "runbook_manifest_path": "results/processed/cloud_hardtail_runbook_cloud_test.json",
                "run_suffix": "cloud_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "security_group_id": "sg-created",
                "status": "ec2_instance_launched_not_runtime_evidence",
                "passed": True,
                "proof_host_launch_dry_run_authorized": False,
                "launch_result": {"Instances": [{"InstanceId": "i-test"}]},
            },
            provision_output,
        ),
    )

    class Completed:
        def __init__(self, stdout="", stderr="", returncode=0):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    def fake_run(command):
        if command[0:4] == ["aws", "ec2", "wait", "instance-status-ok"]:
            return Completed()
        if command[0:3] == ["aws", "ec2", "describe-instances"]:
            return Completed(
                stdout=json.dumps(
                    {"Reservations": [{"Instances": [{"PublicIpAddress": "198.51.100.44"}]}]}
                )
            )
        if command[0:2] == ["python", "scripts/run_h48_fasttarget_remote.py"]:
            return Completed(stderr="remote proof failed", returncode=17)
        if command[0:3] == ["aws", "ec2", "terminate-instances"]:
            return Completed(stdout="terminating")
        if command[0:4] == ["aws", "ec2", "wait", "instance-terminated"]:
            return Completed()
        if command[0:3] in [
            ["aws", "ec2", "revoke-security-group-ingress"],
            ["aws", "ec2", "delete-security-group"],
        ]:
            return Completed()
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(aws_proof, "_run", fake_run)
    args_for_script = SimpleNamespace(
        runbook=runbook,
        region="eu-west-1",
        instance_type="m6id.4xlarge",
        security_group_id=None,
        ssh_cidr="203.0.113.10/32",
        ssh_public_key_file=None,
        ssh_private_key_file=private_key,
        remote_root="/mnt/sgarbas-h48-proof",
        artifact_suffix="paid_cleanup_failure",
        subnet_id=None,
        ami_id=None,
        create_dedicated_security_group=True,
        security_group_ack=aws_security_group.SECURITY_GROUP_ACK,
        security_group_name="sgarbas-h48-fasttarget-proof",
        security_group_description="Temporary SSH access",
        vpc_id=None,
        terminate_instance_on_failure=True,
        cleanup_dedicated_security_group_on_failure=True,
    )

    payload, output = aws_proof.run_aws_proof_plan(
        root=tmp_path,
        runbook_manifest_path=runbook,
        region="eu-west-1",
        instance_type="m6id.4xlarge",
        ami_id=None,
        subnet_id=None,
        security_group_id=None,
        root_volume_gib=80,
        remote_root="/mnt/sgarbas-h48-proof",
        ssh_cidr="203.0.113.10/32",
        ssh_public_key_file=None,
        ssh_private_key_file=private_key,
        artifact_suffix="paid_cleanup_failure",
        execute=True,
        start_remote_proof=True,
        paid_ec2_ack="I understand this starts a paid EC2 instance",
        args_for_script=args_for_script,
    )

    assert output.exists()
    assert payload["passed"] is False
    assert payload["status"] == "aws_h48_fasttarget_detached_proof_started_not_runtime_evidence"
    assert payload["execution_error"] == "remote proof failed"
    assert payload["cleanup_outcome"] == "failure"
    assert payload["cleanup_attempted"] is True
    assert payload["cleanup_passed"] is True
    assert payload["instance_cleanup_action"] == "terminate"
    assert payload["dedicated_security_group_cleanup_result"]["passed"] is True


def test_cloud_campaign_evaluator_requires_stronger_table_full_checksum():
    plan = {
        "solver": "h48h8",
        "workloads": [{"kind": "h48_stronger_table_generation_and_certification"}],
    }
    payload = {
        "passed": True,
        "target_solver": "h48h8",
        "target_estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h8"),
        "post_campaign_target_trusted_table": True,
        "post_campaign_full_checksum_valid": False,
        "status": "generated_and_certified",
    }

    assert _evaluate_stronger_table_artifact(payload, plan=plan) is False

    payload["post_campaign_full_checksum_valid"] = True
    assert _evaluate_stronger_table_artifact(payload, plan=plan) is True


def test_cloud_hardtail_plan_shards_public_distance20_with_bounded_proof(tmp_path):
    _write_scrambles(tmp_path, distance=20, count=5)

    payload = build_cloud_hardtail_plan(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h7",
        python_executable="python",
        distance=20,
        start_offset=0,
        end_offset=5,
        shard_size=2,
        threads=16,
        runtime_target_seconds=300.0,
        h48_timeout_seconds=600.0,
        prepass_timeout_seconds=60.0,
        fallback_timeout_seconds=900.0,
        h48_upper_bound_proof_timeout_seconds=600.0,
        h48_upper_bound_proof_max_gap=4,
        rubikoptimal_timeout_seconds=900.0,
        symmetry_timeout_seconds=300.0,
        symmetry_max_concurrency=4,
        h48_stronger_target_solver="h48h8",
        h48_table_generation_timeout_seconds=21600.0,
        artifact_suffix="cloud_test",
    )

    shard_workloads = [
        workload
        for workload in payload["workloads"]
        if workload["kind"] == "public_known_distance_hardtail_sweep"
    ]
    assert [(row["command_args"][row["command_args"].index("--start-offset") + 1], row["command_args"][row["command_args"].index("--end-offset") + 1]) for row in shard_workloads] == [
        ("0", "2"),
        ("2", "4"),
        ("4", "5"),
    ]
    first_command = shard_workloads[0]["command_args"]
    assert "--h48-upper-bound-proof-timeout" in first_command
    assert first_command[first_command.index("--h48-upper-bound-proof-timeout") + 1] == "600.0"
    assert "--h48-upper-bound-proof-max-gap" in first_command
    assert "--symmetry-order-by-h48-lower-bound" in first_command
    assert "--dry-run" not in first_command
    assert shard_workloads[0]["environment"] == {
        "RUBIK_OPTIMAL_H48_THREADS": "16",
        "RUBIK_OPTIMAL_THREADS": "16",
    }
    assert "env RUBIK_OPTIMAL_H48_THREADS=16 RUBIK_OPTIMAL_THREADS=16 python" in shard_workloads[0]["shell_command"]
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert payload["all_state_fast_oracle_goal_satisfied_by_plan"] is False


def test_cloud_hardtail_plan_can_batch_public_distance20_workloads(tmp_path):
    _write_scrambles(tmp_path, distance=20, count=25)

    payload = build_cloud_hardtail_plan(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h7",
        python_executable="python",
        distance=20,
        start_offset=0,
        end_offset=25,
        shard_size=10,
        threads=16,
        runtime_target_seconds=300.0,
        h48_timeout_seconds=600.0,
        prepass_timeout_seconds=60.0,
        fallback_timeout_seconds=900.0,
        h48_upper_bound_proof_timeout_seconds=600.0,
        h48_upper_bound_proof_max_gap=4,
        rubikoptimal_timeout_seconds=900.0,
        symmetry_timeout_seconds=300.0,
        symmetry_max_concurrency=4,
        h48_stronger_target_solver="h48h8",
        h48_table_generation_timeout_seconds=21600.0,
        artifact_suffix="cloud_batch",
        hardtail_execution_mode="batch",
    )

    hardtail_workloads = [
        workload
        for workload in payload["workloads"]
        if workload["kind"] == "public_known_distance_hardtail_batch"
    ]
    assert len(hardtail_workloads) == 3
    assert payload["hardtail_execution_mode"] == "batch"
    assert payload["hardtail_state_count"] == 25
    assert payload["hardtail_process_count"] == 3
    assert payload["hardtail_process_launch_reduction_factor"] == 8.333333
    first_command = hardtail_workloads[0]["command_args"]
    assert "scripts/run_universal_oracle_cli.py" in first_command
    assert "--benchmark-limit-per-distance" in first_command
    assert first_command[first_command.index("--benchmark-limit-per-distance") + 1] == "10"
    assert first_command[first_command.index("--benchmark-offset-per-distance") + 1] == "0"
    assert "--no-certificate-cache" in first_command
    assert "--command-timeout" in first_command
    assert hardtail_workloads[-1]["command_args"][
        hardtail_workloads[-1]["command_args"].index("--benchmark-limit-per-distance") + 1
    ] == "5"
    assert hardtail_workloads[0]["expected_artifacts"] == [
        "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_cloud_batch_d20_o0_10.json"
    ]


def test_cloud_hardtail_plan_can_target_h48h8_hardtail_after_generation(tmp_path):
    _write_scrambles(tmp_path, distance=20, count=12)

    payload = build_cloud_hardtail_plan(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        python_executable="python",
        distance=20,
        start_offset=0,
        end_offset=12,
        shard_size=6,
        threads=16,
        runtime_target_seconds=300.0,
        h48_timeout_seconds=300.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=600.0,
        h48_upper_bound_proof_timeout_seconds=300.0,
        h48_upper_bound_proof_max_gap=3,
        rubikoptimal_timeout_seconds=600.0,
        symmetry_timeout_seconds=180.0,
        symmetry_max_concurrency=4,
        h48_stronger_target_solver="h48h8",
        h48_table_generation_timeout_seconds=21600.0,
        artifact_suffix="cloud_h48h8",
        hardtail_execution_mode="batch",
    )

    assert payload["solver"] == "h48h8"
    assert payload["hardtail_uses_stronger_target_solver"] is True
    assert payload["hardtail_prerequisite_workload_ids"] == ["stronger_table_h48h8"]
    assert payload["requires_table_distribution_before_hardtail"] is True
    assert payload["workloads"][0]["id"] == "stronger_table_h48h8"
    assert "results/processed/h48_metadata_seed_2026_thesis_h48h8.json" in payload["workloads"][0]["expected_artifacts"]
    hardtail_workloads = [
        workload
        for workload in payload["workloads"]
        if workload["kind"] == "public_known_distance_hardtail_batch"
    ]
    assert len(hardtail_workloads) == 2
    first_command = hardtail_workloads[0]["command_args"]
    assert first_command[first_command.index("--solver") + 1] == "h48h8"
    assert hardtail_workloads[0]["depends_on_workload_ids"] == ["stronger_table_h48h8"]
    assert hardtail_workloads[0]["expected_artifacts"] == [
        "results/processed/universal_oracle_cli_seed_2026_thesis_h48h8_cloud_h48h8_d20_o0_6.json"
    ]
    contract_postprocess = next(
        workload
        for workload in payload["workloads"]
        if workload["kind"] == "postprocess_and_audit"
        and "scripts/generate_h48_oracle_contract.py" in workload["command_args"]
    )
    assert contract_postprocess["command_args"][contract_postprocess["command_args"].index("--solver") + 1] == "h48h8"
    assert contract_postprocess["expected_artifacts"] == [
        "results/processed/h48_oracle_contract_seed_2026_thesis_h48h8.json"
    ]


def test_cloud_hardtail_plan_sizes_h48h11_machine_from_table_size(tmp_path):
    _write_scrambles(tmp_path, distance=20, count=12)

    payload = build_cloud_hardtail_plan(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h11",
        python_executable="python",
        distance=20,
        start_offset=0,
        end_offset=12,
        shard_size=6,
        threads=16,
        runtime_target_seconds=60.0,
        h48_timeout_seconds=90.0,
        prepass_timeout_seconds=10.0,
        fallback_timeout_seconds=180.0,
        h48_upper_bound_proof_timeout_seconds=90.0,
        h48_upper_bound_proof_max_gap=3,
        rubikoptimal_timeout_seconds=180.0,
        symmetry_timeout_seconds=30.0,
        symmetry_max_concurrency=4,
        h48_stronger_target_solver="h48h11",
        h48_table_generation_timeout_seconds=43200.0,
        artifact_suffix="cloud_h48h11",
        hardtail_execution_mode="batch",
    )

    machine = payload["recommended_minimum_cloud_machine"]
    assert machine["h48_target_solver"] == "h48h11"
    assert machine["h48_target_table_size_bytes"] == estimated_h48_table_size_bytes("h48h11")
    assert machine["memory_gib"] == 128
    assert machine["local_nvme_gib"] == 500
    assert "h48h11" in machine["reason"]
    assert "56.50 GiB" in machine["reason"]


def test_cloud_hardtail_plan_sizes_h48h10_for_64gib_target(tmp_path):
    _write_scrambles(tmp_path, distance=20, count=25)

    payload = build_cloud_hardtail_plan(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h10",
        python_executable="python",
        distance=20,
        start_offset=0,
        end_offset=25,
        shard_size=10,
        threads=16,
        runtime_target_seconds=60.0,
        h48_timeout_seconds=90.0,
        prepass_timeout_seconds=10.0,
        fallback_timeout_seconds=180.0,
        h48_upper_bound_proof_timeout_seconds=90.0,
        h48_upper_bound_proof_max_gap=3,
        rubikoptimal_timeout_seconds=180.0,
        symmetry_timeout_seconds=30.0,
        symmetry_max_concurrency=4,
        h48_stronger_target_solver="h48h10",
        h48_table_generation_timeout_seconds=43200.0,
        artifact_suffix="cloud_h48h10",
        hardtail_execution_mode="batch",
    )

    machine = payload["recommended_minimum_cloud_machine"]
    assert machine["h48_target_solver"] == "h48h10"
    assert machine["h48_target_table_size_bytes"] == estimated_h48_table_size_bytes("h48h10")
    assert machine["memory_gib"] == 64
    assert machine["local_nvme_gib"] == 250
    assert "h48h10" in machine["reason"]
    assert "28.25 GiB" in machine["reason"]


def test_cloud_hardtail_plan_can_use_native_h48_only_fasttarget_strategy(tmp_path):
    _write_scrambles(tmp_path, distance=20, count=25)

    payload = build_cloud_hardtail_plan(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h10",
        python_executable="python",
        distance=20,
        start_offset=0,
        end_offset=25,
        shard_size=10,
        threads=16,
        runtime_target_seconds=60.0,
        h48_timeout_seconds=90.0,
        prepass_timeout_seconds=10.0,
        fallback_timeout_seconds=180.0,
        h48_upper_bound_proof_timeout_seconds=90.0,
        h48_upper_bound_proof_max_gap=3,
        rubikoptimal_timeout_seconds=180.0,
        symmetry_timeout_seconds=30.0,
        symmetry_max_concurrency=4,
        h48_stronger_target_solver="h48h10",
        h48_table_generation_timeout_seconds=43200.0,
        artifact_suffix="cloud_h48h10_native",
        hardtail_execution_mode="batch",
        hardtail_strategy="native-h48-only",
    )

    hardtail_workloads = [
        workload
        for workload in payload["workloads"]
        if workload["kind"] == "public_known_distance_hardtail_batch"
    ]
    assert payload["hardtail_strategy"] == "native-h48-only"
    assert payload["hardtail_per_row_timeout_budget_seconds"] == 90.0
    assert payload["hardtail_baseline_portfolio_per_row_timeout_budget_seconds"] == 1180.0
    assert payload["hardtail_timeout_budget_reduction_factor"] == 13.111111
    first_command = hardtail_workloads[0]["command_args"]
    assert first_command[first_command.index("--command-timeout") + 1] == "1500.0"
    assert "--no-portfolio-prepass" in first_command
    assert first_command[first_command.index("--universal-portfolio-fallback-timeout") + 1] == "0.0"
    assert first_command[first_command.index("--universal-fallback-nissy-core-direct-timeout") + 1] == "-1.0"
    assert "--no-upper-lower-certificate" in first_command
    assert "--require-resident-h48-batch-for-all" in first_command
    assert "--universal-rubikoptimal-prepass-timeout" not in first_command
    assert "--universal-rubikoptimal-race-timeout" not in first_command
    assert "--universal-rubikoptimal-fallback-timeout" not in first_command
    assert "--universal-rubikoptimal-symmetry-variants" not in first_command
    assert "--nissy-symmetry-variants" not in first_command
    assert "--nissy-core-direct-symmetry-variants" not in first_command
    assert "--h48-parallel-symmetry-variants" not in first_command
    assert "--symmetry-order-by-h48-lower-bound" not in first_command
    assert "resident-h48-batch" in hardtail_workloads[0]["notes"]


def test_cloud_hardtail_canary_and_full_can_share_h48_prerequisite_artifact(tmp_path):
    _write_scrambles(tmp_path, distance=20, count=25)

    common_kwargs = dict(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h10",
        python_executable="python",
        distance=20,
        start_offset=0,
        threads=16,
        runtime_target_seconds=60.0,
        h48_timeout_seconds=90.0,
        prepass_timeout_seconds=10.0,
        fallback_timeout_seconds=180.0,
        h48_upper_bound_proof_timeout_seconds=90.0,
        h48_upper_bound_proof_max_gap=3,
        rubikoptimal_timeout_seconds=180.0,
        symmetry_timeout_seconds=30.0,
        symmetry_max_concurrency=4,
        h48_stronger_target_solver="h48h10",
        h48_table_generation_timeout_seconds=43200.0,
        hardtail_execution_mode="batch",
        hardtail_strategy="native-h48-only",
        h48_prerequisite_artifact_suffix="cloud_h48h10_shared_prereq",
        h48_gendata_workbatch=128,
        skip_h48_generation_distribution_scan=True,
        h48_generation_mmap_sync_mode="async",
        h48_backend_extra_cflags=["-march=native"],
    )
    canary = build_cloud_hardtail_plan(
        **common_kwargs,
        end_offset=3,
        shard_size=3,
        artifact_suffix="cloud_h48h10_canary",
        claim_scope="canary",
    )
    full = build_cloud_hardtail_plan(
        **common_kwargs,
        end_offset=25,
        shard_size=10,
        artifact_suffix="cloud_h48h10_full",
        claim_scope="full",
    )

    canary_prereq = next(workload for workload in canary["workloads"] if workload["id"] == "stronger_table_h48h10")
    full_prereq = next(workload for workload in full["workloads"] if workload["id"] == "stronger_table_h48h10")
    assert canary["h48_prerequisite_artifact_suffix"] == "cloud_h48h10_shared_prereq"
    assert full["h48_prerequisite_artifact_suffix"] == "cloud_h48h10_shared_prereq"
    assert full["h48_generation_distribution_mode"] == "expected_constants"
    assert full["h48_generation_distribution_scan_skipped"] is True
    assert full["h48_generation_mmap_sync_mode"] == "async"
    assert full["h48_backend_extra_cflags"] == ["-march=native"]
    assert canary_prereq["command_args"] == full_prereq["command_args"]
    assert canary_prereq["expected_artifacts"] == full_prereq["expected_artifacts"]
    assert full["h48_gendata_workbatch"] == 128
    assert full_prereq["h48_gendata_workbatch"] == 128
    assert full_prereq["command_args"][full_prereq["command_args"].index("--gendata-workbatch") + 1] == "128"
    assert full_prereq["command_args"][full_prereq["command_args"].index("--mmap-sync-mode") + 1] == "async"
    assert "--backend-cflag=-march=native" in full_prereq["command_args"]
    assert "--skip-generation-distribution-scan" in full_prereq["command_args"]
    assert full_prereq["h48_generation_distribution_mode"] == "expected_constants"
    assert full_prereq["h48_generation_distribution_scan_skipped"] is True
    assert full_prereq["h48_generation_mmap_sync_mode"] == "async"
    assert full_prereq["h48_backend_extra_cflags"] == ["-march=native"]
    assert (
        "results/processed/h48_stronger_table_campaign_seed_2026_thesis_h48h10_"
        "cloud_h48h10_shared_prereq_h48h10.json"
    ) in full_prereq["expected_artifacts"]


def test_cloud_hardtail_evaluator_requires_native_h48_rows_for_native_strategy():
    workload = {
        "id": "hardtail_batch",
        "kind": "public_known_distance_hardtail_batch",
        "command_args": [
            "--benchmark-distance",
            "20",
            "--benchmark-limit-per-distance",
            "1",
        ],
    }
    plan = {
        "solver": "h48h10",
        "distance": 20,
        "hardtail_strategy": "native-h48-only",
    }
    payload = {
        "passed": True,
        "solver": "h48h10",
        "trusted_table": True,
        "all_exact": True,
        "all_verified": True,
        "all_expected_distances_match": True,
        "try_certificate_cache": False,
        "try_upper_lower_certificate": False,
        "live_solver_shortcuts_disabled": True,
        "require_resident_h48_batch_for_all": True,
        "resident_h48_batch_all_rows": True,
        "rows": [
            {
                "case_kind": "nissy_core_benchmark_known_distance",
                "status": "exact",
                "verified": True,
                "expected_distance": 20,
                "solution_length": 20,
                "source_sequence_provided_to_solver": False,
                "selected_backend": "resident-h48-batch",
            }
        ],
    }

    assert _evaluate_hardtail_batch_artifact(payload, plan=plan, workload=workload) is True
    fallback_payload = {
        **payload,
        "resident_h48_batch_all_rows": False,
        "rows": [
            {
                **payload["rows"][0],
                "selected_backend": "portfolio-after-resident-h48-fallback",
            }
        ],
    }
    assert _evaluate_hardtail_batch_artifact(fallback_payload, plan=plan, workload=workload) is False


def test_cloud_hardtail_plan_includes_stronger_table_and_superflip_workloads(tmp_path):
    _write_scrambles(tmp_path, distance=20, count=1)

    payload = build_cloud_hardtail_plan(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h7",
        python_executable="python",
        distance=20,
        start_offset=0,
        end_offset=1,
        shard_size=1,
        threads=8,
        runtime_target_seconds=240.0,
        h48_timeout_seconds=300.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=600.0,
        h48_upper_bound_proof_timeout_seconds=300.0,
        h48_upper_bound_proof_max_gap=3,
        rubikoptimal_timeout_seconds=600.0,
        symmetry_timeout_seconds=180.0,
        symmetry_max_concurrency=2,
        h48_stronger_target_solver="h48h8",
        h48_table_generation_timeout_seconds=7200.0,
        artifact_suffix="cloud_test",
    )

    stronger = next(workload for workload in payload["workloads"] if workload["id"] == "stronger_table_h48h8")
    assert "scripts/run_h48_stronger_table_campaign.py" in stronger["command_args"]
    assert stronger["command_args"][stronger["command_args"].index("--target-solver") + 1] == "h48h8"
    assert stronger["command_args"][stronger["command_args"].index("--generation-timeout") + 1] == "7200.0"
    assert "data/generated/h48/thesis_seed_2026/h48h8.bin" in stronger["expected_artifacts"]
    assert "results/processed/h48_metadata_seed_2026_thesis_h48h8.json" in stronger["expected_artifacts"]

    superflip = next(workload for workload in payload["workloads"] if workload["id"] == "rubikoptimal_superflip_hardcase")
    assert "scripts/run_rubikoptimal_oracle_corpus.py" in superflip["command_args"]
    assert "--include-superflip" in superflip["command_args"]
    assert superflip["command_args"][superflip["command_args"].index("--case-id") + 1] == "superflip_distance_20"
    assert superflip["command_args"][superflip["command_args"].index("--timeout") + 1] == "600.0"

    postprocess = [workload for workload in payload["workloads"] if workload["kind"] == "postprocess_and_audit"]
    assert len(postprocess) == 3
    assert any("scripts/generate_h48_oracle_contract.py" in workload["command_args"] for workload in postprocess)
    contract_postprocess = next(
        workload
        for workload in postprocess
        if "scripts/generate_h48_oracle_contract.py" in workload["command_args"]
    )
    assert contract_postprocess["expected_artifacts"] == [
        "results/processed/h48_oracle_contract_seed_2026_thesis_h48h7.json"
    ]


def test_cloud_hardtail_plan_can_build_smaller_canary_scope(tmp_path):
    _write_scrambles(tmp_path, distance=20, count=10)

    payload = build_cloud_hardtail_plan(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h7",
        python_executable="python",
        distance=20,
        start_offset=2,
        end_offset=None,
        shard_size=1,
        threads=8,
        runtime_target_seconds=240.0,
        h48_timeout_seconds=300.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=600.0,
        h48_upper_bound_proof_timeout_seconds=300.0,
        h48_upper_bound_proof_max_gap=3,
        rubikoptimal_timeout_seconds=600.0,
        symmetry_timeout_seconds=180.0,
        symmetry_max_concurrency=2,
        h48_stronger_target_solver="h48h8",
        h48_table_generation_timeout_seconds=7200.0,
        artifact_suffix="cloud_canary",
        claim_scope="canary",
        canary_offset_count=3,
    )

    shard_workloads = [
        workload
        for workload in payload["workloads"]
        if workload["kind"] == "public_known_distance_hardtail_sweep"
    ]
    assert payload["claim_scope"] == "canary"
    assert payload["selected_offset_start"] == 2
    assert payload["selected_offset_end"] == 5
    assert [workload["id"] for workload in shard_workloads] == [
        "known_distance_20_shard_000",
        "known_distance_20_shard_001",
        "known_distance_20_shard_002",
    ]
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert "only a full-scope plan" in payload["notes"]


def test_cloud_workload_runner_executes_one_plan_workload_and_captures_artifacts(tmp_path):
    artifact_script = (
        "from pathlib import Path; import json; "
        "p=Path('results/processed/fake_cloud_artifact.json'); "
        "p.parent.mkdir(parents=True, exist_ok=True); "
        "p.write_text(json.dumps({'passed': True}) + '\\n', encoding='utf-8')"
    )
    plan = {
        "objective": "test objective",
        "workloads": [
            {
                "id": "tiny_workload",
                "kind": "postprocess_and_audit",
                "command_args": [sys.executable, "-c", artifact_script],
                "environment": {"RUBIK_OPTIMAL_THREADS": "1"},
                "expected_artifacts": ["results/processed/fake_cloud_artifact.json"],
                "required_for_fast_every_state_claim": True,
            }
        ],
    }
    plan_path = tmp_path / "results" / "processed" / "cloud_plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    payload, output = run_workload(
        root=tmp_path,
        plan_path=plan_path,
        workload_id="tiny_workload",
        dry_run=False,
        timeout_seconds=10.0,
        artifact_suffix="test",
    )

    assert output.exists()
    assert payload["executed"] is True
    assert payload["return_code"] == 0
    assert payload["expected_artifacts_found"] is True
    assert payload["passed"] is True
    assert payload["artifact_summaries"][0]["path"] == "results/processed/fake_cloud_artifact.json"
    assert payload["artifact_integrity_algorithm"] == "sha256-size-v1"
    assert payload["artifact_summaries"][0]["size_bytes"] > 0
    assert len(payload["artifact_summaries"][0]["sha256"]) == 64
    assert payload["fingerprint_algorithm"] == "sha256-canonical-json-v1"
    assert payload["plan_fingerprint"] == fingerprint_json(plan)
    assert payload["workload_fingerprint"] == fingerprint_json(plan["workloads"][0])


def test_cloud_campaign_evaluator_rejects_changed_artifact_after_workload_pass(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    artifact_script = (
        "from pathlib import Path; import json; "
        "p=Path('results/processed/hardtail_batch.json'); "
        "p.parent.mkdir(parents=True, exist_ok=True); "
        "p.write_text(json.dumps({"
        "'passed': True, 'solver': 'h48h7', 'trusted_table': True, "
        "'all_exact': True, 'all_verified': True, 'all_expected_distances_match': True, "
        "'try_certificate_cache': False, 'rows': [{"
        "'case_kind': 'nissy_core_benchmark_known_distance', "
        "'status': 'exact', 'verified': True, 'expected_distance': 20, "
        "'solution_length': 20, 'source_sequence_provided_to_solver': False"
        "}]}) + '\\n', encoding='utf-8')"
    )
    workload = {
        "id": "hardtail_batch",
        "kind": "public_known_distance_hardtail_batch",
        "command_args": [sys.executable, "-c", artifact_script],
        "expected_artifacts": ["results/processed/hardtail_batch.json"],
        "required_for_fast_every_state_claim": True,
    }
    plan = {
        "objective": "prove or falsify",
        "profile": "thesis",
        "seed": 2026,
        "solver": "h48h7",
        "distance": 20,
        "workloads": [workload],
    }
    plan_path = processed / "fake_cloud_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    (processed / "h48_oracle_contract_seed_2026_thesis_h48h7.json").write_text(
        json.dumps(
            {
                "all_state_exact_contract_supported": True,
                "fast_optimal_oracle_implemented_for_every_valid_3x3_state": True,
                "fast_runtime_proven_for_every_possible_state": True,
            }
        ),
        encoding="utf-8",
    )
    (processed / "thesis_audit.json").write_text(
        json.dumps(
            {
                "acceptance_implementation_passed": True,
                "acceptance_repository_passed": True,
                "acceptance_research_passed": True,
                "acceptance_scale_passed": True,
            }
        ),
        encoding="utf-8",
    )

    payload, _output = run_workload(
        root=root,
        plan_path=plan_path,
        workload_id="hardtail_batch",
        dry_run=False,
        timeout_seconds=10.0,
        artifact_suffix="integrity",
    )
    assert payload["passed"] is True
    assert evaluate_campaign(root=root, plan_path=plan_path)["rows"][0]["passed"] is True

    (processed / "hardtail_batch.json").write_text(json.dumps({"passed": False}), encoding="utf-8")
    evaluated = evaluate_campaign(root=root, plan_path=plan_path)

    row = evaluated["rows"][0]
    assert row["passed"] is False
    assert row["reason"] == "workload artifact content no longer matches recorded fingerprint"
    assert row["artifact_integrity_validation"]["required"] is True
    assert row["artifact_integrity_validation"]["passed"] is False
    assert "size changed" in row["artifact_integrity_validation"]["reasons"][0]


def test_cloud_campaign_evaluator_rejects_stale_workload_fingerprint(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    workload = {
        "id": "hardtail_batch",
        "kind": "public_known_distance_hardtail_batch",
        "command_args": [
            "--benchmark-distance",
            "20",
            "--benchmark-limit-per-distance",
            "1",
        ],
        "required_for_fast_every_state_claim": True,
        "expected_artifacts": ["results/processed/hardtail_batch.json"],
    }
    plan = {
        "objective": "prove or falsify",
        "profile": "thesis",
        "seed": 2026,
        "solver": "h48h7",
        "distance": 20,
        "workloads": [workload],
    }
    plan_path = processed / "fake_cloud_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    (processed / "hardtail_batch.json").write_text(
        json.dumps(
            {
                "passed": True,
                "solver": "h48h7",
                "trusted_table": True,
                "all_exact": True,
                "all_verified": True,
                "all_expected_distances_match": True,
                "try_certificate_cache": False,
                "rows": [
                    {
                        "case_kind": "nissy_core_benchmark_known_distance",
                        "status": "exact",
                        "verified": True,
                        "expected_distance": 20,
                        "solution_length": 20,
                        "source_sequence_provided_to_solver": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    stale_result = _fingerprinted_workload_result(
        {"objective": "old plan", "workloads": [workload]},
        workload,
        artifact_summaries=[{"path": "results/processed/hardtail_batch.json"}],
    )
    (processed / "cloud_hardtail_workload_fake_cloud_plan_hardtail_batch_old.json").write_text(
        json.dumps(stale_result),
        encoding="utf-8",
    )
    (processed / "h48_oracle_contract_seed_2026_thesis_h48h7.json").write_text(
        json.dumps(
            {
                "all_state_exact_contract_supported": True,
                "fast_optimal_oracle_implemented_for_every_valid_3x3_state": True,
                "fast_runtime_proven_for_every_possible_state": True,
            }
        ),
        encoding="utf-8",
    )
    (processed / "thesis_audit.json").write_text(
        json.dumps(
            {
                "acceptance_implementation_passed": True,
                "acceptance_repository_passed": True,
                "acceptance_research_passed": True,
                "acceptance_scale_passed": True,
            }
        ),
        encoding="utf-8",
    )

    payload = evaluate_campaign(root=root, plan_path=plan_path)

    assert payload["all_required_workloads_passed"] is False
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert payload["rows"][0]["passed"] is False
    assert payload["rows"][0]["reason"] == "workload result does not match the current plan/workload fingerprint"
    assert payload["rows"][0]["fingerprint_validation"]["passed"] is False
    assert "plan fingerprint mismatch" in payload["rows"][0]["fingerprint_validation"]["reasons"]


def test_cloud_workload_runner_blocks_when_dependency_artifacts_are_missing(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    marker_script = "from pathlib import Path; Path('SHOULD_NOT_EXIST').write_text('ran')"
    plan = {
        "objective": "dependency test",
        "workloads": [
            {
                "id": "stronger_table_h48h8",
                "kind": "h48_stronger_table_generation_and_certification",
                "expected_artifacts": [
                    "results/processed/h48_metadata_seed_2026_thesis_h48h8.json",
                    "data/generated/h48/thesis_seed_2026/h48h8.bin",
                ],
                "required_for_fast_every_state_claim": True,
            },
            {
                "id": "known_distance_20_shard_000",
                "kind": "public_known_distance_hardtail_batch",
                "command_args": [sys.executable, "-c", marker_script],
                "environment": {},
                "expected_artifacts": ["results/processed/hardtail.json"],
                "depends_on_workload_ids": ["stronger_table_h48h8"],
                "required_for_fast_every_state_claim": True,
            },
        ],
    }
    plan_path = processed / "cloud_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    payload, output = run_workload(
        root=root,
        plan_path=plan_path,
        workload_id="known_distance_20_shard_000",
        dry_run=False,
        timeout_seconds=10.0,
        artifact_suffix="depblock",
    )

    assert output.exists()
    assert payload["executed"] is False
    assert payload["blocked_by_missing_dependencies"] is True
    assert payload["dependency_artifacts_found"] is False
    assert payload["dependency_checks"][0]["dependency_id"] == "stronger_table_h48h8"
    assert payload["dependency_checks"][0]["passed"] is False
    assert payload["return_code"] is None
    assert payload["passed"] is False
    assert not (root / "SHOULD_NOT_EXIST").exists()


def test_cloud_workload_runner_blocks_when_h48_dependency_artifacts_are_untrusted(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    h48_dir = root / "data" / "generated" / "h48" / "thesis_seed_2026"
    processed.mkdir(parents=True, exist_ok=True)
    h48_dir.mkdir(parents=True, exist_ok=True)
    (processed / "h48_metadata_seed_2026_thesis_h48h8.json").write_text("{}", encoding="utf-8")
    (h48_dir / "h48h8.bin").write_bytes(b"fake")
    marker_script = "from pathlib import Path; Path('SHOULD_NOT_EXIST').write_text('ran')"
    plan = {
        "objective": "dependency test",
        "profile": "thesis",
        "seed": 2026,
        "solver": "h48h8",
        "workloads": [
            {
                "id": "stronger_table_h48h8",
                "kind": "h48_stronger_table_generation_and_certification",
                "command_args": [
                    sys.executable,
                    "scripts/run_h48_stronger_table_campaign.py",
                    "--target-solver",
                    "h48h8",
                ],
                "expected_artifacts": [
                    "results/processed/h48_metadata_seed_2026_thesis_h48h8.json",
                    "data/generated/h48/thesis_seed_2026/h48h8.bin",
                ],
                "required_for_fast_every_state_claim": True,
            },
            {
                "id": "known_distance_20_shard_000",
                "kind": "public_known_distance_hardtail_batch",
                "command_args": [sys.executable, "-c", marker_script],
                "environment": {},
                "expected_artifacts": ["results/processed/hardtail.json"],
                "depends_on_workload_ids": ["stronger_table_h48h8"],
                "required_for_fast_every_state_claim": True,
            },
        ],
    }
    plan_path = processed / "cloud_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    payload, _output = run_workload(
        root=root,
        plan_path=plan_path,
        workload_id="known_distance_20_shard_000",
        dry_run=False,
        timeout_seconds=10.0,
        artifact_suffix="depuntrusted",
    )

    assert payload["dependency_artifacts_found"] is True
    assert payload["blocked_by_missing_dependencies"] is False
    assert payload["blocked_by_untrusted_h48_dependencies"] is True
    assert payload["h48_trusted_dependencies_satisfied"] is False
    assert payload["h48_trusted_dependency_checks"][0]["solver"] == "h48h8"
    assert payload["executed"] is False
    assert payload["passed"] is False
    assert not (root / "SHOULD_NOT_EXIST").exists()


def test_cloud_workload_runner_allows_workload_when_dependency_artifacts_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.experimental.run_cloud_hardtail_workload.validate_trusted_h48_table_checksum",
        lambda **_kwargs: (
            True,
            "test trusted table full checksum",
            {
                "trusted_metadata_valid": True,
                "full_checksum_valid": True,
                "checksum_cache_hit": False,
                "checksum_runtime_seconds": 0.01,
            },
        ),
    )
    root = tmp_path
    processed = root / "results" / "processed"
    h48_dir = root / "data" / "generated" / "h48" / "thesis_seed_2026"
    processed.mkdir(parents=True, exist_ok=True)
    h48_dir.mkdir(parents=True, exist_ok=True)
    (processed / "h48_metadata_seed_2026_thesis_h48h8.json").write_text("{}", encoding="utf-8")
    (h48_dir / "h48h8.bin").write_bytes(b"fake")
    artifact_script = (
        "from pathlib import Path; import json; "
        "p=Path('results/processed/hardtail.json'); "
        "p.write_text(json.dumps({'passed': True}) + '\\n', encoding='utf-8')"
    )
    plan = {
        "objective": "dependency test",
        "profile": "thesis",
        "seed": 2026,
        "solver": "h48h8",
        "workloads": [
            {
                "id": "stronger_table_h48h8",
                "kind": "h48_stronger_table_generation_and_certification",
                "command_args": [
                    sys.executable,
                    "scripts/run_h48_stronger_table_campaign.py",
                    "--target-solver",
                    "h48h8",
                ],
                "expected_artifacts": [
                    "results/processed/h48_metadata_seed_2026_thesis_h48h8.json",
                    "data/generated/h48/thesis_seed_2026/h48h8.bin",
                ],
                "required_for_fast_every_state_claim": True,
            },
            {
                "id": "known_distance_20_shard_000",
                "kind": "public_known_distance_hardtail_batch",
                "command_args": [sys.executable, "-c", artifact_script],
                "environment": {},
                "expected_artifacts": ["results/processed/hardtail.json"],
                "depends_on_workload_ids": ["stronger_table_h48h8"],
                "required_for_fast_every_state_claim": True,
            },
        ],
    }
    plan_path = processed / "cloud_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    payload, _output = run_workload(
        root=root,
        plan_path=plan_path,
        workload_id="known_distance_20_shard_000",
        dry_run=False,
        timeout_seconds=10.0,
        artifact_suffix="deppass",
    )

    assert payload["blocked_by_missing_dependencies"] is False
    assert payload["blocked_by_untrusted_h48_dependencies"] is False
    assert payload["dependency_artifacts_found"] is True
    assert payload["dependency_checks"][0]["passed"] is True
    assert payload["h48_trusted_dependencies_satisfied"] is True
    assert payload["h48_trusted_dependency_checks"][0]["passed"] is True
    assert payload["h48_trusted_dependency_checks"][0]["full_checksum_valid"] is True
    assert payload["executed"] is True
    assert payload["passed"] is True


def test_cloud_workload_runner_blocks_when_h48_dependency_checksum_mismatches(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.experimental.run_cloud_hardtail_workload.validate_trusted_h48_table_checksum",
        lambda **_kwargs: (
            False,
            "trusted H48 full checksum mismatch",
            {
                "trusted_metadata_valid": True,
                "full_checksum_valid": False,
                "checksum_cache_hit": False,
                "checksum_runtime_seconds": 0.01,
            },
        ),
    )
    root = tmp_path
    processed = root / "results" / "processed"
    h48_dir = root / "data" / "generated" / "h48" / "thesis_seed_2026"
    processed.mkdir(parents=True, exist_ok=True)
    h48_dir.mkdir(parents=True, exist_ok=True)
    (processed / "h48_metadata_seed_2026_thesis_h48h8.json").write_text("{}", encoding="utf-8")
    (h48_dir / "h48h8.bin").write_bytes(b"fake")
    marker_script = "from pathlib import Path; Path('SHOULD_NOT_EXIST').write_text('ran')"
    plan = {
        "objective": "dependency test",
        "profile": "thesis",
        "seed": 2026,
        "solver": "h48h8",
        "workloads": [
            {
                "id": "stronger_table_h48h8",
                "kind": "h48_stronger_table_generation_and_certification",
                "command_args": [
                    sys.executable,
                    "scripts/run_h48_stronger_table_campaign.py",
                    "--target-solver",
                    "h48h8",
                ],
                "expected_artifacts": [
                    "results/processed/h48_metadata_seed_2026_thesis_h48h8.json",
                    "data/generated/h48/thesis_seed_2026/h48h8.bin",
                ],
                "required_for_fast_every_state_claim": True,
            },
            {
                "id": "known_distance_20_shard_000",
                "kind": "public_known_distance_hardtail_batch",
                "command_args": [sys.executable, "-c", marker_script],
                "environment": {},
                "expected_artifacts": ["results/processed/hardtail.json"],
                "depends_on_workload_ids": ["stronger_table_h48h8"],
                "required_for_fast_every_state_claim": True,
            },
        ],
    }
    plan_path = processed / "cloud_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    payload, _output = run_workload(
        root=root,
        plan_path=plan_path,
        workload_id="known_distance_20_shard_000",
        dry_run=False,
        timeout_seconds=10.0,
        artifact_suffix="depchecksum",
    )

    assert payload["dependency_artifacts_found"] is True
    assert payload["blocked_by_missing_dependencies"] is False
    assert payload["blocked_by_untrusted_h48_dependencies"] is True
    assert payload["h48_trusted_dependency_checks"][0]["trusted_metadata_valid"] is True
    assert payload["h48_trusted_dependency_checks"][0]["full_checksum_valid"] is False
    assert payload["executed"] is False
    assert not (root / "SHOULD_NOT_EXIST").exists()


def test_cloud_campaign_evaluator_can_mark_fully_proven_fake_campaign(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    plan = {
        "objective": "prove or falsify",
        "profile": "thesis",
        "seed": 2026,
        "solver": "h48h7",
        "distance": 20,
        "workloads": [
            {
                "id": "hardtail",
                "kind": "public_known_distance_hardtail_sweep",
                "required_for_fast_every_state_claim": True,
                "expected_artifacts": ["results/processed/hardtail.json"],
            },
            {
                "id": "stronger",
                "kind": "h48_stronger_table_generation_and_certification",
                "required_for_fast_every_state_claim": True,
                "expected_artifacts": ["results/processed/stronger.json"],
            },
            {
                "id": "rubikoptimal",
                "kind": "rubikoptimal_table_complete_hardcase",
                "required_for_fast_every_state_claim": True,
                "expected_artifacts": ["results/processed/rubikoptimal.json"],
            },
            {
                "id": "postprocess",
                "kind": "postprocess_and_audit",
                "required_for_fast_every_state_claim": True,
                "expected_artifacts": [],
            },
        ],
    }
    plan_path = processed / "fake_cloud_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    artifacts = {
        "hardtail.json": {
            "passed": True,
            "solver": "h48h7",
            "trusted_table": True,
            "failed_offset_count": 0,
            "rows": [
                {
                    "sweep_status": "ran_passed",
                    "status": "exact",
                    "verified": True,
                    "expected_distance": 20,
                    "source_sequence_provided_to_solver": False,
                }
            ],
        },
        "stronger.json": {
            "passed": True,
            "target_solver": "h48h7",
            "target_estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h7"),
            "post_campaign_target_trusted_table": True,
            "post_campaign_full_checksum_valid": True,
            "status": "generated_and_certified",
        },
        "rubikoptimal.json": {
            "passed": True,
            "all_exact": True,
            "all_verified": True,
            "rows": [
                {
                    "case_id": "superflip_distance_20",
                    "status": "exact",
                    "verified": True,
                    "expected_distance": 20,
                    "solution_length": 20,
                }
            ],
        },
    }
    for name, payload in artifacts.items():
        (processed / name).write_text(json.dumps(payload), encoding="utf-8")
    for workload_id, artifact_name in [
        ("hardtail", "hardtail.json"),
        ("stronger", "stronger.json"),
        ("rubikoptimal", "rubikoptimal.json"),
        ("postprocess", None),
    ]:
        workload = next(row for row in plan["workloads"] if row["id"] == workload_id)
        result = _fingerprinted_workload_result(
            plan,
            workload,
            root=root,
            artifact_summaries=(
                [{"path": f"results/processed/{artifact_name}"}] if artifact_name else []
            ),
        )
        (processed / f"cloud_hardtail_workload_fake_cloud_plan_{workload_id}.json").write_text(
            json.dumps(result),
            encoding="utf-8",
        )
    (processed / "h48_oracle_contract_seed_2026_thesis_h48h7.json").write_text(
        json.dumps(
            {
                "all_state_exact_contract_supported": True,
                "fast_optimal_oracle_implemented_for_every_valid_3x3_state": True,
                "fast_runtime_proven_for_every_possible_state": True,
            }
        ),
        encoding="utf-8",
    )
    (processed / "thesis_audit.json").write_text(
        json.dumps(
            {
                "acceptance_implementation_passed": True,
                "acceptance_repository_passed": True,
                "acceptance_research_passed": True,
                "acceptance_scale_passed": True,
            }
        ),
        encoding="utf-8",
    )

    payload = evaluate_campaign(root=root, plan_path=plan_path)

    assert payload["all_required_workloads_passed"] is True
    assert payload["all_required_artifact_integrity_passed"] is True
    assert payload["artifact_integrity_required_workload_count"] == 3
    assert payload["artifact_integrity_passed_workload_count"] == 3
    assert payload["cloud_runtime_evidence_passed"] is True
    assert payload["plan_claim_scope"] == "full"
    assert payload["plan_profile"] == "thesis"
    assert payload["plan_solver"] == "h48h7"
    assert payload["contract_checks"]["fast_runtime_proven_for_every_possible_state"] is True
    assert payload["thesis_audit_acceptance_gates_passed"] is True
    assert payload["fast_runtime_proven_for_every_possible_state"] is True


def test_cloud_campaign_evaluator_accepts_batched_hardtail_artifacts(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    plan = {
        "objective": "prove or falsify",
        "profile": "thesis",
        "seed": 2026,
        "solver": "h48h7",
        "distance": 20,
        "workloads": [
            {
                "id": "hardtail_batch",
                "kind": "public_known_distance_hardtail_batch",
                "command_args": [
                    "--benchmark-distance",
                    "20",
                    "--benchmark-limit-per-distance",
                    "1",
                ],
                "required_for_fast_every_state_claim": True,
                "expected_artifacts": ["results/processed/hardtail_batch.json"],
            }
        ],
    }
    plan_path = processed / "fake_cloud_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    (processed / "hardtail_batch.json").write_text(
        json.dumps(
            {
                "passed": True,
                "solver": "h48h7",
                "trusted_table": True,
                "all_exact": True,
                "all_verified": True,
                "all_expected_distances_match": True,
                "try_certificate_cache": False,
                "rows": [
                    {
                        "case_kind": "nissy_core_benchmark_known_distance",
                        "status": "exact",
                        "verified": True,
                        "expected_distance": 20,
                        "solution_length": 20,
                        "source_sequence_provided_to_solver": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (processed / "cloud_hardtail_workload_fake_cloud_plan_hardtail_batch.json").write_text(
        json.dumps(
            _fingerprinted_workload_result(
                plan,
                plan["workloads"][0],
                root=root,
                artifact_summaries=[{"path": "results/processed/hardtail_batch.json"}],
            )
        ),
        encoding="utf-8",
    )
    (processed / "h48_oracle_contract_seed_2026_thesis_h48h7.json").write_text(
        json.dumps(
            {
                "all_state_exact_contract_supported": True,
                "fast_optimal_oracle_implemented_for_every_valid_3x3_state": True,
                "fast_runtime_proven_for_every_possible_state": True,
            }
        ),
        encoding="utf-8",
    )
    (processed / "thesis_audit.json").write_text(
        json.dumps(
            {
                "acceptance_implementation_passed": True,
                "acceptance_repository_passed": True,
                "acceptance_research_passed": True,
                "acceptance_scale_passed": True,
            }
        ),
        encoding="utf-8",
    )

    payload = evaluate_campaign(root=root, plan_path=plan_path)

    assert payload["all_required_workloads_passed"] is True
    assert payload["rows"][0]["passed"] is True


def test_cloud_campaign_evaluator_prefers_older_valid_pass_over_newer_dryrun(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    plan = {
        "objective": "prove or falsify",
        "profile": "thesis",
        "seed": 2026,
        "solver": "h48h7",
        "distance": 20,
        "workloads": [
            {
                "id": "hardtail_batch",
                "kind": "public_known_distance_hardtail_batch",
                "command_args": [
                    "--benchmark-distance",
                    "20",
                    "--benchmark-limit-per-distance",
                    "1",
                ],
                "required_for_fast_every_state_claim": True,
                "expected_artifacts": ["results/processed/hardtail_batch.json"],
            }
        ],
    }
    plan_path = processed / "fake_cloud_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    (processed / "hardtail_batch.json").write_text(
        json.dumps(
            {
                "passed": True,
                "solver": "h48h7",
                "trusted_table": True,
                "all_exact": True,
                "all_verified": True,
                "all_expected_distances_match": True,
                "try_certificate_cache": False,
                "rows": [
                    {
                        "case_kind": "nissy_core_benchmark_known_distance",
                        "status": "exact",
                        "verified": True,
                        "expected_distance": 20,
                        "solution_length": 20,
                        "source_sequence_provided_to_solver": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    valid_path = processed / "cloud_hardtail_workload_fake_cloud_plan_hardtail_batch_valid.json"
    valid_path.write_text(
        json.dumps(
            _fingerprinted_workload_result(
                plan,
                plan["workloads"][0],
                root=root,
                artifact_summaries=[{"path": "results/processed/hardtail_batch.json"}],
            )
        ),
        encoding="utf-8",
    )
    newer_dryrun_path = (
        processed / "cloud_hardtail_workload_fake_cloud_plan_hardtail_batch_newer_dryrun.json"
    )
    newer_dryrun_path.write_text(
        json.dumps(
            _fingerprinted_workload_result(
                plan,
                plan["workloads"][0],
                passed=True,
                executed=False,
                dry_run=True,
                root=root,
                artifact_summaries=[{"path": "results/processed/hardtail_batch.json"}],
            )
        ),
        encoding="utf-8",
    )
    os.utime(valid_path, (1, 1))
    os.utime(newer_dryrun_path, (2, 2))

    payload = evaluate_campaign(root=root, plan_path=plan_path)

    row = payload["rows"][0]
    assert payload["all_required_workloads_passed"] is True
    assert row["passed"] is True
    assert row["result_path"].endswith("_valid.json")
    assert row["ignored_newer_result_count"] == 1
    assert row["ignored_newer_results"][0]["rejection_reason"] == "result_not_executed"


def test_cloud_campaign_evaluator_requires_h48_dependency_validation_for_hardtail(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    plan = {
        "objective": "prove or falsify",
        "profile": "thesis",
        "seed": 2026,
        "solver": "h48h8",
        "distance": 20,
        "workloads": [
            {
                "id": "stronger_table_h48h8",
                "kind": "h48_stronger_table_generation_and_certification",
                "command_args": [
                    sys.executable,
                    "scripts/run_h48_stronger_table_campaign.py",
                    "--target-solver",
                    "h48h8",
                ],
                "required_for_fast_every_state_claim": False,
                "expected_artifacts": [
                    "results/processed/h48_metadata_seed_2026_thesis_h48h8.json",
                    "data/generated/h48/thesis_seed_2026/h48h8.bin",
                ],
            },
            {
                "id": "hardtail_batch",
                "kind": "public_known_distance_hardtail_batch",
                "command_args": [
                    "--benchmark-distance",
                    "20",
                    "--benchmark-limit-per-distance",
                    "1",
                ],
                "depends_on_workload_ids": ["stronger_table_h48h8"],
                "required_for_fast_every_state_claim": True,
                "expected_artifacts": ["results/processed/hardtail_batch.json"],
            },
        ],
    }
    plan_path = processed / "fake_cloud_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    (processed / "hardtail_batch.json").write_text(
        json.dumps(
            {
                "passed": True,
                "solver": "h48h8",
                "trusted_table": True,
                "all_exact": True,
                "all_verified": True,
                "all_expected_distances_match": True,
                "try_certificate_cache": False,
                "rows": [
                    {
                        "case_kind": "nissy_core_benchmark_known_distance",
                        "status": "exact",
                        "verified": True,
                        "expected_distance": 20,
                        "solution_length": 20,
                        "source_sequence_provided_to_solver": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = _fingerprinted_workload_result(
        plan,
        plan["workloads"][1],
        root=root,
        artifact_summaries=[{"path": "results/processed/hardtail_batch.json"}],
    )
    missing_validation_result = (
        processed / "cloud_hardtail_workload_fake_cloud_plan_hardtail_batch_missing_validation.json"
    )
    missing_validation_result.write_text(
        json.dumps(result),
        encoding="utf-8",
    )

    payload = evaluate_campaign(root=root, plan_path=plan_path)

    hardtail_row = next(row for row in payload["rows"] if row["workload_id"] == "hardtail_batch")
    assert hardtail_row["passed"] is False
    assert hardtail_row["reason"] == "workload did not prove trusted H48 dependency validation before search"
    assert hardtail_row["h48_dependency_validation"]["required"] is True
    assert "missing h48_trusted_dependency_checks" in hardtail_row["h48_dependency_validation"]["reasons"][0]

    result["h48_trusted_dependency_checks"] = [
        {
            "dependency_id": "stronger_table_h48h8",
            "solver": "h48h8",
            "profile": "thesis",
            "seed": 2026,
            "passed": True,
            "trusted_metadata_valid": True,
            "full_checksum_valid": True,
        }
    ]
    missing_validation_result.unlink()
    (processed / "cloud_hardtail_workload_fake_cloud_plan_hardtail_batch_with_validation.json").write_text(
        json.dumps(result),
        encoding="utf-8",
    )

    payload = evaluate_campaign(root=root, plan_path=plan_path)
    hardtail_row = next(row for row in payload["rows"] if row["workload_id"] == "hardtail_batch")
    assert hardtail_row["passed"] is True
    assert hardtail_row["h48_dependency_validation"]["passed"] is True


def test_cloud_campaign_runner_executes_selected_workloads_and_evaluates(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    artifact_script = (
        "from pathlib import Path; import json; "
        "p=Path('results/processed/fake_hardtail.json'); "
        "p.parent.mkdir(parents=True, exist_ok=True); "
        "p.write_text(json.dumps({'passed': True, 'solver': 'h48h7', 'trusted_table': True, "
        "'failed_offset_count': 0, "
        "'rows': [{'sweep_status': 'ran_passed', 'status': 'exact', 'verified': True, "
        "'expected_distance': 20, 'source_sequence_provided_to_solver': False}]}) + '\\n', "
        "encoding='utf-8')"
    )
    plan = {
        "objective": "prove or falsify",
        "claim_scope": "canary",
        "profile": "thesis",
        "seed": 2026,
        "solver": "h48h7",
        "distance": 20,
        "workloads": [
            {
                "id": "hardtail",
                "kind": "public_known_distance_hardtail_sweep",
                "command_args": [sys.executable, "-c", artifact_script],
                "environment": {"RUBIK_OPTIMAL_THREADS": "1"},
                "expected_artifacts": ["results/processed/fake_hardtail.json"],
                "required_for_fast_every_state_claim": True,
            }
        ],
    }
    plan_path = processed / "fake_cloud_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    (processed / "h48_oracle_contract_seed_2026_thesis_h48h7.json").write_text(
        json.dumps(
            {
                "all_state_exact_contract_supported": True,
                "fast_optimal_oracle_implemented_for_every_valid_3x3_state": True,
                "fast_runtime_proven_for_every_possible_state": False,
            }
        ),
        encoding="utf-8",
    )
    (processed / "thesis_audit.json").write_text(
        json.dumps(
            {
                "acceptance_implementation_passed": True,
                "acceptance_repository_passed": True,
                "acceptance_research_passed": True,
                "acceptance_scale_passed": True,
            }
        ),
        encoding="utf-8",
    )

    payload, output = run_campaign(
        root=root,
        plan_path=plan_path,
        dry_run=False,
        resume=False,
        stop_on_fail=True,
        timeout_seconds=10.0,
        use_estimated_timeouts=False,
        timeout_scale=1.0,
        artifact_suffix="test",
        evaluation_suffix="test",
    )

    assert output.exists()
    assert payload["selected_workload_count"] == 1
    assert payload["executed_workload_count"] == 1
    assert payload["all_selected_workloads_passed"] is True
    assert payload["evaluation_all_required_workloads_passed"] is True
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert (processed / "cloud_hardtail_campaign_evaluation_fake_cloud_plan_test.json").exists()


def test_cloud_campaign_runner_resume_skips_existing_passed_workload(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    plan = {
        "objective": "resume test",
        "workloads": [
            {
                "id": "already_done",
                "kind": "postprocess_and_audit",
                "command_args": [sys.executable, "-c", "raise SystemExit(99)"],
                "environment": {},
                "expected_artifacts": [],
                "required_for_fast_every_state_claim": True,
            }
        ],
    }
    plan_path = processed / "fake_cloud_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    (processed / "cloud_hardtail_workload_fake_cloud_plan_already_done_previous.json").write_text(
        json.dumps(_fingerprinted_workload_result(plan, plan["workloads"][0])),
        encoding="utf-8",
    )

    payload, _output = run_campaign(
        root=root,
        plan_path=plan_path,
        dry_run=False,
        resume=True,
        stop_on_fail=True,
        timeout_seconds=1.0,
        use_estimated_timeouts=False,
        timeout_scale=1.0,
        artifact_suffix="resume",
        evaluate_after=False,
    )

    assert payload["selected_workload_count"] == 1
    assert payload["executed_workload_count"] == 0
    assert payload["skipped_existing_passed_count"] == 1
    assert payload["rows"][0]["action"] == "skipped_existing_passed"
    assert payload["all_selected_workloads_passed"] is True


def test_cloud_campaign_runner_resume_skips_older_valid_pass_after_newer_failure(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    plan = {
        "objective": "resume test",
        "workloads": [
            {
                "id": "already_done",
                "kind": "postprocess_and_audit",
                "command_args": [sys.executable, "-c", "raise SystemExit(99)"],
                "environment": {},
                "expected_artifacts": [],
                "required_for_fast_every_state_claim": True,
            }
        ],
    }
    plan_path = processed / "fake_cloud_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    valid_path = processed / "cloud_hardtail_workload_fake_cloud_plan_already_done_valid.json"
    valid_path.write_text(
        json.dumps(_fingerprinted_workload_result(plan, plan["workloads"][0])),
        encoding="utf-8",
    )
    failed_path = processed / "cloud_hardtail_workload_fake_cloud_plan_already_done_failed_newer.json"
    failed_path.write_text(
        json.dumps(
            _fingerprinted_workload_result(
                plan,
                plan["workloads"][0],
                passed=False,
                executed=True,
                return_code=17,
            )
        ),
        encoding="utf-8",
    )
    os.utime(valid_path, (1, 1))
    os.utime(failed_path, (2, 2))

    payload, _output = run_campaign(
        root=root,
        plan_path=plan_path,
        dry_run=False,
        resume=True,
        stop_on_fail=True,
        timeout_seconds=1.0,
        use_estimated_timeouts=False,
        timeout_scale=1.0,
        artifact_suffix="resume",
        evaluate_after=False,
    )

    assert payload["selected_workload_count"] == 1
    assert payload["executed_workload_count"] == 0
    assert payload["skipped_existing_passed_count"] == 1
    assert payload["rows"][0]["action"] == "skipped_existing_passed"
    assert payload["rows"][0]["result_path"].endswith("_valid.json")
    assert payload["rows"][0]["ignored_newer_result_count"] == 1
    assert payload["rows"][0]["ignored_newer_results"][0]["rejection_reason"] == "result_not_passed"
    assert payload["all_selected_workloads_passed"] is True


def test_cloud_campaign_runner_resume_ignores_stale_passed_workload(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    artifact_script = (
        "from pathlib import Path; import json; "
        "p=Path('results/processed/resume_current.json'); "
        "p.parent.mkdir(parents=True, exist_ok=True); "
        "p.write_text(json.dumps({'passed': True}) + '\\n', encoding='utf-8')"
    )
    plan = {
        "objective": "resume test",
        "workloads": [
            {
                "id": "already_done",
                "kind": "postprocess_and_audit",
                "command_args": [sys.executable, "-c", artifact_script],
                "environment": {},
                "expected_artifacts": ["results/processed/resume_current.json"],
                "required_for_fast_every_state_claim": True,
            }
        ],
    }
    plan_path = processed / "fake_cloud_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    stale_result = _fingerprinted_workload_result(
        {"objective": "old resume test", "workloads": plan["workloads"]},
        plan["workloads"][0],
    )
    (processed / "cloud_hardtail_workload_fake_cloud_plan_already_done_previous.json").write_text(
        json.dumps(stale_result),
        encoding="utf-8",
    )

    payload, _output = run_campaign(
        root=root,
        plan_path=plan_path,
        dry_run=False,
        resume=True,
        stop_on_fail=True,
        timeout_seconds=10.0,
        use_estimated_timeouts=False,
        timeout_scale=1.0,
        artifact_suffix="resume_current",
        evaluate_after=False,
    )

    assert payload["selected_workload_count"] == 1
    assert payload["executed_workload_count"] == 1
    assert payload["skipped_existing_passed_count"] == 0
    assert payload["rows"][0]["action"] == "executed"
    assert payload["rows"][0]["ignored_resume_result_path"].endswith("_previous.json")
    assert payload["rows"][0]["ignored_resume_fingerprint_validation"]["passed"] is False
    assert payload["all_selected_workloads_passed"] is True


def test_cloud_runbook_renders_canary_full_and_collection_scripts(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    canary_plan = {
        "claim_scope": "canary",
        "profile": "thesis",
        "seed": 2026,
        "solver": "h48h7",
        "worker_threads": 8,
        "recommended_minimum_cloud_machine": {
            "cpu_count": 16,
            "memory_gib": 64,
            "local_nvme_gib": 250,
        },
        "workloads": [],
    }
    full_plan = {
        "claim_scope": "full",
        "profile": "thesis",
        "seed": 2026,
        "solver": "h48h7",
        "worker_threads": 16,
        "recommended_minimum_cloud_machine": {
            "cpu_count": 16,
            "memory_gib": 64,
            "local_nvme_gib": 250,
        },
        "workloads": [],
    }
    canary_path = processed / "canary_plan.json"
    full_path = processed / "full_plan.json"
    canary_path.write_text(json.dumps(canary_plan), encoding="utf-8")
    full_path.write_text(json.dumps(full_plan), encoding="utf-8")

    payload, output = build_cloud_hardtail_runbook(
        root=root,
        canary_plan_path=canary_path,
        full_plan_path=full_path,
        output_dir=Path("results/cloud_hardtail_runbook_test"),
        run_suffix="cloud_test",
        timeout_scale=1.5,
    )

    assert output.exists()
    assert payload["status"] == "runbook_generated_not_runtime_evidence"
    assert payload["default_threads"] == 16
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    run_canary = root / payload["generated_files"]["run_canary"]
    dry_run_canary = root / payload["generated_files"]["dry_run_canary"]
    run_full = root / payload["generated_files"]["run_full"]
    evaluate_full = root / payload["generated_files"]["evaluate_full"]
    collect_results = root / payload["generated_files"]["collect_results"]
    bootstrap = root / payload["generated_files"]["bootstrap_cloud_machine"]
    end_to_end = root / payload["generated_files"]["run_end_to_end_single_machine"]
    readme = root / payload["generated_files"]["readme"]

    assert run_canary.stat().st_mode & 0o111
    assert bootstrap.stat().st_mode & 0o111
    assert end_to_end.stat().st_mode & 0o111
    bootstrap_text = bootstrap.read_text(encoding="utf-8")
    assert '"$BOOTSTRAP_PYTHON" -m venv "$ROOT/.venv"' in bootstrap_text
    assert "python -m pip install -e \".[dev]\"" in bootstrap_text
    assert "python -m rubik_optimal.cli --help" in bootstrap_text
    assert "scripts/cloud_hardtail_preflight.py" in bootstrap_text
    assert "--artifact-suffix cloud_test_bootstrap" in bootstrap_text
    run_canary_text = run_canary.read_text(encoding="utf-8")
    assert '.venv/bin/activate' in run_canary_text
    assert "scripts/cloud_hardtail_preflight.py" in run_canary_text
    assert "scripts/run_cloud_hardtail_campaign.py" in run_canary_text
    assert run_canary_text.index("scripts/cloud_hardtail_preflight.py") < run_canary_text.index(
        "scripts/run_cloud_hardtail_campaign.py"
    )
    assert "--resume --stop-on-fail --use-estimated-timeouts" in run_canary_text
    assert "--timeout-scale 1.5" in run_canary_text
    assert "--dry-run" not in run_canary_text
    assert "--dry-run" in dry_run_canary.read_text(encoding="utf-8")
    run_full_text = run_full.read_text(encoding="utf-8")
    assert '.venv/bin/activate' in run_full_text
    assert "full_plan.json" in run_full_text
    assert "scripts/cloud_hardtail_preflight.py" in run_full_text
    assert run_full_text.index("scripts/cloud_hardtail_preflight.py") < run_full_text.index(
        "scripts/run_cloud_hardtail_campaign.py"
    )
    assert "scripts/evaluate_cloud_hardtail_campaign.py" in evaluate_full.read_text(encoding="utf-8")
    assert "cloud_hardtail_artifacts_cloud_test.tar.gz" in collect_results.read_text(encoding="utf-8")
    end_to_end_text = end_to_end.read_text(encoding="utf-8")
    assert "./bootstrap_cloud_machine.sh" in end_to_end_text
    assert "./preflight_leader.sh" in end_to_end_text
    assert end_to_end_text.index("./bootstrap_cloud_machine.sh") < end_to_end_text.index(
        "./preflight_leader.sh"
    )
    assert "./run_canary.sh" in end_to_end_text
    assert "./run_full.sh" in end_to_end_text
    assert "./evaluate_full.sh" in end_to_end_text
    assert "./collect_results.sh" in end_to_end_text
    assert "./run_full_prerequisites.sh" not in end_to_end_text
    readme_text = readme.read_text(encoding="utf-8")
    assert "bootstrap_cloud_machine.sh" in readme_text
    assert "run_end_to_end_single_machine.sh" in readme_text
    assert "run_canary.sh" in readme_text


def test_cloud_runbook_splits_full_hardtail_shards_across_machines(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    canary_path = processed / "canary_plan.json"
    full_path = processed / "full_plan.json"
    canary_path.write_text(
        json.dumps(
            {
                "claim_scope": "canary",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h7",
                "worker_threads": 16,
                "recommended_minimum_cloud_machine": {"cpu_count": 16, "memory_gib": 64},
                "workloads": [],
            }
        ),
        encoding="utf-8",
    )
    full_workloads = [
        {
            "id": f"known_distance_20_shard_{index:03d}",
            "kind": "public_known_distance_hardtail_sweep",
            "estimated_wall_seconds": 6660.0,
        }
        for index in range(5)
    ]
    full_workloads.extend(
        [
            {
                "id": "stronger_table_h48h8",
                "kind": "h48_stronger_table_generation_and_certification",
                "estimated_wall_seconds": 21600.0,
            },
            {
                "id": "rubikoptimal_superflip_hardcase",
                "kind": "rubikoptimal_table_complete_hardcase",
                "estimated_wall_seconds": 900.0,
            },
            {
                "id": "postprocess_00",
                "kind": "postprocess_and_audit",
                "estimated_wall_seconds": 300.0,
            },
        ]
    )
    full_path.write_text(
        json.dumps(
            {
                "claim_scope": "full",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h7",
                "worker_threads": 16,
                "recommended_minimum_cloud_machine": {"cpu_count": 16, "memory_gib": 64},
                "workloads": full_workloads,
            }
        ),
        encoding="utf-8",
    )

    payload, _output = build_cloud_hardtail_runbook(
        root=root,
        canary_plan_path=canary_path,
        full_plan_path=full_path,
        output_dir=Path("results/cloud_hardtail_runbook_parallel"),
        run_suffix="parallel_test",
        timeout_scale=1.25,
        parallel_machines=3,
    )

    assert payload["parallel_machine_count"] == 3
    assert len(payload["parallel_assignments"]) == 3
    assigned = {
        workload_id
        for group in payload["parallel_assignments"]
        for workload_id in group["workload_ids"]
    }
    assert assigned == {f"known_distance_20_shard_{index:03d}" for index in range(5)}
    assert payload["parallel_estimate"]["estimated_wall_hours_scaled"] < 8.0

    machine_0 = root / payload["generated_files"]["run_full_machine_00"]
    machine_0_text = machine_0.read_text(encoding="utf-8")
    assert "--workload-id known_distance_20_shard_" in machine_0_text
    assert "--no-evaluate" in machine_0_text
    assert "known_distance_20_shard_000" in machine_0_text

    nonshard = root / payload["generated_files"]["run_full_nonshard"]
    nonshard_text = nonshard.read_text(encoding="utf-8")
    assert "--workload-id stronger_table_h48h8" in nonshard_text
    assert "--workload-id rubikoptimal_superflip_hardcase" in nonshard_text

    finalize = root / payload["generated_files"]["finalize_full_after_collect"]
    finalize_text = finalize.read_text(encoding="utf-8")
    assert "--kind postprocess_and_audit" in finalize_text
    assert "cloud_hardtail_campaign.py" in finalize_text
    assert "generate_h48_oracle_contract.py" in finalize_text
    assert "parallel_test_precontract" in finalize_text
    assert "scripts/thesis_audit.py" in finalize_text

    readme = (root / payload["generated_files"]["readme"]).read_text(encoding="utf-8")
    assert "Parallel full-campaign option" in readme
    assert "run_full_machine_XX.sh" in readme


def test_cloud_runbook_exposes_h48h8_prerequisite_distribution(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    canary_path = processed / "canary_plan.json"
    full_path = processed / "full_plan.json"
    canary_path.write_text(
        json.dumps(
            {
                "claim_scope": "canary",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h8",
                "worker_threads": 16,
                "recommended_minimum_cloud_machine": {"cpu_count": 16, "memory_gib": 64},
                "workloads": [],
            }
        ),
        encoding="utf-8",
    )
    full_path.write_text(
        json.dumps(
            {
                "claim_scope": "full",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h8",
                "worker_threads": 16,
                "requires_table_distribution_before_hardtail": True,
                "hardtail_prerequisite_workload_ids": ["stronger_table_h48h8"],
                "recommended_minimum_cloud_machine": {"cpu_count": 16, "memory_gib": 64},
                "workloads": [
                    {
                        "id": "stronger_table_h48h8",
                        "kind": "h48_stronger_table_generation_and_certification",
                        "estimated_wall_seconds": 21600.0,
                        "expected_artifacts": [
                            "results/processed/h48_metadata_seed_2026_thesis_h48h8.json",
                            "data/generated/h48/thesis_seed_2026/h48h8.bin",
                        ],
                    },
                    {
                        "id": "known_distance_20_shard_000",
                        "kind": "public_known_distance_hardtail_batch",
                        "estimated_wall_seconds": 6660.0,
                        "depends_on_workload_ids": ["stronger_table_h48h8"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    payload, _output = build_cloud_hardtail_runbook(
        root=root,
        canary_plan_path=canary_path,
        full_plan_path=full_path,
        output_dir=Path("results/cloud_hardtail_runbook_h48h8"),
        run_suffix="h48h8_test",
        timeout_scale=1.25,
        parallel_machines=1,
    )

    assert payload["solver"] == "h48h8"
    assert payload["execution_environment"] == "generic_large_machine_or_approved_cloud"
    assert payload["aws_required"] is False
    assert payload["nonaws_generic_ssh_supported"] is True
    assert payload["nonaws_entrypoint"] == "scripts/run_h48_fasttarget_nonaws_proof.py"
    assert "AWS helper scripts are not required" in payload["aws_account_boundary_note"]
    assert payload["full_plan_summary"]["claim_scope"] == "full"
    assert payload["full_plan_summary"]["solver"] == "h48h8"
    assert payload["full_plan_summary"]["workload_count"] == 2
    assert payload["full_plan_summary"]["required_workload_count"] == 2
    assert payload["full_plan_summary"]["required_workload_ids"] == [
        "stronger_table_h48h8",
        "known_distance_20_shard_000",
    ]
    assert payload["full_plan_summary"]["requires_table_distribution_before_hardtail"] is True
    assert payload["full_plan_summary"]["recommended_minimum_machine"]["cpu_count"] == 16
    assert payload["parallel_estimate"]["prerequisite_hours_raw"] == 6.0
    assert payload["parallel_estimate"]["hardtail_stage_hours_raw"] == 1.85
    assert payload["parallel_estimate"]["steady_state_after_prerequisites_hours_scaled"] == 2.312
    assert payload["parallel_estimate"]["estimated_wall_hours_scaled"] == 9.812
    assert "bootstrap_cloud_machine" in payload["generated_files"]
    assert "preflight_leader" in payload["generated_files"]
    assert "run_full_prerequisites" in payload["generated_files"]
    assert "preflight_worker" in payload["generated_files"]
    assert "validate_prerequisite_tables" in payload["generated_files"]
    assert "recover_prerequisite_metadata" in payload["generated_files"]
    assert "collect_prerequisite_tables" in payload["generated_files"]
    assert "collect_prerequisite_table_parts" in payload["generated_files"]
    assert "install_prerequisite_tables" in payload["generated_files"]
    assert "run_end_to_end_single_machine" in payload["generated_files"]
    leader_preflight = (root / payload["generated_files"]["preflight_leader"]).read_text(encoding="utf-8")
    assert "scripts/cloud_hardtail_preflight.py" in leader_preflight
    assert "--artifact-suffix h48h8_test_leader" in leader_preflight
    prereq = (root / payload["generated_files"]["run_full_prerequisites"]).read_text(encoding="utf-8")
    assert "scripts/cloud_hardtail_preflight.py" in prereq
    assert "--workload-id stronger_table_h48h8" in prereq
    assert prereq.index("scripts/cloud_hardtail_preflight.py") < prereq.index(
        "scripts/run_cloud_hardtail_campaign.py"
    )
    worker_preflight = (root / payload["generated_files"]["preflight_worker"]).read_text(encoding="utf-8")
    assert "scripts/cloud_hardtail_preflight.py" in worker_preflight
    assert "--require-target-table" in worker_preflight
    assert "--artifact-suffix h48h8_test_worker" in worker_preflight
    validate = (root / payload["generated_files"]["validate_prerequisite_tables"]).read_text(encoding="utf-8")
    assert "scripts/validate_h48_worker_table.py" in validate
    assert "--solver h48h8" in validate
    assert "--artifact-suffix h48h8_test_worker" in validate
    assert "--persistent-cache" in validate
    collect = (root / payload["generated_files"]["collect_prerequisite_tables"]).read_text(encoding="utf-8")
    assert "cloud_hardtail_prerequisite_tables_h48h8_test.tar.gz" in collect
    assert "data/generated/h48/thesis_seed_2026/h48h8.bin" in collect
    assert "results/processed/h48_worker_table_validation_*.json" in collect
    assert "results/processed/cloud_hardtail_preflight_*.json" in collect
    collect_parts = (root / payload["generated_files"]["collect_prerequisite_table_parts"]).read_text(
        encoding="utf-8"
    )
    assert "scripts/create_h48_table_bundle.py" in collect_parts
    assert "--solver h48h8" in collect_parts
    assert "cloud_hardtail_prerequisite_tables_h48h8_test_parts" in collect_parts
    assert "H48_TABLE_BUNDLE_PART_SIZE_MIB" in collect_parts
    assert "--artifact-suffix h48h8_test_prerequisite_parts" in collect_parts
    installer = (root / payload["generated_files"]["install_prerequisite_tables"]).read_text(
        encoding="utf-8"
    )
    assert "scripts/install_h48_table_bundle.py" in installer
    assert "--solver h48h8" in installer
    assert "--bundle \"$1\"" in installer
    assert "--artifact-suffix h48h8_test_worker_install" in installer
    recover = (root / payload["generated_files"]["recover_prerequisite_metadata"]).read_text(
        encoding="utf-8"
    )
    assert "scripts/generate_h48_tables.py" in recover
    assert "--adopt-existing-table-metadata" in recover
    assert "scripts/validate_h48_worker_table.py" in recover
    assert "--persistent-cache" in recover
    assert "staged partial" in recover
    assert ".h48h8.bin.partial" in recover
    assert 'H48_TABLE_ROOT="${RUBIK_OPTIMAL_H48_TABLE_ROOT:-data/generated/h48}"' in recover
    assert 'TABLE="$H48_TABLE_ROOT"/thesis_seed_2026/h48h8.bin' in recover
    end_to_end = (root / payload["generated_files"]["run_end_to_end_single_machine"]).read_text(
        encoding="utf-8"
    )
    assert end_to_end.index("./preflight_leader.sh") < end_to_end.index("./run_canary.sh")
    assert end_to_end.index("./bootstrap_cloud_machine.sh") < end_to_end.index(
        "./preflight_leader.sh"
    )
    assert end_to_end.index("./run_canary.sh") < end_to_end.index("./run_full_prerequisites.sh")
    assert end_to_end.index("./run_full_prerequisites.sh") < end_to_end.index("./preflight_worker.sh")
    assert end_to_end.index("./preflight_worker.sh") < end_to_end.index(
        "./validate_prerequisite_tables.sh"
    )
    assert end_to_end.index("./validate_prerequisite_tables.sh") < end_to_end.index("./run_full.sh")
    assert end_to_end.index("./run_full.sh") < end_to_end.index("./evaluate_full.sh")
    assert end_to_end.index("./evaluate_full.sh") < end_to_end.index("./collect_results.sh")
    assert end_to_end.index("./collect_results.sh") < end_to_end.index(
        "./finalize_full_after_collect.sh"
    )
    run_full = (root / payload["generated_files"]["run_full"]).read_text(encoding="utf-8")
    assert "scripts/cloud_hardtail_preflight.py" in run_full
    assert "scripts/validate_h48_worker_table.py" in run_full
    assert "--persistent-cache" in run_full
    assert "--require-target-table" in run_full
    assert run_full.index("scripts/cloud_hardtail_preflight.py") < run_full.index(
        "scripts/validate_h48_worker_table.py"
    )
    assert run_full.index("scripts/validate_h48_worker_table.py") < run_full.index(
        "scripts/run_cloud_hardtail_campaign.py"
    )
    worker = (root / payload["generated_files"]["run_full_machine_00"]).read_text(encoding="utf-8")
    assert "scripts/cloud_hardtail_preflight.py" in worker
    assert "scripts/validate_h48_worker_table.py" in worker
    assert "scripts/run_cloud_hardtail_campaign.py" in worker
    assert "--artifact-suffix h48h8_test_m00_worker" in worker
    assert "--persistent-cache" in worker
    assert worker.index("scripts/cloud_hardtail_preflight.py") < worker.index(
        "scripts/validate_h48_worker_table.py"
    )
    assert worker.index("scripts/validate_h48_worker_table.py") < worker.index(
        "scripts/run_cloud_hardtail_campaign.py"
    )
    readme = (root / payload["generated_files"]["readme"]).read_text(encoding="utf-8")
    assert "Large-machine hard-tail campaign runbook" in readme
    assert "AWS is not required by this runbook" in readme
    assert "generic SSH/non-AWS wrapper" in readme
    assert "bootstrap_cloud_machine.sh" in readme
    assert "preflight_leader.sh" in readme
    assert "run_end_to_end_single_machine.sh" in readme
    assert "preflight_worker.sh" in readme
    assert "run_full_prerequisites.sh" in readme
    assert "install_prerequisite_tables.sh" in readme
    assert "collect_prerequisite_table_parts.sh" in readme
    assert "split-parts directory" in readme
    assert "validate_prerequisite_tables.sh" in readme
    assert "recover_prerequisite_metadata.sh" in readme
    assert "copy that archive to every hard-tail worker" in readme
    assert "post-prerequisite budget" in readme
    assert "h48_worker_table_validation_*.json" in readme
    assert "h48_oracle_contract_seed_2026_thesis_h48h8.json" in readme


def test_cloud_runbook_reuses_shared_h48_prerequisite_before_canary(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    shared_prereq = {
        "id": "stronger_table_h48h10",
        "kind": "h48_stronger_table_generation_and_certification",
        "estimated_wall_seconds": 43200.0,
        "command_args": [
            "python",
            "scripts/run_h48_stronger_table_campaign.py",
            "--target-solver",
            "h48h10",
            "--artifact-suffix",
            "shared_h48h10",
        ],
        "expected_artifacts": [
            "results/processed/h48_stronger_table_campaign_seed_2026_thesis_h48h10_shared_h48h10.json",
            "results/processed/h48_metadata_seed_2026_thesis_h48h10.json",
            "data/generated/h48/thesis_seed_2026/h48h10.bin",
        ],
    }
    canary_path = processed / "canary_plan.json"
    full_path = processed / "full_plan.json"
    canary_path.write_text(
        json.dumps(
            {
                "claim_scope": "canary",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "worker_threads": 16,
                "requires_table_distribution_before_hardtail": True,
                "hardtail_prerequisite_workload_ids": ["stronger_table_h48h10"],
                "recommended_minimum_cloud_machine": {"cpu_count": 16, "memory_gib": 64},
                "workloads": [
                    shared_prereq,
                    {
                        "id": "known_distance_20_shard_000",
                        "kind": "public_known_distance_hardtail_batch",
                        "estimated_wall_seconds": 270.0,
                        "depends_on_workload_ids": ["stronger_table_h48h10"],
                    },
                    {
                        "id": "postprocess_00",
                        "kind": "postprocess_and_audit",
                        "estimated_wall_seconds": 300.0,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    full_path.write_text(
        json.dumps(
            {
                "claim_scope": "full",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "worker_threads": 16,
                "requires_table_distribution_before_hardtail": True,
                "hardtail_prerequisite_workload_ids": ["stronger_table_h48h10"],
                "recommended_minimum_cloud_machine": {"cpu_count": 16, "memory_gib": 64},
                "workloads": [
                    shared_prereq,
                    {
                        "id": "known_distance_20_shard_000",
                        "kind": "public_known_distance_hardtail_batch",
                        "estimated_wall_seconds": 900.0,
                        "depends_on_workload_ids": ["stronger_table_h48h10"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    payload, _output = build_cloud_hardtail_runbook(
        root=root,
        canary_plan_path=canary_path,
        full_plan_path=full_path,
        output_dir=Path("results/cloud_hardtail_runbook_shared"),
        run_suffix="shared_prereq",
        timeout_scale=1.25,
        parallel_machines=1,
    )

    assert payload["shared_canary_prerequisite_ids"] == ["stronger_table_h48h10"]
    assert payload["canary_reuses_full_prerequisites"] is True
    assert "run_canary_after_prerequisites" in payload["generated_files"]
    assert payload["single_machine_run_order"] == [
        "bootstrap_cloud_machine",
        "preflight_leader",
        "run_full_prerequisites",
        "preflight_worker",
        "validate_prerequisite_tables",
        "run_canary_after_prerequisites",
        "run_full",
        "evaluate_full",
        "collect_results",
        "finalize_full_after_collect",
    ]
    assert payload["manual_staged_run_order"] == payload["run_order"]
    assert "run_end_to_end_single_machine" not in payload["manual_staged_run_order"]
    assert payload["manual_staged_run_order"].index("bootstrap_cloud_machine") < payload[
        "manual_staged_run_order"
    ].index("preflight_leader")
    assert payload["manual_staged_run_order"].index("run_full_prerequisites") < payload[
        "manual_staged_run_order"
    ].index("run_canary_after_prerequisites")
    canary_after = (root / payload["generated_files"]["run_canary_after_prerequisites"]).read_text(
        encoding="utf-8"
    )
    assert "--workload-id known_distance_20_shard_000" in canary_after
    assert "--workload-id postprocess_00" in canary_after
    assert "--workload-id stronger_table_h48h10" not in canary_after

    end_to_end = (root / payload["generated_files"]["run_end_to_end_single_machine"]).read_text(
        encoding="utf-8"
    )
    assert end_to_end.index("./bootstrap_cloud_machine.sh") < end_to_end.index(
        "./preflight_leader.sh"
    )
    assert end_to_end.index("./run_full_prerequisites.sh") < end_to_end.index(
        "./run_canary_after_prerequisites.sh"
    )
    assert "./run_canary.sh" not in end_to_end
    assert payload["run_order"].index("run_full_prerequisites") < payload["run_order"].index(
        "run_canary_after_prerequisites"
    )
    assert payload["run_order"].count("run_full_prerequisites") == 1
    readme = (root / payload["generated_files"]["readme"]).read_text(encoding="utf-8")
    assert "run_canary_after_prerequisites.sh" in readme
    assert "Do not run `run_canary.sh` after the shared prerequisite path" in readme
    assert "not run once under the canary artifact name and again under the full-plan artifact name" in readme


def _write_remote_full_runbook_manifest(root: Path) -> Path:
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    generated_files = {
        "preflight_leader": "preflight_leader.sh",
        "run_full_prerequisites": "run_full_prerequisites.sh",
        "collect_prerequisite_tables": "collect_prerequisite_tables.sh",
        "collect_prerequisite_table_parts": "collect_prerequisite_table_parts.sh",
        "preflight_worker": "preflight_worker.sh",
        "validate_prerequisite_tables": "validate_prerequisite_tables.sh",
        "run_canary_after_prerequisites": "run_canary_after_prerequisites.sh",
        "run_full": "run_full.sh",
        "evaluate_full": "evaluate_full.sh",
        "collect_results": "collect_results.sh",
        "unpack_results": "unpack_results.sh",
        "finalize_full_after_collect": "finalize_full_after_collect.sh",
    }
    for name in generated_files.values():
        (runbook_dir / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "recommended_minimum_cloud_machine": {
                    "h48_target_table_size_bytes": 30336314216,
                },
                "generated_files": {
                    key: f"results/cloud_hardtail_runbook_remote_test/{name}"
                    for key, name in generated_files.items()
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def _write_archive_validation_fixture(
    root: Path,
    *,
    include_second_workload: bool,
    stale_second_workload_fingerprint: bool = False,
    evaluation_overrides: dict | None = None,
) -> tuple[Path, Path]:
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    plan_path = processed / "cloud_hardtail_campaign_plan_seed_2026_thesis_h48h10_full.json"
    plan = {
        "objective": "test full archive validation",
        "claim_scope": "full",
        "profile": "thesis",
        "seed": 2026,
        "solver": "h48h10",
        "distance": 20,
        "workloads": [
            {
                "id": "stronger_table_h48h10",
                "kind": "h48_stronger_table_generation_and_certification",
                "required_for_fast_every_state_claim": True,
                "expected_artifacts": [
                    "results/processed/h48_metadata_seed_2026_thesis_h48h10.json",
                ],
            },
            {
                "id": "known_distance_20_shard_000",
                "kind": "public_known_distance_hardtail_batch",
                "required_for_fast_every_state_claim": True,
                "expected_artifacts": [
                    "results/processed/universal_oracle_cli_seed_2026_thesis_h48h10_archive_fixture_d20.json",
                ],
            },
            {
                "id": "optional_probe",
                "kind": "diagnostic",
                "required_for_fast_every_state_claim": False,
            },
        ],
    }
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "full_plan_path": "results/processed/cloud_hardtail_campaign_plan_seed_2026_thesis_h48h10_full.json",
                "generated_files": {},
            }
        ),
        encoding="utf-8",
    )
    member_root = root / "tmp" / "archive_members"
    member_dir = member_root / "results" / "processed"
    member_dir.mkdir(parents=True, exist_ok=True)
    plan_stem = plan_path.stem

    artifact_payloads = {
        "results/processed/h48_metadata_seed_2026_thesis_h48h10.json": {
            "trusted_table": True,
        },
        "results/processed/universal_oracle_cli_seed_2026_thesis_h48h10_archive_fixture_d20.json": {
            "passed": True,
            "rows": [{"status": "exact", "verified": True}],
        },
    }
    for relpath, payload in artifact_payloads.items():
        path = member_root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    required_workloads = [
        workload for workload in plan["workloads"] if workload.get("required_for_fast_every_state_claim", True)
    ]
    workload_payloads = {}
    for workload in required_workloads:
        matched = {
            pattern: [pattern]
            for pattern in workload.get("expected_artifacts", [])
        }
        payload = _fingerprinted_workload_result(
            plan,
            workload,
            root=member_root,
            dry_run=False,
            expected_artifacts_found=True,
            matched_artifacts_by_pattern=matched,
            artifact_summaries=[
                {"path": pattern}
                for pattern in workload.get("expected_artifacts", [])
            ],
            required_for_fast_every_state_claim=True,
        )
        workload_payloads[workload["id"]] = payload
    if stale_second_workload_fingerprint:
        workload_payloads["known_distance_20_shard_000"]["workload_fingerprint"] = "stale"

    evaluation_payload = {
        "schema_version": 1,
        "plan_path": "results/processed/cloud_hardtail_campaign_plan_seed_2026_thesis_h48h10_full.json",
        "plan_claim_scope": "full",
        "plan_profile": "thesis",
        "plan_seed": 2026,
        "plan_solver": "h48h10",
        "plan_distance": 20,
        "workload_count": len(plan["workloads"]),
        "evaluated_workload_count": len(plan["workloads"]),
        "all_required_workloads_passed": True,
        "artifact_integrity_required_workload_count": 2,
        "artifact_integrity_passed_workload_count": 2,
        "all_required_artifact_integrity_passed": True,
        "cloud_runtime_evidence_passed": True,
        "fast_runtime_proven_for_every_possible_state": False,
        "rows": [
            {
                "workload_id": workload["id"],
                "kind": workload["kind"],
                "required": workload.get("required_for_fast_every_state_claim", True),
                "passed": True,
            }
            for workload in plan["workloads"]
        ],
        "missing_or_failed_workloads": [],
    }
    evaluation_payload.update(evaluation_overrides or {})

    (member_dir / f"cloud_hardtail_campaign_evaluation_{plan_stem}_remote_test.json").write_text(
        json.dumps(evaluation_payload),
        encoding="utf-8",
    )
    (member_dir / f"cloud_hardtail_workload_{plan_stem}_stronger_table_h48h10_remote_test.json").write_text(
        json.dumps(workload_payloads["stronger_table_h48h10"]),
        encoding="utf-8",
    )
    if include_second_workload:
        (
            member_dir
            / f"cloud_hardtail_workload_{plan_stem}_known_distance_20_shard_000_remote_test.json"
        ).write_text(
            json.dumps(workload_payloads["known_distance_20_shard_000"]),
            encoding="utf-8",
        )
    archive = root / "results" / "cloud_hardtail_artifacts_remote_test.tar.gz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(member_root.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=str(path.relative_to(member_root)))
    return manifest_path, archive


def test_cloud_hardtail_archive_validator_requires_full_plan_workloads(tmp_path):
    root = tmp_path
    manifest_path, archive = _write_archive_validation_fixture(
        root,
        include_second_workload=True,
    )

    payload = validate_archive(root=root, runbook_path=manifest_path, archive_path=archive)

    assert payload["passed"] is True
    assert payload["required_pattern_count"] == 3
    assert payload["missing_required_pattern_count"] == 0
    assert payload["unsafe_member_count"] == 0
    assert payload["evaluation_payload_valid"] is True
    assert payload["workload_payload_passed_count"] == 2
    assert payload["archive_artifact_check_count"] == 2
    assert payload["archive_artifact_passed_count"] == 2


def test_cloud_hardtail_archive_validator_rejects_missing_required_workload(tmp_path):
    root = tmp_path
    manifest_path, archive = _write_archive_validation_fixture(
        root,
        include_second_workload=False,
    )

    payload = validate_archive(root=root, runbook_path=manifest_path, archive_path=archive)

    assert payload["passed"] is False
    assert payload["missing_required_pattern_count"] == 1
    assert payload["missing_required_patterns"][0]["workload_id"] == "known_distance_20_shard_000"
    assert "archive is missing required full-plan proof artifacts" in payload["errors"]
    assert "archive workload payloads do not match full-plan fingerprints or execution requirements" in payload["errors"]


def test_cloud_hardtail_archive_validator_rejects_stale_workload_fingerprint(tmp_path):
    root = tmp_path
    manifest_path, archive = _write_archive_validation_fixture(
        root,
        include_second_workload=True,
        stale_second_workload_fingerprint=True,
    )

    payload = validate_archive(root=root, runbook_path=manifest_path, archive_path=archive)

    assert payload["passed"] is False
    assert payload["missing_required_pattern_count"] == 0
    failed = [
        check for check in payload["workload_payload_checks"]
        if check["workload_id"] == "known_distance_20_shard_000"
    ][0]
    assert failed["passed"] is False
    assert "workload fingerprint mismatch" in failed["candidates"][0]["reasons"]


def test_cloud_hardtail_archive_validator_rejects_failed_evaluation_payload(tmp_path):
    root = tmp_path
    manifest_path, archive = _write_archive_validation_fixture(
        root,
        include_second_workload=True,
        evaluation_overrides={
            "all_required_workloads_passed": False,
            "cloud_runtime_evidence_passed": False,
            "missing_or_failed_workloads": ["known_distance_20_shard_000"],
            "rows": [
                {
                    "workload_id": "stronger_table_h48h10",
                    "kind": "h48_stronger_table_generation_and_certification",
                    "required": True,
                    "passed": True,
                },
                {
                    "workload_id": "known_distance_20_shard_000",
                    "kind": "public_known_distance_hardtail_batch",
                    "required": True,
                    "passed": False,
                },
                {
                    "workload_id": "optional_probe",
                    "kind": "diagnostic",
                    "required": False,
                    "passed": True,
                },
            ],
        },
    )

    payload = validate_archive(root=root, runbook_path=manifest_path, archive_path=archive)

    assert payload["passed"] is False
    assert payload["evaluation_payload_valid"] is False
    assert "archive campaign evaluation payload does not prove full-plan runtime evidence" in payload["errors"]
    assert payload["workload_payload_passed_count"] == 2


def test_h48_fasttarget_remote_runner_bootstraps_before_preflight_when_available(tmp_path):
    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    for name in ["bootstrap_cloud_machine.sh", "preflight_leader.sh"]:
        (runbook_dir / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "generated_files": {
                    "bootstrap_cloud_machine": (
                        "results/cloud_hardtail_runbook_remote_test/bootstrap_cloud_machine.sh"
                    ),
                    "preflight_leader": (
                        "results/cloud_hardtail_runbook_remote_test/preflight_leader.sh"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    steps, _context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="preflight",
    )

    step_ids = [step["id"] for step in steps]
    assert step_ids == [
        "remote_prepare",
        "sync_repo_to_remote",
        "remote_bootstrap_cloud_machine",
        "remote_preflight_leader",
        "fetch_processed_artifacts",
    ]
    assert "bootstrap_cloud_machine.sh" in steps[2]["command"][-1]
    assert "preflight_leader.sh" in steps[3]["command"][-1]


def test_h48_fasttarget_remote_runner_builds_sync_run_fetch_finalize_commands(tmp_path):
    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    for name in [
        "run_end_to_end_single_machine.sh",
        "unpack_results.sh",
        "finalize_full_after_collect.sh",
    ]:
        path = runbook_dir / name
        path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "recommended_minimum_cloud_machine": {
                    "cpu_count": 16,
                    "memory_gib": 64,
                    "local_nvme_gib": 250,
                },
                "parallel_estimate": {"estimated_wall_hours_scaled": 19.41},
                "generated_files": {
                    "collect_prerequisite_tables": (
                        "results/cloud_hardtail_runbook_remote_test/collect_prerequisite_tables.sh"
                    ),
                    "run_end_to_end_single_machine": (
                        "results/cloud_hardtail_runbook_remote_test/run_end_to_end_single_machine.sh"
                    ),
                    "unpack_results": "results/cloud_hardtail_runbook_remote_test/unpack_results.sh",
                    "finalize_full_after_collect": (
                        "results/cloud_hardtail_runbook_remote_test/finalize_full_after_collect.sh"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        port=2222,
        identity_file=Path("~/.ssh/cube.pem"),
        ssh_options=["StrictHostKeyChecking=no"],
    )

    assert context["run_suffix"] == "remote_test"
    assert context["solver"] == "h48h10"
    assert context["remote_action"] == "end-to-end"
    assert context["results_archive"] == "results/cloud_hardtail_artifacts_remote_test.tar.gz"
    assert (
        context["prerequisite_tables_archive"]
        == "results/cloud_hardtail_prerequisite_tables_remote_test.tar.gz"
    )
    assert context["fetch_diagnostics_on_fail"] is True
    assert "results/processed/" in context["diagnostic_fetch_command"]
    assert "results/processed/" in context["fetch_processed_command"]
    assert "ubuntu@cube-box:/mnt/sgarbas-h48/results/processed/" in context["diagnostic_fetch_command"]
    assert [step["id"] for step in steps] == [
        "remote_prepare",
        "sync_repo_to_remote",
        "remote_run_end_to_end",
        "fetch_results_archive",
        "validate_results_archive",
        "unpack_results_archive",
        "finalize_after_collect",
    ]
    sync = steps[1]["command"]
    assert sync[0] == "rsync"
    assert "--exclude" in sync
    assert f"{root}/" in sync
    assert sync[-1] == "ubuntu@cube-box:/mnt/sgarbas-h48/"
    remote_run = steps[2]["command"]
    assert remote_run[:2] == ["ssh", "-p"]
    assert "ubuntu@cube-box" in remote_run
    assert "cd /mnt/sgarbas-h48" in remote_run[-1]
    assert "run_end_to_end_single_machine.sh" in remote_run[-1]
    fetch = steps[3]["command"]
    assert "ubuntu@cube-box:/mnt/sgarbas-h48/results/cloud_hardtail_artifacts_remote_test.tar.gz" in fetch
    assert any("validate_cloud_hardtail_archive.py" in part for part in steps[4]["command"])
    assert steps[4]["archive"] == "results/cloud_hardtail_artifacts_remote_test.tar.gz"
    assert steps[5]["command"][-1] == "results/cloud_hardtail_artifacts_remote_test.tar.gz"
    assert "finalize_full_after_collect.sh" in steps[6]["command"][-1]


def test_h48_fasttarget_remote_runner_can_run_preflight_only(tmp_path):
    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    preflight = runbook_dir / "preflight_leader.sh"
    preflight.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "generated_files": {
                    "preflight_leader": (
                        "results/cloud_hardtail_runbook_remote_test/preflight_leader.sh"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="preflight",
    )

    assert context["remote_action"] == "preflight"
    assert [step["id"] for step in steps] == [
        "remote_prepare",
        "sync_repo_to_remote",
        "remote_preflight_leader",
        "fetch_processed_artifacts",
    ]
    assert "preflight_leader.sh" in steps[2]["command"][-1]
    assert "ubuntu@cube-box:/mnt/sgarbas-h48/results/processed/" in steps[3]["command"]
    assert all("run_full_prerequisites.sh" not in " ".join(step["command"]) for step in steps)
    assert all("run_full.sh" not in " ".join(step["command"]) for step in steps)
    assert all("finalize_full_after_collect" not in " ".join(step["command"]) for step in steps)


def test_h48_fasttarget_remote_runner_can_recover_prerequisite_metadata(tmp_path):
    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    for name in [
        "bootstrap_cloud_machine.sh",
        "recover_prerequisite_metadata.sh",
    ]:
        (runbook_dir / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "generated_files": {
                    "bootstrap_cloud_machine": (
                        "results/cloud_hardtail_runbook_remote_test/bootstrap_cloud_machine.sh"
                    ),
                    "recover_prerequisite_metadata": (
                        "results/cloud_hardtail_runbook_remote_test/recover_prerequisite_metadata.sh"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="recover-prerequisite-metadata",
    )

    assert context["remote_action"] == "recover-prerequisite-metadata"
    assert [step["id"] for step in steps] == [
        "remote_prepare",
        "sync_repo_to_remote",
        "remote_bootstrap_cloud_machine",
        "remote_recover_prerequisite_metadata",
        "fetch_processed_artifacts",
    ]
    recover_command = steps[3]["command"][-1]
    assert "recover_prerequisite_metadata.sh" in recover_command
    assert "run_full_prerequisites.sh" not in recover_command
    assert "run_full.sh" not in recover_command
    assert "finalize_full_after_collect" not in recover_command
    assert "ubuntu@cube-box:/mnt/sgarbas-h48/results/processed/" in steps[4]["command"]


def test_h48_fasttarget_remote_runner_can_start_prerequisites_detached(tmp_path):
    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    for name in [
        "preflight_leader.sh",
        "run_full_prerequisites.sh",
        "collect_prerequisite_tables.sh",
    ]:
        path = runbook_dir / name
        path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "generated_files": {
                    "preflight_leader": (
                        "results/cloud_hardtail_runbook_remote_test/preflight_leader.sh"
                    ),
                    "run_full_prerequisites": (
                        "results/cloud_hardtail_runbook_remote_test/run_full_prerequisites.sh"
                    ),
                    "collect_prerequisite_tables": (
                        "results/cloud_hardtail_runbook_remote_test/collect_prerequisite_tables.sh"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="start-prerequisites",
    )

    assert context["remote_action"] == "start-prerequisites"
    assert [step["id"] for step in steps] == [
        "remote_prepare",
        "sync_repo_to_remote",
        "remote_preflight_leader",
        "remote_start_prerequisites_detached",
        "fetch_processed_artifacts",
    ]
    assert "preflight_leader.sh" in steps[2]["command"][-1]
    detached = steps[3]
    assert detached["detached"] is True
    assert "nohup bash -lc" in detached["command"][-1]
    assert "run_full_prerequisites.sh" in detached["command"][-1]
    assert "collect_prerequisite_tables.sh" in detached["command"][-1]
    assert "h48_fasttarget_remote_test_start_prerequisites.pid" in detached["command"][-1]
    assert "h48_fasttarget_remote_test_start_prerequisites_launch.json" in detached["command"][-1]
    assert "ubuntu@cube-box:/mnt/sgarbas-h48/results/processed/" in steps[4]["command"]
    assert all("run_full.sh" not in " ".join(step["command"]) for step in steps)
    assert all("finalize_full_after_collect" not in " ".join(step["command"]) for step in steps)


def test_h48_fasttarget_remote_runner_can_run_prerequisite_stage_only(tmp_path):
    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    for name in [
        "run_full_prerequisites.sh",
        "collect_prerequisite_tables.sh",
    ]:
        path = runbook_dir / name
        path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "generated_files": {
                    "run_full_prerequisites": (
                        "results/cloud_hardtail_runbook_remote_test/run_full_prerequisites.sh"
                    ),
                    "collect_prerequisite_tables": (
                        "results/cloud_hardtail_runbook_remote_test/collect_prerequisite_tables.sh"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="prerequisites",
    )

    assert context["remote_action"] == "prerequisites"
    assert [step["id"] for step in steps] == [
        "remote_prepare",
        "sync_repo_to_remote",
        "remote_run_prerequisites",
        "remote_collect_prerequisite_tables",
        "fetch_prerequisite_tables_archive",
        "fetch_processed_artifacts",
    ]
    assert "run_full_prerequisites.sh" in steps[2]["command"][-1]
    assert "collect_prerequisite_tables.sh" in steps[3]["command"][-1]
    assert (
        "ubuntu@cube-box:/mnt/sgarbas-h48/results/"
        "cloud_hardtail_prerequisite_tables_remote_test.tar.gz"
    ) in steps[4]["command"]
    assert "ubuntu@cube-box:/mnt/sgarbas-h48/results/processed/" in steps[5]["command"]
    assert all("finalize_full_after_collect" not in " ".join(step["command"]) for step in steps)


def test_h48_fasttarget_remote_runner_can_run_split_prerequisite_stage_only(tmp_path):
    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    for name in [
        "run_full_prerequisites.sh",
        "collect_prerequisite_table_parts.sh",
    ]:
        (runbook_dir / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "generated_files": {
                    "run_full_prerequisites": (
                        "results/cloud_hardtail_runbook_remote_test/run_full_prerequisites.sh"
                    ),
                    "collect_prerequisite_table_parts": (
                        "results/cloud_hardtail_runbook_remote_test/"
                        "collect_prerequisite_table_parts.sh"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="prerequisites",
        prerequisite_bundle_mode="split",
    )

    assert context["remote_action"] == "prerequisites"
    assert context["prerequisite_bundle_mode"] == "split"
    assert context["prerequisite_tables_parts_dir"] == (
        "results/cloud_hardtail_prerequisite_tables_remote_test_parts"
    )
    assert context["prerequisite_install_source"] == (
        "results/cloud_hardtail_prerequisite_tables_remote_test_parts"
    )
    assert [step["id"] for step in steps] == [
        "remote_prepare",
        "sync_repo_to_remote",
        "remote_run_prerequisites",
        "remote_collect_prerequisite_table_parts",
        "fetch_prerequisite_table_parts",
        "fetch_processed_artifacts",
    ]
    assert "collect_prerequisite_table_parts.sh" in steps[3]["command"][-1]
    assert "collect_prerequisite_tables.sh" not in steps[3]["command"][-1]
    assert (
        "ubuntu@cube-box:/mnt/sgarbas-h48/results/"
        "cloud_hardtail_prerequisite_tables_remote_test_parts/"
    ) in steps[4]["command"]
    assert all(step["id"] != "fetch_prerequisite_tables_archive" for step in steps)


def test_h48_fasttarget_remote_runner_can_run_canary_after_shared_prerequisites(tmp_path):
    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    for name in [
        "preflight_worker.sh",
        "validate_prerequisite_tables.sh",
        "run_canary_after_prerequisites.sh",
    ]:
        path = runbook_dir / name
        path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "generated_files": {
                    "preflight_worker": (
                        "results/cloud_hardtail_runbook_remote_test/preflight_worker.sh"
                    ),
                    "validate_prerequisite_tables": (
                        "results/cloud_hardtail_runbook_remote_test/validate_prerequisite_tables.sh"
                    ),
                    "run_canary_after_prerequisites": (
                        "results/cloud_hardtail_runbook_remote_test/run_canary_after_prerequisites.sh"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="canary-after-prerequisites",
    )

    assert context["remote_action"] == "canary-after-prerequisites"
    assert [step["id"] for step in steps] == [
        "remote_prepare",
        "sync_repo_to_remote",
        "remote_preflight_worker",
        "remote_validate_prerequisite_tables",
        "remote_run_canary_after_prerequisites",
        "fetch_processed_artifacts",
    ]
    assert "preflight_worker.sh" in steps[2]["command"][-1]
    assert "validate_prerequisite_tables.sh" in steps[3]["command"][-1]
    assert "run_canary_after_prerequisites.sh" in steps[4]["command"][-1]
    assert "ubuntu@cube-box:/mnt/sgarbas-h48/results/processed/" in steps[5]["command"]
    assert all("run_full_prerequisites.sh" not in " ".join(step["command"]) for step in steps)


def test_h48_fasttarget_remote_runner_can_probe_remote_status_without_sync(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "recommended_minimum_cloud_machine": {
                    "cpu_count": 16,
                    "memory_gib": 64,
                    "local_nvme_gib": 250,
                    "h48_target_table_size_bytes": 30336314216,
                },
                "generated_files": {},
            }
        ),
        encoding="utf-8",
    )

    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="status",
    )

    assert context["remote_action"] == "status"
    assert context["expected_table_size_bytes"] == 30336314216
    assert [step["id"] for step in steps] == ["remote_status"]
    status_command = steps[0]["command"][-1]
    assert "mkdir -p" not in status_command
    assert "data/generated/h48" in status_command
    assert "h48h10" in status_command
    assert "h48_metadata_seed_" in status_command
    assert "h48_oracle_contract_seed_" in status_command
    assert "cloud_hardtail_artifacts_remote_test.tar.gz" in status_command
    assert "cloud_hardtail_prerequisite_tables_remote_test.tar.gz" in status_command
    assert "target_table_size_matches_expected" in status_command
    assert "target_table_full_checksum_valid" in status_command
    assert "validate_trusted_h48_table_checksum" in status_command
    assert "contract_fast_runtime_proven_for_every_possible_state" in status_command
    assert "detached_prerequisite" in status_command
    assert "detached_full_proof" in status_command
    assert "start_prerequisites" in status_command
    assert "start_full" in status_command
    assert "os.kill(pid, 0)" in status_command
    assert "tail_max_lines" in status_command
    assert "processed_workload_artifact_count" in status_command
    assert all(step["id"] not in {"remote_prepare", "sync_repo_to_remote"} for step in steps)


def test_h48_fasttarget_remote_runner_can_wait_for_detached_prerequisites(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "recommended_minimum_cloud_machine": {
                    "h48_target_table_size_bytes": 30336314216,
                },
                "generated_files": {},
            }
        ),
        encoding="utf-8",
    )

    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="wait-prerequisites",
        prerequisite_wait_timeout_seconds=3600.0,
        prerequisite_poll_interval_seconds=45.0,
    )

    assert context["remote_action"] == "wait-prerequisites"
    assert context["prerequisite_wait_timeout_seconds"] == 3600.0
    assert context["prerequisite_poll_interval_seconds"] == 45.0
    assert [step["id"] for step in steps] == [
        "remote_wait_prerequisites",
        "fetch_prerequisite_tables_archive",
        "fetch_processed_artifacts",
    ]
    wait_command = steps[0]["command"][-1]
    assert "wait-prerequisites" not in wait_command
    assert "prerequisite_wait_timeout_seconds" in wait_command
    assert "prerequisite_poll_interval_seconds" in wait_command
    assert "start_prerequisites" in wait_command
    assert "os.kill(pid, 0)" in wait_command
    assert "ready_for_resume" in wait_command
    assert "validate_trusted_h48_table_checksum" in wait_command
    assert "persistent_cache=True" in wait_command
    assert "target_table_full_checksum_valid" in wait_command
    assert "metadata_trusted_table" in wait_command
    assert "cloud_hardtail_prerequisite_tables_remote_test.tar.gz" in wait_command
    assert "30336314216" in wait_command
    assert all(step["id"] not in {"remote_prepare", "sync_repo_to_remote"} for step in steps)


def test_h48_fasttarget_remote_runner_waits_for_split_prerequisite_parts(tmp_path):
    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "recommended_minimum_cloud_machine": {
                    "h48_target_table_size_bytes": 30336314216,
                },
                "generated_files": {},
            }
        ),
        encoding="utf-8",
    )

    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="wait-prerequisites",
        prerequisite_bundle_mode="split",
        prerequisite_wait_timeout_seconds=3600.0,
        prerequisite_poll_interval_seconds=45.0,
    )

    assert context["prerequisite_bundle_mode"] == "split"
    assert [step["id"] for step in steps] == [
        "remote_wait_prerequisites",
        "fetch_prerequisite_table_parts",
        "fetch_processed_artifacts",
    ]
    wait_command = steps[0]["command"][-1]
    assert "prerequisite_bundle_mode" in wait_command
    assert "prerequisite_tables_parts_dir" in wait_command
    assert "parts_present" in wait_command
    assert "prerequisite_transfer_ready" in wait_command
    assert "cloud_hardtail_prerequisite_tables_remote_test_parts" in wait_command
    assert (
        "ubuntu@cube-box:/mnt/sgarbas-h48/results/"
        "cloud_hardtail_prerequisite_tables_remote_test_parts/"
    ) in steps[1]["command"]


def test_h48_fasttarget_remote_runner_can_install_fetched_prerequisites(tmp_path):
    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    (runbook_dir / "install_prerequisite_tables.sh").write_text(
        "#!/usr/bin/env bash\n",
        encoding="utf-8",
    )
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "recommended_minimum_cloud_machine": {
                    "h48_target_table_size_bytes": 30336314216,
                },
                "generated_files": {
                    "install_prerequisite_tables": (
                        "results/cloud_hardtail_runbook_remote_test/"
                        "install_prerequisite_tables.sh"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="wait-prerequisites",
        prerequisite_wait_timeout_seconds=43200.0,
        prerequisite_poll_interval_seconds=60.0,
        install_fetched_prerequisites=True,
    )

    assert context["install_fetched_prerequisites"] is True
    assert [step["id"] for step in steps] == [
        "remote_wait_prerequisites",
        "fetch_prerequisite_tables_archive",
        "install_fetched_prerequisite_tables",
        "fetch_processed_artifacts",
    ]
    install = steps[2]
    assert install["location"] == "local"
    assert install["archive"] == "results/cloud_hardtail_prerequisite_tables_remote_test.tar.gz"
    assert "install_prerequisite_tables.sh" in install["command"][1]
    assert install["command"][2].endswith(
        "results/cloud_hardtail_prerequisite_tables_remote_test.tar.gz"
    )


def test_h48_fasttarget_remote_runner_can_install_split_fetched_prerequisites(tmp_path):
    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    (runbook_dir / "install_prerequisite_tables.sh").write_text(
        "#!/usr/bin/env bash\n",
        encoding="utf-8",
    )
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "recommended_minimum_cloud_machine": {
                    "h48_target_table_size_bytes": 30336314216,
                },
                "generated_files": {
                    "install_prerequisite_tables": (
                        "results/cloud_hardtail_runbook_remote_test/"
                        "install_prerequisite_tables.sh"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="wait-prerequisites",
        prerequisite_bundle_mode="split",
        install_fetched_prerequisites=True,
    )

    assert context["install_fetched_prerequisites"] is True
    assert context["prerequisite_install_source"] == (
        "results/cloud_hardtail_prerequisite_tables_remote_test_parts"
    )
    assert [step["id"] for step in steps] == [
        "remote_wait_prerequisites",
        "fetch_prerequisite_table_parts",
        "install_fetched_prerequisite_tables",
        "fetch_processed_artifacts",
    ]
    install = steps[2]
    assert install["location"] == "local"
    assert install["archive"] is None
    assert install["parts_dir"] == "results/cloud_hardtail_prerequisite_tables_remote_test_parts"
    assert install["install_source"] == (
        "results/cloud_hardtail_prerequisite_tables_remote_test_parts"
    )
    assert "install_prerequisite_tables.sh" in install["command"][1]
    assert install["command"][2].endswith(
        "results/cloud_hardtail_prerequisite_tables_remote_test_parts"
    )


def test_h48_fasttarget_remote_runner_can_start_full_proof_detached(tmp_path):
    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    generated_files = {
        "preflight_worker": "preflight_worker.sh",
        "validate_prerequisite_tables": "validate_prerequisite_tables.sh",
        "run_canary_after_prerequisites": "run_canary_after_prerequisites.sh",
        "run_full": "run_full.sh",
        "evaluate_full": "evaluate_full.sh",
        "collect_results": "collect_results.sh",
    }
    for name in generated_files.values():
        (runbook_dir / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "generated_files": {
                    key: f"results/cloud_hardtail_runbook_remote_test/{name}"
                    for key, name in generated_files.items()
                },
            }
        ),
        encoding="utf-8",
    )

    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="start-full",
    )

    assert context["remote_action"] == "start-full"
    assert [step["id"] for step in steps] == [
        "remote_prepare",
        "sync_repo_to_remote",
        "remote_start_full_detached",
        "fetch_processed_artifacts",
    ]
    detached = steps[2]
    assert detached["detached"] is True
    assert "nohup bash -lc" in detached["command"][-1]
    assert "preflight_worker.sh" in detached["command"][-1]
    assert "validate_prerequisite_tables.sh" in detached["command"][-1]
    assert "run_canary_after_prerequisites.sh" in detached["command"][-1]
    assert "run_full.sh" in detached["command"][-1]
    assert "evaluate_full.sh" in detached["command"][-1]
    assert "collect_results.sh" in detached["command"][-1]
    assert "h48_fasttarget_remote_test_start_full.pid" in detached["command"][-1]
    assert "h48_fasttarget_remote_test_start_full_launch.json" in detached["command"][-1]
    assert "ubuntu@cube-box:/mnt/sgarbas-h48/results/processed/" in steps[3]["command"]


def test_h48_fasttarget_remote_runner_can_wait_for_detached_full_proof(tmp_path):
    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    generated_files = {
        "unpack_results": "unpack_results.sh",
        "finalize_full_after_collect": "finalize_full_after_collect.sh",
    }
    for name in generated_files.values():
        (runbook_dir / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "generated_files": {
                    key: f"results/cloud_hardtail_runbook_remote_test/{name}"
                    for key, name in generated_files.items()
                },
            }
        ),
        encoding="utf-8",
    )

    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="wait-full",
        full_wait_timeout_seconds=28800.0,
        full_poll_interval_seconds=60.0,
    )

    assert context["remote_action"] == "wait-full"
    assert context["full_wait_timeout_seconds"] == 28800.0
    assert context["full_poll_interval_seconds"] == 60.0
    assert [step["id"] for step in steps] == [
        "remote_wait_full",
        "fetch_results_archive",
        "fetch_processed_artifacts",
        "validate_results_archive",
        "unpack_results_archive",
        "finalize_after_collect",
    ]
    wait_command = steps[0]["command"][-1]
    assert "full_wait_timeout_seconds" in wait_command
    assert "full_poll_interval_seconds" in wait_command
    assert "start_full" in wait_command
    assert "os.kill(pid, 0)" in wait_command
    assert "ready_for_finalize" in wait_command
    assert "cloud_hardtail_artifacts_remote_test.tar.gz" in wait_command
    assert all(step["id"] not in {"remote_prepare", "sync_repo_to_remote"} for step in steps)


def test_h48_fasttarget_remote_runner_resume_plans_status_prerequisites_and_full(tmp_path):
    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    generated_files = {
        "run_full_prerequisites": "run_full_prerequisites.sh",
        "collect_prerequisite_tables": "collect_prerequisite_tables.sh",
        "preflight_worker": "preflight_worker.sh",
        "validate_prerequisite_tables": "validate_prerequisite_tables.sh",
        "run_full": "run_full.sh",
        "evaluate_full": "evaluate_full.sh",
        "collect_results": "collect_results.sh",
        "unpack_results": "unpack_results.sh",
        "finalize_full_after_collect": "finalize_full_after_collect.sh",
    }
    for name in generated_files.values():
        (runbook_dir / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "recommended_minimum_cloud_machine": {
                    "h48_target_table_size_bytes": 30336314216,
                },
                "generated_files": {
                    key: f"results/cloud_hardtail_runbook_remote_test/{name}"
                    for key, name in generated_files.items()
                },
            }
        ),
        encoding="utf-8",
    )

    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="resume",
    )

    assert context["remote_action"] == "resume"
    assert context["expected_table_size_bytes"] == 30336314216
    assert context["resume_decision_policy"].startswith("remote_status results archive exists")
    assert "fetch_finalize" in context["resume_decision_policy"]
    assert "full checksum validates" in context["resume_decision_policy"]
    assert [step["id"] for step in steps] == [
        "remote_prepare",
        "sync_repo_to_remote",
        "remote_status",
        "remote_run_prerequisites",
        "remote_collect_prerequisite_tables",
        "remote_preflight_worker",
        "remote_validate_prerequisite_tables",
        "remote_run_full",
        "remote_evaluate_full",
        "remote_collect_results",
        "fetch_prerequisite_tables_archive",
        "fetch_processed_artifacts",
        "fetch_results_archive",
        "validate_results_archive",
        "unpack_results_archive",
        "finalize_after_collect",
    ]
    assert steps[2]["resume_group"] == "status"
    assert {steps[index]["resume_group"] for index in [3, 4, 10, 11]} == {"prerequisites"}
    assert {steps[index]["resume_group"] for index in [5, 6, 7, 8, 9, 12, 13, 14, 15]} == {"full"}


def test_h48_fasttarget_remote_runner_staged_proof_plans_detached_wait_canary_full(
    tmp_path,
):
    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    generated_files = {
        "preflight_leader": "preflight_leader.sh",
        "run_full_prerequisites": "run_full_prerequisites.sh",
        "collect_prerequisite_tables": "collect_prerequisite_tables.sh",
        "preflight_worker": "preflight_worker.sh",
        "validate_prerequisite_tables": "validate_prerequisite_tables.sh",
        "run_canary_after_prerequisites": "run_canary_after_prerequisites.sh",
        "run_full": "run_full.sh",
        "evaluate_full": "evaluate_full.sh",
        "collect_results": "collect_results.sh",
        "unpack_results": "unpack_results.sh",
        "finalize_full_after_collect": "finalize_full_after_collect.sh",
    }
    for name in generated_files.values():
        (runbook_dir / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "recommended_minimum_cloud_machine": {
                    "h48_target_table_size_bytes": 30336314216,
                },
                "generated_files": {
                    key: f"results/cloud_hardtail_runbook_remote_test/{name}"
                    for key, name in generated_files.items()
                },
            }
        ),
        encoding="utf-8",
    )

    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="staged-proof",
        prerequisite_wait_timeout_seconds=43200.0,
        prerequisite_poll_interval_seconds=60.0,
    )

    assert context["remote_action"] == "staged-proof"
    assert context["expected_table_size_bytes"] == 30336314216
    assert "wait_prerequisites_then_full" in context["resume_decision_policy"]
    assert context["prerequisite_wait_timeout_seconds"] == 43200.0
    assert context["prerequisite_poll_interval_seconds"] == 60.0
    assert [step["id"] for step in steps] == [
        "remote_prepare",
        "sync_repo_to_remote",
        "remote_status",
        "remote_preflight_leader",
        "remote_start_prerequisites_detached",
        "remote_wait_prerequisites",
        "remote_preflight_worker",
        "remote_validate_prerequisite_tables",
        "remote_run_canary_after_prerequisites",
        "remote_run_full",
        "remote_evaluate_full",
        "remote_collect_results",
        "fetch_results_archive",
        "fetch_prerequisite_tables_archive",
        "fetch_processed_artifacts",
        "validate_results_archive",
        "unpack_results_archive",
        "finalize_after_collect",
    ]
    assert steps[2]["resume_group"] == "status"
    assert {steps[index]["resume_group"] for index in [3, 4]} == {"prerequisite_start"}
    assert {steps[index]["resume_group"] for index in [5, 13, 14]} == {"prerequisite_wait"}
    assert {steps[index]["resume_group"] for index in [6, 7, 8, 9, 10, 11, 15, 16, 17]} == {
        "full"
    }
    detached = steps[4]
    assert detached["detached"] is True
    assert "nohup bash -lc" in detached["command"][-1]
    assert "run_full_prerequisites.sh" in detached["command"][-1]
    assert "collect_prerequisite_tables.sh" in detached["command"][-1]
    assert "remote_wait_prerequisites" not in steps[5]["command"][-1]
    assert "ready_for_resume" in steps[5]["command"][-1]
    assert "run_canary_after_prerequisites.sh" in steps[8]["command"][-1]


def test_h48_fasttarget_remote_runner_detached_staged_proof_plans_two_detached_waits(
    tmp_path,
):
    root = tmp_path
    manifest_path = _write_remote_full_runbook_manifest(root)

    steps, context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="detached-staged-proof",
        prerequisite_wait_timeout_seconds=43200.0,
        prerequisite_poll_interval_seconds=60.0,
        full_wait_timeout_seconds=28800.0,
        full_poll_interval_seconds=60.0,
    )

    assert context["remote_action"] == "detached-staged-proof"
    assert context["expected_table_size_bytes"] == 30336314216
    assert "start_prerequisites_then_start_full" in context["resume_decision_policy"]
    assert "wait_full" in context["resume_decision_policy"]
    assert context["prerequisite_wait_timeout_seconds"] == 43200.0
    assert context["full_wait_timeout_seconds"] == 28800.0
    assert [step["id"] for step in steps] == [
        "remote_prepare",
        "sync_repo_to_remote",
        "remote_status",
        "remote_preflight_leader",
        "remote_start_prerequisites_detached",
        "remote_wait_prerequisites",
        "remote_start_full_detached",
        "remote_wait_full",
        "fetch_results_archive",
        "fetch_prerequisite_tables_archive",
        "fetch_processed_artifacts",
        "validate_results_archive",
        "unpack_results_archive",
        "finalize_after_collect",
    ]
    assert steps[2]["resume_group"] == "status"
    assert {steps[index]["resume_group"] for index in [3, 4]} == {"prerequisite_start"}
    assert {steps[index]["resume_group"] for index in [5, 9]} == {"prerequisite_wait"}
    assert steps[6]["resume_group"] == "full_start"
    assert steps[7]["resume_group"] == "full_wait"
    assert {steps[index]["resume_group"] for index in [10, 11, 12, 13]} == {"full"}
    assert steps[4]["detached"] is True
    assert steps[6]["detached"] is True
    assert "run_full_prerequisites.sh" in steps[4]["command"][-1]
    assert "collect_prerequisite_tables.sh" in steps[4]["command"][-1]
    assert "run_canary_after_prerequisites.sh" in steps[6]["command"][-1]
    assert "collect_results.sh" in steps[6]["command"][-1]
    assert "ready_for_resume" in steps[5]["command"][-1]
    assert "ready_for_finalize" in steps[7]["command"][-1]
    assert "full_wait_timeout_seconds" in steps[7]["command"][-1]


def test_h48_fasttarget_remote_runner_parses_executed_status_payload(tmp_path, monkeypatch):
    import scripts.experimental.run_h48_fasttarget_remote as remote_runner

    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "recommended_minimum_cloud_machine": {
                    "h48_target_table_size_bytes": 30336314216,
                },
                "generated_files": {},
            }
        ),
        encoding="utf-8",
    )

    class Completed:
        return_code = 0
        timed_out = False
        runtime_seconds = 0.01
        terminated_process_group = False
        stderr = ""
        stdout = (
            "status probe\n"
            '{"solver":"h48h10","target_table_size_matches_expected":true,'
            '"target_table_full_checksum_valid":true,'
            '"contract_fast_runtime_proven_for_every_possible_state":false,'
            '"detached_prerequisite":{"pid":123,"process_alive":true,'
            '"prerequisite_tables_archive_present":false},'
            '"processed_workload_artifact_count":0}\n'
        )

    def fake_run_process_tree(_command, **_kwargs):
        return Completed()

    monkeypatch.setattr(remote_runner, "run_process_tree", fake_run_process_tree)

    payload, output = run_remote_fasttarget_proof(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="status",
        execute=True,
        artifact_suffix="status",
    )

    assert output.exists()
    assert payload["passed"] is True
    assert payload["remote_action"] == "status"
    assert payload["step_count"] == 1
    assert payload["executed_step_count"] == 1
    assert payload["passed_step_count"] == 1
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert payload["remote_status"]["solver"] == "h48h10"
    assert payload["remote_status"]["target_table_size_matches_expected"] is True
    assert payload["remote_status"]["target_table_full_checksum_valid"] is True
    assert payload["remote_status"]["contract_fast_runtime_proven_for_every_possible_state"] is False
    assert payload["remote_status"]["detached_prerequisite"]["pid"] == 123
    assert payload["remote_status"]["detached_prerequisite"]["process_alive"] is True
    assert payload["rows"][0]["remote_status"] == payload["remote_status"]


def test_h48_fasttarget_remote_runner_parses_executed_wait_payload(tmp_path, monkeypatch):
    import scripts.experimental.run_h48_fasttarget_remote as remote_runner

    root = tmp_path
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "recommended_minimum_cloud_machine": {
                    "h48_target_table_size_bytes": 30336314216,
                },
                "generated_files": {},
            }
        ),
        encoding="utf-8",
    )

    class Completed:
        return_code = 0
        timed_out = False
        runtime_seconds = 0.01
        terminated_process_group = False
        stderr = ""
        stdout = (
            "wait probe\n"
            '{"status":"ready","ready_for_resume":true,'
            '"archive_present":true,"table_size_matches_expected":true,'
            '"metadata_present":true,"metadata_trusted_table":true,'
            '"target_table_full_checksum_valid":true,'
            '"target_table_full_checksum_message":"valid",'
            '"attempts":2}\n'
        )

    def fake_run_process_tree(_command, **_kwargs):
        return Completed()

    monkeypatch.setattr(remote_runner, "run_process_tree", fake_run_process_tree)

    payload, output = run_remote_fasttarget_proof(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="wait-prerequisites",
        execute=True,
        skip_fetch=True,
        prerequisite_wait_timeout_seconds=60.0,
        prerequisite_poll_interval_seconds=5.0,
        artifact_suffix="wait_prereq",
    )

    assert output.exists()
    assert payload["passed"] is True
    assert payload["remote_action"] == "wait-prerequisites"
    assert payload["step_count"] == 1
    assert payload["executed_step_count"] == 1
    assert payload["remote_wait_prerequisites"]["status"] == "ready"
    assert payload["remote_wait_prerequisites"]["ready_for_resume"] is True
    assert payload["remote_wait_prerequisites"]["metadata_trusted_table"] is True
    assert payload["remote_wait_prerequisites"]["target_table_full_checksum_valid"] is True
    assert payload["rows"][0]["remote_wait_prerequisites"] == payload["remote_wait_prerequisites"]


def test_h48_fasttarget_remote_runner_parses_executed_full_wait_payload(
    tmp_path, monkeypatch
):
    import scripts.experimental.run_h48_fasttarget_remote as remote_runner

    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    for name in ["unpack_results.sh", "finalize_full_after_collect.sh"]:
        (runbook_dir / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "generated_files": {
                    "unpack_results": (
                        "results/cloud_hardtail_runbook_remote_test/unpack_results.sh"
                    ),
                    "finalize_full_after_collect": (
                        "results/cloud_hardtail_runbook_remote_test/finalize_full_after_collect.sh"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    class Completed:
        return_code = 0
        timed_out = False
        runtime_seconds = 0.01
        terminated_process_group = False
        stderr = ""
        stdout = (
            "full wait probe\n"
            '{"status":"ready","ready_for_finalize":true,'
            '"archive_present":true,"attempts":4}\n'
        )

    def fake_run_process_tree(_command, **_kwargs):
        return Completed()

    monkeypatch.setattr(remote_runner, "run_process_tree", fake_run_process_tree)

    payload, output = run_remote_fasttarget_proof(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="wait-full",
        execute=True,
        skip_fetch=True,
        skip_local_finalize=True,
        full_wait_timeout_seconds=60.0,
        full_poll_interval_seconds=5.0,
        artifact_suffix="wait_full",
    )

    assert output.exists()
    assert payload["passed"] is False
    assert payload["remote_action"] == "wait-full"
    assert payload["step_count"] == 1
    assert payload["executed_step_count"] == 1
    assert payload["remote_wait_full"]["status"] == "ready"
    assert payload["remote_wait_full"]["ready_for_finalize"] is True
    assert payload["rows"][0]["remote_wait_full"] == payload["remote_wait_full"]
    assert payload["final_contract_required_for_pass"] is True


def test_h48_fasttarget_remote_runner_staged_proof_waits_when_prerequisite_is_running(
    tmp_path, monkeypatch
):
    import scripts.experimental.run_h48_fasttarget_remote as remote_runner

    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    generated_files = {
        "preflight_leader": "preflight_leader.sh",
        "run_full_prerequisites": "run_full_prerequisites.sh",
        "collect_prerequisite_tables": "collect_prerequisite_tables.sh",
        "preflight_worker": "preflight_worker.sh",
        "validate_prerequisite_tables": "validate_prerequisite_tables.sh",
        "run_canary_after_prerequisites": "run_canary_after_prerequisites.sh",
        "run_full": "run_full.sh",
        "evaluate_full": "evaluate_full.sh",
        "collect_results": "collect_results.sh",
        "unpack_results": "unpack_results.sh",
        "finalize_full_after_collect": "finalize_full_after_collect.sh",
    }
    for name in generated_files.values():
        (runbook_dir / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "recommended_minimum_cloud_machine": {
                    "h48_target_table_size_bytes": 30336314216,
                },
                "generated_files": {
                    key: f"results/cloud_hardtail_runbook_remote_test/{name}"
                    for key, name in generated_files.items()
                },
            }
        ),
        encoding="utf-8",
    )

    class Completed:
        return_code = 0
        timed_out = False
        runtime_seconds = 0.01
        terminated_process_group = False
        stderr = ""

        def __init__(self, stdout: str = ""):
            self.stdout = stdout

    def fake_run_process_tree(command, **_kwargs):
        shell_command = " ".join(str(part) for part in command)
        if "processed_workload_artifact_count" in shell_command:
            return Completed(
                '{"results_archive":{"exists":false},'
                '"contract_fast_runtime_proven_for_every_possible_state":false,'
                '"target_table_size_matches_expected":false,'
                '"target_table_full_checksum_valid":false,'
                '"detached_prerequisite":{"process_alive":true}}\n'
            )
        if "ready_for_resume" in shell_command:
            return Completed(
                '{"status":"ready","ready_for_resume":true,'
                '"archive_present":true,"table_size_matches_expected":true,'
                '"metadata_present":true,"metadata_trusted_table":true,'
                '"target_table_full_checksum_valid":true,'
                '"target_table_full_checksum_message":"valid",'
                '"attempts":3}\n'
            )
        return Completed()

    monkeypatch.setattr(remote_runner, "run_process_tree", fake_run_process_tree)

    payload, output = run_remote_fasttarget_proof(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="staged-proof",
        execute=True,
        skip_sync=True,
        skip_fetch=True,
        skip_local_finalize=True,
        artifact_suffix="staged_running",
    )

    assert output.exists()
    assert payload["remote_action"] == "staged-proof"
    assert payload["resume_decision"] == "wait_prerequisites_then_full"
    assert payload["resume_prerequisites_skipped"] is True
    assert payload["remote_wait_prerequisites"]["ready_for_resume"] is True
    assert payload["remote_wait_prerequisites"]["target_table_full_checksum_valid"] is True
    skipped_ids = [
        row["id"] for row in payload["rows"] if row.get("skipped_by_resume_decision") is True
    ]
    assert skipped_ids == [
        "remote_preflight_leader",
        "remote_start_prerequisites_detached",
    ]
    executed_ids = [row["id"] for row in payload["rows"] if row.get("executed") is True]
    assert "remote_wait_prerequisites" in executed_ids
    assert "remote_run_canary_after_prerequisites" in executed_ids
    assert "remote_run_full" in executed_ids
    assert payload["final_contract_required_for_pass"] is True
    assert payload["passed"] is False


def test_h48_fasttarget_remote_runner_detached_staged_proof_waits_when_full_is_running(
    tmp_path, monkeypatch
):
    import scripts.experimental.run_h48_fasttarget_remote as remote_runner

    root = tmp_path
    manifest_path = _write_remote_full_runbook_manifest(root)

    class Completed:
        return_code = 0
        timed_out = False
        runtime_seconds = 0.01
        terminated_process_group = False
        stderr = ""

        def __init__(self, stdout: str = ""):
            self.stdout = stdout

    def fake_run_process_tree(command, **_kwargs):
        shell_command = " ".join(str(part) for part in command)
        if "processed_workload_artifact_count" in shell_command:
            return Completed(
                '{"results_archive":{"exists":false},'
                '"contract_fast_runtime_proven_for_every_possible_state":false,'
                '"target_table_size_matches_expected":true,'
                '"metadata_trusted_table":true,'
                '"target_table_full_checksum_valid":true,'
                '"table":{"exists":true,"size_bytes":30336314216},'
                '"metadata":{"exists":true},'
                '"detached_prerequisite":{"process_alive":false},'
                '"detached_full_proof":{"process_alive":true}}\n'
            )
        if "ready_for_finalize" in shell_command:
            return Completed(
                '{"status":"ready","ready_for_finalize":true,'
                '"archive_present":true,"attempts":2}\n'
            )
        return Completed()

    monkeypatch.setattr(remote_runner, "run_process_tree", fake_run_process_tree)

    payload, output = run_remote_fasttarget_proof(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="detached-staged-proof",
        execute=True,
        skip_sync=True,
        skip_fetch=True,
        skip_local_finalize=True,
        artifact_suffix="detached_staged_full_running",
    )

    assert output.exists()
    assert payload["remote_action"] == "detached-staged-proof"
    assert payload["resume_decision"] == "wait_full"
    assert payload["resume_prerequisites_skipped"] is True
    assert payload["resume_remote_full_skipped"] is True
    assert payload["remote_wait_full"]["ready_for_finalize"] is True
    skipped_ids = [
        row["id"] for row in payload["rows"] if row.get("skipped_by_resume_decision") is True
    ]
    assert skipped_ids == [
        "remote_preflight_leader",
        "remote_start_prerequisites_detached",
        "remote_wait_prerequisites",
        "remote_start_full_detached",
    ]
    executed_ids = [row["id"] for row in payload["rows"] if row.get("executed") is True]
    assert "remote_wait_full" in executed_ids
    assert "remote_start_full_detached" not in executed_ids
    assert "remote_wait_prerequisites" not in executed_ids
    assert payload["final_contract_required_for_pass"] is True
    assert payload["passed"] is False


def test_h48_fasttarget_remote_runner_detached_staged_proof_fetches_when_archive_exists(
    tmp_path, monkeypatch
):
    import scripts.experimental.run_h48_fasttarget_remote as remote_runner

    root = tmp_path
    manifest_path = _write_remote_full_runbook_manifest(root)
    calls: list[list[str]] = []

    class Completed:
        def __init__(self, stdout: str = ""):
            self.return_code = 0
            self.timed_out = False
            self.runtime_seconds = 0.01
            self.terminated_process_group = False
            self.stdout = stdout
            self.stderr = ""

    def fake_run_process_tree(command, **_kwargs):
        command = [str(part) for part in command]
        calls.append(command)
        shell_command = " ".join(command)
        if "processed_workload_artifact_count" in shell_command:
            return Completed(
                '{"solver":"h48h10",'
                '"results_archive":{"exists":true,"size_bytes":123456},'
                '"contract_fast_runtime_proven_for_every_possible_state":false,'
                '"target_table_size_matches_expected":true,'
                '"metadata_trusted_table":true,'
                '"target_table_full_checksum_valid":true,'
                '"table":{"exists":true,"size_bytes":30336314216},'
                '"metadata":{"exists":true},'
                '"detached_full_proof":{"process_alive":false}}\n'
            )
        return Completed()

    monkeypatch.setattr(remote_runner, "run_process_tree", fake_run_process_tree)

    payload, _output = run_remote_fasttarget_proof(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="detached-staged-proof",
        execute=True,
        skip_sync=True,
        skip_local_finalize=True,
        artifact_suffix="detached_staged_fetch_finalize",
    )

    assert payload["remote_action"] == "detached-staged-proof"
    assert payload["resume_decision"] == "fetch_finalize"
    assert payload["resume_prerequisites_skipped"] is True
    assert payload["resume_remote_full_skipped"] is True
    skipped_ids = [
        row["id"] for row in payload["rows"] if row.get("skipped_by_resume_decision") is True
    ]
    assert skipped_ids == [
        "remote_preflight_leader",
        "remote_start_prerequisites_detached",
        "remote_wait_prerequisites",
        "remote_start_full_detached",
        "remote_wait_full",
        "fetch_prerequisite_tables_archive",
    ]
    executed_ids = [row["id"] for row in payload["rows"] if row.get("executed") is True]
    assert "fetch_results_archive" in executed_ids
    assert "fetch_processed_artifacts" in executed_ids
    assert "remote_start_full_detached" not in executed_ids
    assert "remote_wait_full" not in executed_ids
    assert payload["final_contract_required_for_pass"] is True
    assert payload["passed"] is False


def test_h48_fasttarget_remote_runner_resume_skips_prerequisites_when_table_ready(
    tmp_path, monkeypatch
):
    import scripts.experimental.run_h48_fasttarget_remote as remote_runner

    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    generated_files = {
        "run_full_prerequisites": "run_full_prerequisites.sh",
        "collect_prerequisite_tables": "collect_prerequisite_tables.sh",
        "preflight_worker": "preflight_worker.sh",
        "validate_prerequisite_tables": "validate_prerequisite_tables.sh",
        "run_full": "run_full.sh",
        "evaluate_full": "evaluate_full.sh",
        "collect_results": "collect_results.sh",
        "unpack_results": "unpack_results.sh",
        "finalize_full_after_collect": "finalize_full_after_collect.sh",
    }
    for name in generated_files.values():
        (runbook_dir / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "recommended_minimum_cloud_machine": {
                    "h48_target_table_size_bytes": 30336314216,
                },
                "generated_files": {
                    key: f"results/cloud_hardtail_runbook_remote_test/{name}"
                    for key, name in generated_files.items()
                },
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    class Completed:
        def __init__(self, stdout: str = ""):
            self.return_code = 0
            self.timed_out = False
            self.runtime_seconds = 0.01
            self.terminated_process_group = False
            self.stdout = stdout
            self.stderr = ""

    def fake_run_process_tree(command, **_kwargs):
        calls.append([str(part) for part in command])
        if any("finalize_full_after_collect.sh" in str(part) for part in command):
            (processed / "h48_oracle_contract_seed_2026_thesis_h48h10.json").write_text(
                json.dumps(
                    _successful_h48h10_fast_contract()
                ),
                encoding="utf-8",
            )
        if len(calls) == 3:
            return Completed(
                '{"solver":"h48h10","target_table_size_matches_expected":true,'
                '"metadata_trusted_table":true,'
                '"target_table_full_checksum_valid":true,'
                '"table":{"exists":true,"size_bytes":30336314216},'
                '"metadata":{"exists":true},'
                '"contract_fast_runtime_proven_for_every_possible_state":false}\n'
            )
        return Completed()

    monkeypatch.setattr(remote_runner, "run_process_tree", fake_run_process_tree)

    payload, _output = run_remote_fasttarget_proof(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="resume",
        execute=True,
        artifact_suffix="resume_ready",
    )

    assert payload["passed"] is True
    assert payload["final_contract_required_for_pass"] is True
    assert payload["final_contract_proof_passed"] is True
    assert payload["fast_runtime_proven_for_every_possible_state"] is True
    assert payload["final_contract"]["path"] == (
        "results/processed/h48_oracle_contract_seed_2026_thesis_h48h10.json"
    )
    assert payload["resume_decision"] == "full"
    assert payload["resume_prerequisites_skipped"] is True
    skipped_ids = [
        row["id"] for row in payload["rows"] if row.get("skipped_by_resume_decision") is True
    ]
    assert skipped_ids == [
        "remote_run_prerequisites",
        "remote_collect_prerequisite_tables",
        "fetch_prerequisite_tables_archive",
        "fetch_processed_artifacts",
    ]
    executed_ids = [row["id"] for row in payload["rows"] if row.get("executed") is True]
    assert "remote_run_full" in executed_ids
    assert "remote_run_prerequisites" not in executed_ids


def test_h48_fasttarget_remote_runner_resume_fetches_when_remote_proof_archive_exists(
    tmp_path, monkeypatch
):
    import scripts.experimental.run_h48_fasttarget_remote as remote_runner

    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    generated_files = {
        "run_full_prerequisites": "run_full_prerequisites.sh",
        "collect_prerequisite_tables": "collect_prerequisite_tables.sh",
        "preflight_worker": "preflight_worker.sh",
        "validate_prerequisite_tables": "validate_prerequisite_tables.sh",
        "run_full": "run_full.sh",
        "evaluate_full": "evaluate_full.sh",
        "collect_results": "collect_results.sh",
        "unpack_results": "unpack_results.sh",
        "finalize_full_after_collect": "finalize_full_after_collect.sh",
    }
    for name in generated_files.values():
        (runbook_dir / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "recommended_minimum_cloud_machine": {
                    "h48_target_table_size_bytes": 30336314216,
                },
                "generated_files": {
                    key: f"results/cloud_hardtail_runbook_remote_test/{name}"
                    for key, name in generated_files.items()
                },
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    class Completed:
        def __init__(self, stdout: str = ""):
            self.return_code = 0
            self.timed_out = False
            self.runtime_seconds = 0.01
            self.terminated_process_group = False
            self.stdout = stdout
            self.stderr = ""

    def fake_run_process_tree(command, **_kwargs):
        command = [str(part) for part in command]
        calls.append(command)
        if any("finalize_full_after_collect.sh" in part for part in command):
            (processed / "h48_oracle_contract_seed_2026_thesis_h48h10.json").write_text(
                json.dumps(
                    _successful_h48h10_fast_contract()
                ),
                encoding="utf-8",
            )
        if len(calls) == 3:
            return Completed(
                '{"solver":"h48h10",'
                '"target_table_size_matches_expected":true,'
                '"metadata_trusted_table":true,'
                '"target_table_full_checksum_valid":true,'
                '"table":{"exists":true,"size_bytes":30336314216},'
                '"metadata":{"exists":true},'
                '"results_archive":{"exists":true},'
                '"contract_fast_runtime_proven_for_every_possible_state":true}\n'
            )
        return Completed()

    monkeypatch.setattr(remote_runner, "run_process_tree", fake_run_process_tree)

    payload, _output = run_remote_fasttarget_proof(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="resume",
        execute=True,
        artifact_suffix="resume_fetch_finalize",
    )

    assert payload["passed"] is True
    assert payload["resume_decision"] == "fetch_finalize"
    assert payload["resume_prerequisites_skipped"] is True
    assert payload["resume_remote_full_skipped"] is True
    assert payload["final_contract_proof_passed"] is True
    assert payload["fast_runtime_proven_for_every_possible_state"] is True
    skipped_ids = [
        row["id"] for row in payload["rows"] if row.get("skipped_by_resume_decision") is True
    ]
    assert skipped_ids == [
        "remote_run_prerequisites",
        "remote_collect_prerequisite_tables",
        "remote_preflight_worker",
        "remote_validate_prerequisite_tables",
        "remote_run_full",
        "remote_evaluate_full",
        "remote_collect_results",
        "fetch_prerequisite_tables_archive",
        "fetch_processed_artifacts",
    ]
    executed_ids = [row["id"] for row in payload["rows"] if row.get("executed") is True]
    assert "fetch_results_archive" in executed_ids
    assert "unpack_results_archive" in executed_ids
    assert "finalize_after_collect" in executed_ids
    assert "remote_run_full" not in executed_ids


def test_h48_fasttarget_remote_runner_resume_fetch_finalize_can_install_prerequisites(
    tmp_path, monkeypatch
):
    import scripts.experimental.run_h48_fasttarget_remote as remote_runner

    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    generated_files = {
        "run_full_prerequisites": "run_full_prerequisites.sh",
        "collect_prerequisite_tables": "collect_prerequisite_tables.sh",
        "preflight_worker": "preflight_worker.sh",
        "validate_prerequisite_tables": "validate_prerequisite_tables.sh",
        "run_full": "run_full.sh",
        "evaluate_full": "evaluate_full.sh",
        "collect_results": "collect_results.sh",
        "unpack_results": "unpack_results.sh",
        "finalize_full_after_collect": "finalize_full_after_collect.sh",
        "install_prerequisite_tables": "install_prerequisite_tables.sh",
    }
    for name in generated_files.values():
        (runbook_dir / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "recommended_minimum_cloud_machine": {
                    "h48_target_table_size_bytes": 30336314216,
                },
                "generated_files": {
                    key: f"results/cloud_hardtail_runbook_remote_test/{name}"
                    for key, name in generated_files.items()
                },
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    class Completed:
        def __init__(self, stdout: str = ""):
            self.return_code = 0
            self.timed_out = False
            self.runtime_seconds = 0.01
            self.terminated_process_group = False
            self.stdout = stdout
            self.stderr = ""

    def fake_run_process_tree(command, **_kwargs):
        command = [str(part) for part in command]
        calls.append(command)
        if any("finalize_full_after_collect.sh" in part for part in command):
            (processed / "h48_oracle_contract_seed_2026_thesis_h48h10.json").write_text(
                json.dumps(
                    _successful_h48h10_fast_contract()
                ),
                encoding="utf-8",
            )
        if len(calls) == 3:
            return Completed(
                '{"solver":"h48h10",'
                '"target_table_size_matches_expected":true,'
                '"metadata_trusted_table":true,'
                '"target_table_full_checksum_valid":true,'
                '"table":{"exists":true,"size_bytes":30336314216},'
                '"metadata":{"exists":true},'
                '"results_archive":{"exists":true},'
                '"contract_fast_runtime_proven_for_every_possible_state":true}\n'
            )
        return Completed()

    monkeypatch.setattr(remote_runner, "run_process_tree", fake_run_process_tree)

    payload, _output = run_remote_fasttarget_proof(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="resume",
        execute=True,
        install_fetched_prerequisites=True,
        artifact_suffix="resume_fetch_finalize_install",
    )

    assert payload["passed"] is True
    assert payload["resume_decision"] == "fetch_finalize"
    assert payload["install_fetched_prerequisites"] is True
    skipped_ids = [
        row["id"] for row in payload["rows"] if row.get("skipped_by_resume_decision") is True
    ]
    assert "fetch_prerequisite_tables_archive" not in skipped_ids
    assert "install_fetched_prerequisite_tables" not in skipped_ids
    executed_ids = [row["id"] for row in payload["rows"] if row.get("executed") is True]
    assert "fetch_prerequisite_tables_archive" in executed_ids
    assert "install_fetched_prerequisite_tables" in executed_ids
    assert "fetch_results_archive" in executed_ids
    assert "finalize_after_collect" in executed_ids


def test_h48_fasttarget_remote_runner_resume_does_not_skip_when_checksum_missing(
    tmp_path, monkeypatch
):
    import scripts.experimental.run_h48_fasttarget_remote as remote_runner

    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    generated_files = {
        "run_full_prerequisites": "run_full_prerequisites.sh",
        "collect_prerequisite_tables": "collect_prerequisite_tables.sh",
        "preflight_worker": "preflight_worker.sh",
        "validate_prerequisite_tables": "validate_prerequisite_tables.sh",
        "run_full": "run_full.sh",
        "evaluate_full": "evaluate_full.sh",
        "collect_results": "collect_results.sh",
        "unpack_results": "unpack_results.sh",
        "finalize_full_after_collect": "finalize_full_after_collect.sh",
    }
    for name in generated_files.values():
        (runbook_dir / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "recommended_minimum_cloud_machine": {
                    "h48_target_table_size_bytes": 30336314216,
                },
                "generated_files": {
                    key: f"results/cloud_hardtail_runbook_remote_test/{name}"
                    for key, name in generated_files.items()
                },
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    class Completed:
        def __init__(self, stdout: str = ""):
            self.return_code = 0
            self.timed_out = False
            self.runtime_seconds = 0.01
            self.terminated_process_group = False
            self.stdout = stdout
            self.stderr = ""

    def fake_run_process_tree(command, **_kwargs):
        calls.append([str(part) for part in command])
        if any("finalize_full_after_collect.sh" in str(part) for part in command):
            (processed / "h48_oracle_contract_seed_2026_thesis_h48h10.json").write_text(
                json.dumps(
                    _successful_h48h10_fast_contract()
                ),
                encoding="utf-8",
            )
        if len(calls) == 3:
            return Completed(
                '{"solver":"h48h10","target_table_size_matches_expected":true,'
                '"metadata_trusted_table":true,'
                '"target_table_full_checksum_valid":false,'
                '"table":{"exists":true,"size_bytes":30336314216},'
                '"metadata":{"exists":true},'
                '"contract_fast_runtime_proven_for_every_possible_state":false}\n'
            )
        return Completed()

    monkeypatch.setattr(remote_runner, "run_process_tree", fake_run_process_tree)

    payload, _output = run_remote_fasttarget_proof(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="resume",
        execute=True,
        artifact_suffix="resume_checksum_missing",
    )

    assert payload["passed"] is True
    assert payload["resume_decision"] == "prerequisites_then_full"
    assert payload["resume_prerequisites_skipped"] is False
    executed_ids = [row["id"] for row in payload["rows"] if row.get("executed") is True]
    assert "remote_run_prerequisites" in executed_ids
    assert "remote_collect_prerequisite_tables" in executed_ids


def test_h48_fasttarget_remote_runner_final_proof_requires_contract_true(
    tmp_path, monkeypatch
):
    import scripts.experimental.run_h48_fasttarget_remote as remote_runner

    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    for name in [
        "run_end_to_end_single_machine.sh",
        "unpack_results.sh",
        "finalize_full_after_collect.sh",
    ]:
        (runbook_dir / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "generated_files": {
                    "run_end_to_end_single_machine": (
                        "results/cloud_hardtail_runbook_remote_test/run_end_to_end_single_machine.sh"
                    ),
                    "unpack_results": "results/cloud_hardtail_runbook_remote_test/unpack_results.sh",
                    "finalize_full_after_collect": (
                        "results/cloud_hardtail_runbook_remote_test/finalize_full_after_collect.sh"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    class Completed:
        return_code = 0
        timed_out = False
        runtime_seconds = 0.01
        terminated_process_group = False
        stdout = ""
        stderr = ""

    monkeypatch.setattr(remote_runner, "run_process_tree", lambda *_args, **_kwargs: Completed())

    payload, _output = run_remote_fasttarget_proof(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        execute=True,
        artifact_suffix="contract_missing",
    )

    assert payload["all_steps_passed"] is True
    assert payload["final_contract_required_for_pass"] is True
    assert payload["final_contract"]["exists"] is False
    assert payload["final_contract_proof_passed"] is False
    assert payload["passed"] is False
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_h48_fasttarget_remote_runner_final_proof_requires_nested_cloud_integrity(
    tmp_path, monkeypatch
):
    import scripts.experimental.run_h48_fasttarget_remote as remote_runner

    root = tmp_path
    manifest_path = _write_remote_full_runbook_manifest(root)
    processed = root / "results" / "processed"

    class Completed:
        return_code = 0
        timed_out = False
        runtime_seconds = 0.01
        terminated_process_group = False
        stdout = ""
        stderr = ""

    def fake_run_process_tree(command, **_kwargs):
        if any("finalize_full_after_collect.sh" in str(part) for part in command):
            payload = _successful_h48h10_fast_contract()
            payload["cloud_runtime_proof"] = {
                **payload["cloud_runtime_proof"],
                "passed": False,
                "all_required_artifact_integrity_passed": False,
                "cloud_runtime_evidence_passed": False,
                "artifact_integrity_passed_workload_count": 6,
                "missing_or_failed_workload_count": 0,
            }
            (processed / "h48_oracle_contract_seed_2026_thesis_h48h10.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
        return Completed()

    monkeypatch.setattr(remote_runner, "run_process_tree", fake_run_process_tree)

    payload, _output = run_remote_fasttarget_proof(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        remote_action="full",
        execute=True,
        artifact_suffix="contract_shallow_success",
    )

    assert payload["all_steps_passed"] is True
    assert payload["final_contract_required_for_pass"] is True
    assert payload["final_contract"]["fast_runtime_proven_for_every_possible_state"] is True
    assert payload["final_contract"]["cloud_runtime_proof_passed"] is False
    assert payload["final_contract"]["all_required_artifact_integrity_passed"] is False
    assert payload["final_contract"]["artifact_integrity_count_matches"] is False
    assert payload["final_contract_proof_passed"] is False
    assert payload["passed"] is False
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_h48_fasttarget_remote_runner_dry_run_writes_auditable_artifact(tmp_path):
    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    for name in [
        "run_end_to_end_single_machine.sh",
        "unpack_results.sh",
        "finalize_full_after_collect.sh",
    ]:
        (runbook_dir / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "generated_files": {
                    "run_end_to_end_single_machine": (
                        "results/cloud_hardtail_runbook_remote_test/run_end_to_end_single_machine.sh"
                    ),
                    "unpack_results": "results/cloud_hardtail_runbook_remote_test/unpack_results.sh",
                    "finalize_full_after_collect": (
                        "results/cloud_hardtail_runbook_remote_test/finalize_full_after_collect.sh"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    payload, output = run_remote_fasttarget_proof(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        execute=False,
        artifact_suffix="dryrun",
    )

    assert output.exists()
    assert payload["dry_run"] is True
    assert payload["execute"] is False
    assert payload["passed"] is False
    assert payload["remote_action"] == "end-to-end"
    assert payload["executed_step_count"] == 0
    assert payload["step_count"] == 7
    assert payload["fetch_diagnostics_on_fail"] is True
    assert "results/processed/" in payload["diagnostic_fetch_command"]
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert all(row["executed"] is False for row in payload["rows"])


def test_h48_fasttarget_remote_runner_fetches_diagnostics_after_execute_failure(
    tmp_path, monkeypatch
):
    import scripts.experimental.run_h48_fasttarget_remote as remote_runner

    root = tmp_path
    runbook_dir = root / "results" / "cloud_hardtail_runbook_remote_test"
    processed = root / "results" / "processed"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    for name in [
        "run_end_to_end_single_machine.sh",
        "unpack_results.sh",
        "finalize_full_after_collect.sh",
    ]:
        (runbook_dir / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manifest_path = processed / "cloud_hardtail_runbook_remote_test.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_suffix": "remote_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "generated_files": {
                    "run_end_to_end_single_machine": (
                        "results/cloud_hardtail_runbook_remote_test/run_end_to_end_single_machine.sh"
                    ),
                    "unpack_results": "results/cloud_hardtail_runbook_remote_test/unpack_results.sh",
                    "finalize_full_after_collect": (
                        "results/cloud_hardtail_runbook_remote_test/finalize_full_after_collect.sh"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    calls = []

    class Completed:
        def __init__(self, return_code: int, stdout: str = "", stderr: str = ""):
            self.return_code = return_code
            self.timed_out = False
            self.runtime_seconds = 0.01
            self.terminated_process_group = False
            self.stdout = stdout
            self.stderr = stderr

    def fake_run_process_tree(command, **_kwargs):
        calls.append(command)
        if len(calls) == 1:
            return Completed(42, stderr="preflight failed")
        return Completed(0, stdout="diagnostics fetched")

    monkeypatch.setattr(remote_runner, "run_process_tree", fake_run_process_tree)

    payload, _output = run_remote_fasttarget_proof(
        root=root,
        runbook_manifest_path=manifest_path,
        host="ubuntu@cube-box",
        remote_root="/mnt/sgarbas-h48",
        execute=True,
        artifact_suffix="failed",
    )

    assert payload["passed"] is False
    assert payload["halted"] is True
    assert payload["step_count"] == 2
    assert [row["id"] for row in payload["rows"]] == [
        "remote_prepare",
        "fetch_diagnostics_on_fail",
    ]
    assert payload["rows"][0]["return_code"] == 42
    assert payload["rows"][1]["passed"] is True
    assert payload["rows"][1]["required"] is False
    assert payload["rows"][1]["triggered_by_failed_step"] == "remote_prepare"
    assert "results/processed/" in payload["rows"][1]["shell_command"]
    assert len(calls) == 2
