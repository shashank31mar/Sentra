#!/bin/bash
#
# Manage Cognito Users for Sentra Dashboard
#
# Usage:
#   ./scripts/create-cognito-users.sh [OPTIONS] [environment]
#
# Options:
#   --delete          Delete users instead of creating them
#   --email EMAIL     Specify user email (requires --password for create)
#   --password PWD    Specify temporary password (requires --email for create)
#   --help            Show this help message
#
# Examples:
#   # Create users with default credentials (dev/demo only)
#   ./scripts/create-cognito-users.sh dev
#
#   # Create specific user via command line
#   ./scripts/create-cognito-users.sh --email admin@sentra.com --password TempPass123! dev
#
#   # Create users from environment variables
#   export SENTRA_ADMIN_EMAIL="admin@sentra.com"
#   export SENTRA_ADMIN_TEMP_PASSWORD="TempPassword123!"
#   ./scripts/create-cognito-users.sh dev
#
#   # Create users from config file
#   cp scripts/.cognito-users.conf.example scripts/.cognito-users.conf
#   # Edit .cognito-users.conf
#   ./scripts/create-cognito-users.sh dev
#
#   # Delete specific user
#   ./scripts/create-cognito-users.sh --delete --email admin@sentra.com dev
#
#   # Delete all users from config file
#   ./scripts/create-cognito-users.sh --delete dev
#
# Prerequisites:
#   - AWS CLI configured with 'sentra' profile
#   - User Pool deployed via CDK
#

set -euo pipefail

# Configuration
ENVIRONMENT=""
AWS_PROFILE="${AWS_PROFILE:-sentra}"
AWS_REGION="${AWS_REGION:-us-east-1}"
DELETE_MODE=false
CLI_EMAIL=""
CLI_PASSWORD=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_debug() {
    echo -e "${BLUE}[DEBUG]${NC} $1"
}

show_help() {
    cat << EOF
Sentra Cognito User Management Script

Usage:
  ./scripts/create-cognito-users.sh [OPTIONS] [environment]

Options:
  --delete          Delete users instead of creating them
  --email EMAIL     Specify user email (requires --password for create)
  --password PWD    Specify temporary password (requires --email for create)
  --help            Show this help message

Examples:
  # Create users with default credentials (dev/demo only)
  ./scripts/create-cognito-users.sh dev

  # Create specific user via command line
  ./scripts/create-cognito-users.sh --email admin@sentra.com --password TempPass123! dev

  # Create users from environment variables
  export SENTRA_ADMIN_EMAIL="admin@sentra.com"
  export SENTRA_ADMIN_TEMP_PASSWORD="TempPassword123!"
  ./scripts/create-cognito-users.sh dev

  # Create users from config file
  cp scripts/.cognito-users.conf.example scripts/.cognito-users.conf
  # Edit .cognito-users.conf with your users
  ./scripts/create-cognito-users.sh dev

  # Delete specific user
  ./scripts/create-cognito-users.sh --delete --email admin@sentra.com dev

  # Delete all users from config file
  ./scripts/create-cognito-users.sh --delete dev

Credential Priority (for CREATE mode):
  1. Command line arguments (--email, --password)
  2. Environment variables (SENTRA_ADMIN_EMAIL, SENTRA_ADMIN_TEMP_PASSWORD)
  3. Config file (scripts/.cognito-users.conf)
  4. Default users (admin@sentra.com, demo@sentra.com) - DEV/DEMO ONLY

Default Users (used when no credentials provided):
  - admin@sentra.com / TempPassword123!
  - demo@sentra.com / DemoPassword123!

EOF
    exit 0
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --delete)
                DELETE_MODE=true
                shift
                ;;
            --email)
                CLI_EMAIL="$2"
                shift 2
                ;;
            --password)
                CLI_PASSWORD="$2"
                shift 2
                ;;
            --help)
                show_help
                ;;
            *)
                ENVIRONMENT="$1"
                shift
                ;;
        esac
    done

    # Set default environment
    ENVIRONMENT="${ENVIRONMENT:-dev}"

    # Validate arguments for CREATE mode
    if [ "$DELETE_MODE" = false ]; then
        if [ -n "$CLI_EMAIL" ] && [ -z "$CLI_PASSWORD" ]; then
            log_error "When using --email, you must also provide --password"
            exit 1
        fi
        if [ -z "$CLI_EMAIL" ] && [ -n "$CLI_PASSWORD" ]; then
            log_error "When using --password, you must also provide --email"
            exit 1
        fi
    fi

    # For DELETE mode, only email is needed
    if [ "$DELETE_MODE" = true ]; then
        if [ -n "$CLI_PASSWORD" ]; then
            log_warn "Password is ignored in delete mode"
        fi
    fi
}

