#!/bin/bash
# Sentra MVP - CDK Setup Script
# This script sets up the CDK environment with all dependencies

set -e  # Exit on error

echo "======================================"
echo "Sentra MVP - CDK Setup"
echo "======================================"

# Navigate to project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo ""
echo "Project root: $PROJECT_ROOT"

# Check if venv exists, create if not
if [ ! -d "venv" ]; then
    echo ""
    echo "Creating virtual environment..."
    python3 -m venv venv
else
    echo ""
    echo "Virtual environment already exists"
fi

# Activate virtual environment
echo ""
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo ""
echo "Upgrading pip..."
pip install --upgrade pip

# Install CDK dependencies
echo ""
echo "Installing CDK dependencies from cdk/requirements.txt..."
pip install -r cdk/requirements.txt

# Verify installation
echo ""
echo "Verifying CDK installation..."
cdk --version

echo ""
echo "======================================"
echo "CDK Setup Complete!"
echo "======================================"
echo ""
echo "Next steps:"
echo "  1. Activate venv: source venv/bin/activate"
echo "  2. Configure AWS: export AWS_PROFILE=sentra"
echo "  3. Verify account: aws sts get-caller-identity"
echo "  4. Bootstrap CDK: cd cdk && cdk bootstrap"
echo "  5. Synthesize: cd cdk && cdk synth"
echo "  6. Deploy: cd cdk && cdk deploy SentraNetworkStack"
echo ""
