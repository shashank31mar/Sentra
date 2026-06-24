#!/usr/bin/env python3
"""
Build and Push Docker Image to ECR

This script builds a Docker image for a specific Sentra service and pushes it to ECR.
Enforces milestone-based versioning for deployment safety.

BEST PRACTICES:
- Milestone numbers are MANDATORY for all deployments
- Each milestone is immutable (cannot overwrite existing milestone)
- Automatic tagging: milestone-N and latest
- Pre-flight validation ensures safe deployments

Usage:
    # Build and push with milestone number (REQUIRED)
    python scripts/build_and_push_image.py --service security-controller --milestone 1
    
    # Build locally without pushing (for testing)
    python scripts/build_and_push_image.py --service security-controller --milestone 1 --no-push
    
    # Force overwrite existing milestone (use with caution!)
    python scripts/build_and_push_image.py --service security-controller --milestone 1 --force
"""

import argparse
import contextlib
import fcntl
import subprocess
import sys
import os
import tempfile
from typing import Optional, List


# Configuration
AWS_PROFILE = "sentra"
AWS_REGION = "us-east-1"
AWS_ACCOUNT_ID = "531109575379"

# ANSI color codes
GREEN = "\033[0;32m"
BLUE = "\033[0;34m"
YELLOW = "\033[0;33m"
RED = "\033[0;31m"
NC = "\033[0m"  # No Color


def print_step(step: str, message: str):
    """Print a colored step message"""
    print(f"{BLUE}{step}{NC} {message}")


def print_success(message: str):
    """Print a success message"""
    print(f"{GREEN}✓ {message}{NC}")


def print_error(message: str):
    """Print an error message"""
    print(f"{RED}✗ {message}{NC}", file=sys.stderr)


def print_warning(message: str):
    """Print a warning message"""
    print(f"{YELLOW}⚠ {message}{NC}")


def run_command(cmd: List[str], check: bool = True, capture_output: bool = False) -> subprocess.CompletedProcess:
    """Run a shell command and handle errors"""
    try:
        result = subprocess.run(
            cmd,
            check=check,
            capture_output=capture_output,
            text=True
        )
        return result
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed: {' '.join(cmd)}")
        if e.stderr:
            print_error(f"Error: {e.stderr}")
        sys.exit(1)


def verify_aws_credentials() -> bool:
    """Verify AWS credentials are valid"""
    print_step("[1/7]", "Verifying AWS credentials...")
    try:
        result = run_command(
            ["aws", "sts", "get-caller-identity", "--profile", AWS_PROFILE],
            capture_output=True
        )
        print_success("AWS credentials verified")
        return True
    except:
        print_error("AWS credentials invalid. Please run: ada cred update --once")
        return False


def ecr_login() -> bool:
    """Login to ECR"""
    print_step("[2/7]", "Logging into ECR...")
    try:
        # Get ECR password
        result = run_command(
            ["aws", "ecr", "get-login-password", "--region", AWS_REGION, "--profile", AWS_PROFILE],
            capture_output=True
        )
        password = result.stdout.strip()
        
        # Docker login with password piped to stdin
        ecr_url = f"{AWS_ACCOUNT_ID}.dkr.ecr.{AWS_REGION}.amazonaws.com"
        login_process = subprocess.run(
            ["docker", "login", "--username", "AWS", "--password-stdin", ecr_url],
            input=password,
            text=True,
            capture_output=True,
            check=True
        )
        
        print_success("ECR login successful")
        return True
    except subprocess.CalledProcessError as e:
        print_error("ECR login failed")
        if e.stderr:
            print_error(f"Error: {e.stderr}")
        return False
    except Exception as e:
        print_error(f"ECR login failed: {e}")
        return False


def build_image(service: str, dockerfile: str, context: str, tag: str) -> bool:
    """Build Docker image"""
    print_step("[3/7]", f"Building image for: {service}")
    
    local_tag = f"sentra/{service}:{tag}"
    
    cmd = [
        "docker", "build",
        "-t", local_tag,
        "--platform", "linux/amd64",  # ECS Fargate requirement
        "--build-arg", f"SERVICE_NAME={service}",  # Pass service name to Dockerfile
        "-f", dockerfile,
        context
    ]
    
    print(f"  Command: {' '.join(cmd)}")
    
    try:
        run_command(cmd)
        print_success(f"Built: {local_tag}")
        return True
    except:
        print_error(f"Failed to build {service}")
        return False