# Get User Pool ID from CloudFormation
get_user_pool_id() {
    local env_upper=$(echo "$ENVIRONMENT" | tr '[:lower:]' '[:upper:]')
    local stack_name="Sentra-${env_upper}-Cognito-Stack"

    log_info "Getting User Pool ID from stack: $stack_name"

    USER_POOL_ID=$(aws cloudformation describe-stacks \
        --stack-name "$stack_name" \
        --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
        --output text \
        --profile "$AWS_PROFILE" \
        --region "$AWS_REGION" 2>/dev/null)

    if [ -z "$USER_POOL_ID" ]; then
        log_error "Could not find User Pool ID. Is the Cognito stack deployed?"
        exit 1
    fi

    log_info "User Pool ID: $USER_POOL_ID"
}

# Create a Cognito user
create_user() {
    local username="$1"
    local email="$2"
    local temp_password="$3"

    log_info "Creating user: $email"

    # Check if user already exists
    if aws cognito-idp admin-get-user \
        --user-pool-id "$USER_POOL_ID" \
        --username "$username" \
        --profile "$AWS_PROFILE" \
        --region "$AWS_REGION" &>/dev/null; then
        log_warn "User $email already exists, skipping"
        return 0
    fi

    # Create user
    aws cognito-idp admin-create-user \
        --user-pool-id "$USER_POOL_ID" \
        --username "$username" \
        --user-attributes Name=email,Value="$email" Name=email_verified,Value=true \
        --temporary-password "$temp_password" \
        --message-action SUPPRESS \
        --profile "$AWS_PROFILE" \
        --region "$AWS_REGION" \
        &>/dev/null

    if [ $? -eq 0 ]; then
        log_info "✓ User created: $email (temporary password set)"
    else
        log_error "✗ Failed to create user: $email"
        return 1
    fi
}

# Delete a Cognito user
delete_user() {
    local username="$1"
    local email="$2"

    log_info "Deleting user: $email"

    # Check if user exists
    if ! aws cognito-idp admin-get-user \
        --user-pool-id "$USER_POOL_ID" \
        --username "$username" \
        --profile "$AWS_PROFILE" \
        --region "$AWS_REGION" &>/dev/null; then
        log_warn "User $email does not exist, skipping"
        return 0
    fi

    # Delete user
    aws cognito-idp admin-delete-user \
        --user-pool-id "$USER_POOL_ID" \
        --username "$username" \
        --profile "$AWS_PROFILE" \
        --region "$AWS_REGION" \
        &>/dev/null

    if [ $? -eq 0 ]; then
        log_info "✓ User deleted: $email"
    else
        log_error "✗ Failed to delete user: $email"
        return 1
    fi
}

