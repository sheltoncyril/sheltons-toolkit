#!/usr/bin/env python3
"""Emit `aws ec2 delete-tags` commands for ORPHANED cluster tags on a shared subnet.

The shared RHOAI ROSA-HCP subnets are tagged `kubernetes.io/cluster/<cluster>`
once per cluster. AWS caps this at 50 tags per subnet, so tags left behind by
deleted clusters must be cleared periodically.

This script never deletes anything itself — it only prints the delete-tags
commands for you to review and run. It will only target a tag whose cluster is
NOT in the live-cluster list, so a running cluster's tag is never touched.

Usage:
    export LIVE_CLUSTERS="clusterA,clusterB,..."   # from `rosa list clusters`
    python3 rosa_cleanup.py <subnet-id>

If LIVE_CLUSTERS is unset, the script refuses to emit anything (fail safe),
because without it every tag would look orphaned.

Requires: boto3  (pip3 install boto3), and valid AWS creds for account
585132637328 in us-east-1.
"""
import os
import sys

try:
    import boto3
except ImportError:
    sys.exit("boto3 not installed. Run: pip3 install boto3")

CLUSTER_TAG_PREFIX = "kubernetes.io/cluster/"


def live_clusters():
    raw = os.environ.get("LIVE_CLUSTERS")
    if raw is None:
        sys.exit(
            "LIVE_CLUSTERS is unset. Refusing to run (would treat every tag as "
            "orphaned). Set it first, e.g.:\n"
            "  export LIVE_CLUSTERS=\"$(rosa list clusters -o json | "
            "python3 -c 'import json,sys;print(\\\",\\\".join("
            "c[\\\"name\\\"] for c in json.load(sys.stdin)))')\""
        )
    return {c.strip() for c in raw.split(",") if c.strip()}


def main():
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} <subnet-id>")
    subnet = sys.argv[1]
    live = live_clusters()

    ec2 = boto3.client("ec2", region_name="us-east-1")
    resp = ec2.describe_subnets(SubnetIds=[subnet])
    tags = resp["Subnets"][0].get("Tags", [])

    for tag in tags:
        key = tag["Key"]
        if not key.startswith(CLUSTER_TAG_PREFIX):
            continue
        cluster = key[len(CLUSTER_TAG_PREFIX):]
        if cluster in live:
            continue  # live cluster — never touch
        value = tag.get("Value", "shared")
        # Printed for you to review, then run.
        print(
            f"aws ec2 delete-tags --resources {subnet} "
            f"--tags Key={key},Value={value}"
        )


if __name__ == "__main__":
    main()