def tag_image(service: str, source_tag: str, target_tag: str) -> bool:
    """Tag Docker image for ECR"""
    print_step("[4/7]", f"Tagging image: {service}")
    
    local_tag = f"sentra/{service}:{source_tag}"
    ecr_uri = f"{AWS_ACCOUNT_ID}.dkr.ecr.{AWS_REGION}.amazonaws.com/sentra/{service}:{target_tag}"
    
    try:
        run_command(["docker", "tag", local_tag, ecr_uri])
        print_success(f"Tagged: {ecr_uri}")
        return True
    except:
        print_error(f"Failed to tag {service}")
        return False


def push_image(service: str, tag: str) -> bool:
    """Push Docker image to ECR"""
    print_step("[5/7]", f"Pushing image to ECR: {service}:{tag}")
    
    ecr_uri = f"{AWS_ACCOUNT_ID}.dkr.ecr.{AWS_REGION}.amazonaws.com/sentra/{service}:{tag}"
    
    try:
        run_command(["docker", "push", ecr_uri])
        print_success(f"Pushed: {ecr_uri}")
        return True
    except:
        print_error(f"Failed to push {service}:{tag}")
        return False


@contextlib.contextmanager
def push_lock():
    """Serialize ECR login+push across concurrent invocations of this script.

    `docker login` + `docker push` share one mutable ~/.docker/config.json (auths
    + credsStore). Two invocations running at once race on it, and the loser's
    push fails with `no basic auth credentials` — which is how a 'successful' run
    can silently ship the OLD image. A coarse file lock makes parallel pushes
    queue instead of collide. Build is unaffected (it's outside the lock)."""
    lock_path = os.path.join(tempfile.gettempdir(), "sentra-ecr-push.lock")
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def image_digest_in_ecr(service: str, tag: str) -> Optional[str]:
    """Return the imageDigest a tag resolves to in ECR, or None if absent."""
    repo_name = f"sentra/{service}"
    result = run_command(
        [
            "aws", "ecr", "describe-images",
            "--repository-name", repo_name,
            "--image-ids", f"imageTag={tag}",
            "--region", AWS_REGION,
            "--profile", AWS_PROFILE,
            "--query", "imageDetails[0].imageDigest",
            "--output", "text",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    digest = (result.stdout or "").strip()
    return digest if digest and digest != "None" else None


def check_image_exists_in_ecr(service: str, tag: str) -> bool:
    """Check if image already exists in ECR (returns True if exists)"""
    repo_name = f"sentra/{service}"

    try:
        result = run_command(
            [
                "aws", "ecr", "describe-images",
                "--repository-name", repo_name,
                "--image-ids", f"imageTag={tag}",
                "--region", AWS_REGION,
                "--profile", AWS_PROFILE
            ],
            capture_output=True,
            check=False  # Don't fail if image doesn't exist
        )
        return result.returncode == 0
    except:
        return False


def verify_push_landed(service: str, milestone_tag: str) -> bool:
    """Hard-verify the push actually landed: the milestone tag exists AND `latest`
    resolves to the SAME digest. This is the guard against a 'green' run that
    silently shipped a stale image — a failed/raced push leaves `latest` pointing
    at the previous build, and ECS (which pulls `:latest`) would never get the new
    code. Digest equality is the only honest proof the new code is deployable."""
    print_step("[6/7]", f"Verifying push landed: {service}:{milestone_tag} == :latest")

    milestone_digest = image_digest_in_ecr(service, milestone_tag)
    latest_digest = image_digest_in_ecr(service, "latest")

    if milestone_digest is None:
        print_error(f"Milestone tag not in ECR after push: sentra/{service}:{milestone_tag}")
        return False
    if latest_digest is None:
        print_error(f"'latest' tag not in ECR after push: sentra/{service}:latest")
        return False
    if milestone_digest != latest_digest:
        print_error(
            f"'latest' does NOT point at {milestone_tag} "
            f"({latest_digest[:19]}… vs {milestone_digest[:19]}…) — "
            f"the push likely raced or failed. ECS pulls ':latest', so it would "
            f"deploy the WRONG image. Re-run this push (serially)."
        )
        return False

    print_success(f"Push verified: {milestone_tag} and latest both → {milestone_digest[:19]}…")
    return True


def test_image_locally(service: str, tag: str, port: int = 8080) -> bool:
    """Test Docker image locally"""
    print_step("[7/7]", f"Testing image locally: {service}:{tag}")
    
    local_tag = f"sentra/{service}:{tag}"
    
    print(f"\n  To test the image locally, run:")
    print(f"    docker run -p {port}:{port} \\")
    print(f"      -e AWS_REGION={AWS_REGION} \\")
    print(f"      -e AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID \\")
    print(f"      -e AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY \\")
    print(f"      {local_tag}")
    print(f"\n  Then test with: curl http://localhost:{port}/health\n")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Build and push Docker image to ECR with milestone-based versioning",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Build and push security-controller milestone 1
  python scripts/build_and_push_image.py --service security-controller --milestone 1
  
  # Build and push milestone 2
  python scripts/build_and_push_image.py --service security-controller --milestone 2
  
  # Build locally without pushing (for testing)
  python scripts/build_and_push_image.py --service security-controller --milestone 1 --no-push
  
  # Force overwrite existing milestone (use with caution!)
  python scripts/build_and_push_image.py --service security-controller --milestone 1 --force

BEST PRACTICES:
  - Always use milestone numbers for deployments
  - Milestones are immutable by default (prevents accidental overwrites)
  - Each milestone automatically updates 'latest' tag
  - Use --no-push for local testing before pushing
        """
    )
    
    parser.add_argument(
        "--service",
        required=True,
        choices=["security-controller", "dashboard", "customer-query-agent", "payment-agent", "demo-orchestrator", "console"],
        help="Service name to build"
    )
    
    parser.add_argument(
        "--milestone",
        type=int,
        required=True,
        help="Milestone number (REQUIRED). Example: 1, 2, 3, etc."
    )
    
    parser.add_argument(
        "--dockerfile",
        help="Path to Dockerfile (default: docker/{service}/Dockerfile)"
    )
    
    parser.add_argument(
        "--context",
        help="Build context directory (default: . - project root)"
    )
    
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Build locally without pushing to ECR (for testing)"
    )
    
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force overwrite existing milestone (use with caution!)"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for local testing instructions (default: 8080)"
    )
    
    args = parser.parse_args()
    
    # Generate milestone tag
    milestone_tag = f"milestone-{args.milestone}"
    
    # Set defaults
    if not args.dockerfile:
        args.dockerfile = f"docker/{args.service}/Dockerfile"
    
    if not args.context:
        args.context = "."  # Project root
    
    # Verify Dockerfile exists
    if not os.path.exists(args.dockerfile):
        print_error(f"Dockerfile not found: {args.dockerfile}")
        sys.exit(1)
    
    # Verify context directory exists
    if not os.path.exists(args.context):
        print_error(f"Build context directory not found: {args.context}")
        sys.exit(1)
    
    # Print header
    print(f"\n{BLUE}========================================{NC}")
    print(f"{BLUE}Sentra MVP - Build and Push Image{NC}")
    print(f"{BLUE}========================================{NC}")
    print(f"  Service:    {args.service}")
    print(f"  Milestone:  {args.milestone} ({milestone_tag})")
    print(f"  Dockerfile: {args.dockerfile}")
    print(f"  Context:    {args.context}")
    print(f"  Push:       {'No' if args.no_push else 'Yes'}")
    print(f"  Force:      {'Yes' if args.force else 'No'}")
    print(f"{BLUE}========================================{NC}\n")
    
    # Step 1: Verify AWS credentials
    if not verify_aws_credentials():
        sys.exit(1)
    
    # Step 2: Check if milestone already exists (unless --force or --no-push)
    if not args.no_push and not args.force:
        print_step("[2/7]", f"Checking if {milestone_tag} already exists...")
        if check_image_exists_in_ecr(args.service, milestone_tag):
            print_error(f"Milestone {args.milestone} already exists in ECR!")
            print_error(f"Image: sentra/{args.service}:{milestone_tag}")
            print_error(f"\nMilestones are immutable to prevent accidental overwrites.")
            print_error(f"Options:")
            print_error(f"  1. Use a new milestone number: --milestone {args.milestone + 1}")
            print_error(f"  2. Force overwrite (not recommended): --force")
            print_error(f"  3. Build locally only: --no-push")
            sys.exit(1)
        print_success(f"Milestone {args.milestone} is available")
    
    # Step 4: Build image (outside the push lock — builds can safely run in parallel)
    if not args.no_push:
        print_step("[3/7]", "ECR login deferred to push lock (Step 5)")
    else:
        print_step("[3/7]", "Skipping ECR login (--no-push)")

    if not build_image(args.service, args.dockerfile, args.context, milestone_tag):
        sys.exit(1)

    # Step 5-6: Tag, push, and verify (skip if not pushing)
    if not args.no_push:
        # Hold a cross-process lock around login+push+verify so concurrent
        # invocations serialize instead of racing on ~/.docker/config.json
        # (the root cause of silent 'no basic auth credentials' push failures).
        with push_lock():
            # Login INSIDE the lock — the ECR token write is itself the race.
            if not ecr_login():
                sys.exit(1)

            # Tag and push with milestone tag
            if not tag_image(args.service, milestone_tag, milestone_tag):
                sys.exit(1)

            if not push_image(args.service, milestone_tag):
                sys.exit(1)

            # Also tag and push as latest
            if not tag_image(args.service, milestone_tag, "latest"):
                sys.exit(1)

            if not push_image(args.service, "latest"):
                sys.exit(1)

            # HARD gate: prove the push landed and `latest` resolves to this
            # build's digest. A warning here was how a stale image shipped green.
            if not verify_push_landed(args.service, milestone_tag):
                print_error("Push verification FAILED — not treating this as a successful deploy.")
                sys.exit(1)
    else:
        print_step("[5/7]", "Skipping tagging (--no-push)")
        print_step("[6/7]", "Skipping push (--no-push)")
        print_step("[7/7]", "Skipping verification (--no-push)")
    
    # Step 7: Show local testing instructions
    test_image_locally(args.service, milestone_tag, args.port)
    
    # Print success
    print(f"\n{GREEN}========================================{NC}")
    print(f"{GREEN}✓ Build completed successfully!{NC}")
    print(f"{GREEN}========================================{NC}\n")
    
    if not args.no_push:
        print("Deployment Info:")
        print(f"  ✓ Milestone {args.milestone} pushed: sentra/{args.service}:{milestone_tag}")
        print(f"  ✓ Latest tag updated: sentra/{args.service}:latest")
        print(f"\nNext steps:")
        print(f"  1. ECS will automatically pick up the new ':latest' tag")
        print(f"  2. Monitor deployment:")
        print(f"     aws ecs describe-services --cluster sentra-mvp-cluster --services {args.service} --region {AWS_REGION} --profile {AWS_PROFILE}")
        print(f"  3. Check logs:")
        print(f"     aws logs tail /ecs/sentra/{args.service} --follow --region {AWS_REGION} --profile {AWS_PROFILE}")
        print(f"\n  To rollback to milestone {args.milestone - 1 if args.milestone > 1 else 'PREVIOUS'}:")
        print(f"    python scripts/build_and_push_image.py --service {args.service} --milestone {args.milestone - 1 if args.milestone > 1 else 'PREVIOUS'} --force\n")
    else:
        print("Local Build Info:")
        print(f"  ✓ Image built locally: sentra/{args.service}:{milestone_tag}")
        print(f"  ✓ Not pushed to ECR (--no-push)")
        print(f"\n  To push this milestone:")
        print(f"    python scripts/build_and_push_image.py --service {args.service} --milestone {args.milestone}\n")


if __name__ == "__main__":
    main()