# Process users in CREATE mode
process_create() {
    # Priority 1: Command line arguments
    if [ -n "$CLI_EMAIL" ]; then
        log_info "Creating user from command line arguments"
        create_user "$CLI_EMAIL" "$CLI_EMAIL" "$CLI_PASSWORD"

    # Priority 2: Environment variables
    elif [ -n "${SENTRA_ADMIN_EMAIL:-}" ] && [ -n "${SENTRA_ADMIN_TEMP_PASSWORD:-}" ]; then
        log_info "Creating users from environment variables"
        create_user \
            "$SENTRA_ADMIN_EMAIL" \
            "$SENTRA_ADMIN_EMAIL" \
            "$SENTRA_ADMIN_TEMP_PASSWORD"

    # Priority 3: Config file
    elif [ -f "scripts/.cognito-users.conf" ]; then
        log_info "Creating users from config file: scripts/.cognito-users.conf"

        # Read config file (format: email,temp_password)
        while IFS=',' read -r email temp_password || [ -n "$email" ]; do
            # Skip comments and empty lines
            [[ "$email" =~ ^#.*$ ]] && continue
            [[ -z "$email" ]] && continue

            create_user "$email" "$email" "$temp_password"
        done < "scripts/.cognito-users.conf"

    # Priority 4: Default users (dev/demo only)
    else
        log_warn "No user credentials provided. Creating default demo users."
        log_warn "SECURITY: This should NOT be used in production!"
        log_warn ""
        log_warn "Default users:"
        log_warn "  - admin@sentra.com / TempPassword123!"
        log_warn "  - demo@sentra.com / DemoPassword123!"
        log_warn ""

        create_user \
            "admin@sentra.com" \
            "admin@sentra.com" \
            "TempPassword123!"

        create_user \
            "demo@sentra.com" \
            "demo@sentra.com" \
            "DemoPassword123!"
    fi
}

# Process users in DELETE mode
process_delete() {
    # Priority 1: Command line email
    if [ -n "$CLI_EMAIL" ]; then
        log_info "Deleting user from command line argument"
        delete_user "$CLI_EMAIL" "$CLI_EMAIL"

    # Priority 2: Environment variable
    elif [ -n "${SENTRA_ADMIN_EMAIL:-}" ]; then
        log_info "Deleting user from environment variable"
        delete_user "$SENTRA_ADMIN_EMAIL" "$SENTRA_ADMIN_EMAIL"

    # Priority 3: Config file
    elif [ -f "scripts/.cognito-users.conf" ]; then
        log_info "Deleting users from config file: scripts/.cognito-users.conf"

        # Read config file (format: email,temp_password - we only need email)
        while IFS=',' read -r email temp_password || [ -n "$email" ]; do
            # Skip comments and empty lines
            [[ "$email" =~ ^#.*$ ]] && continue
            [[ -z "$email" ]] && continue

            delete_user "$email" "$email"
        done < "scripts/.cognito-users.conf"

    # Priority 4: Default users
    else
        log_warn "No user email provided. Deleting default demo users."
        log_warn "Default users: admin@sentra.com, demo@sentra.com"

        delete_user "admin@sentra.com" "admin@sentra.com"
        delete_user "demo@sentra.com" "demo@sentra.com"
    fi
}

# Main execution
main() {
    # Parse arguments
    parse_args "$@"

    log_info "=========================================="
    if [ "$DELETE_MODE" = true ]; then
        log_info "Sentra Cognito User Deletion"
    else
        log_info "Sentra Cognito User Creation"
    fi
    log_info "=========================================="
    log_info "Environment: $ENVIRONMENT"
    log_info "AWS Profile: $AWS_PROFILE"
    log_info "AWS Region: $AWS_REGION"
    log_info "=========================================="

    # Get User Pool ID
    get_user_pool_id

    # Process based on mode
    if [ "$DELETE_MODE" = true ]; then
        process_delete
    else
        process_create
    fi

    log_info "=========================================="
    if [ "$DELETE_MODE" = true ]; then
        log_info "User deletion complete!"
    else
        log_info "User creation complete!"
        log_info ""
        log_info "Next steps:"
        log_info "1. Open Dashboard: http://\$PUBLIC_ALB_DNS"
        log_info "2. Login with temporary password"
        log_info "3. Set permanent password on first login"
    fi
    log_info "=========================================="
}

# Run main
main "$@"
