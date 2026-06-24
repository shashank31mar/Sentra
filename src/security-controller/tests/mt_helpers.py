"""Shared helpers for the multi-tenancy (LLD-26) test suite.

Not collected by pytest (no ``test_`` prefix). Provides ES256 keypair
generation, agent-JWT signing, and moto table creation for the three new tables.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional, Tuple

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import settings


def run(coro):
    """Run a coroutine on a *persistent* event loop. Unlike ``asyncio.run`` this
    never closes the shared loop, so it doesn't break sibling test modules that
    use the legacy ``get_event_loop().run_until_complete`` pattern."""
    try:
        loop = asyncio.get_event_loop_policy().get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def gen_keypair() -> Tuple[str, str]:
    """Return ``(private_pem, public_pem)`` for a fresh ES256 / P-256 key."""
    key = ec.generate_private_key(ec.SECP256R1())
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def public_pem_to_jwk(public_pem: str) -> str:
    """Export an EC public PEM as a JWK JSON string (to test the JWK code path)."""
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    from jwt.algorithms import ECAlgorithm

    key = load_pem_public_key(public_pem.encode())
    return ECAlgorithm.to_jwk(key)


def sign_agent_jwt(
    private_pem: str,
    kid: str,
    tenant_id: str,
    agent_id: str,
    *,
    iss: str = "aegion-guard",
    aud: str = "sentra-controller",
    exp_offset: int = 600,
    iat_offset: int = 0,
) -> str:
    """Sign an agent JWT the way the LLD-23 SDK would (ES256, kid header)."""
    now = int(time.time())
    return jwt.encode(
        {
            "iss": iss,
            "sub": agent_id,
            "tid": tenant_id,
            "iat": now + iat_offset,
            "exp": now + exp_offset,
            "aud": aud,
        },
        private_pem,
        algorithm="ES256",
        headers={"kid": kid},
    )


def create_mt_tables(ddb) -> None:
    """Create sentra-tenants, sentra-tenant-members (+GSI), sentra-agent-credentials
    (+kid-index GSI) in a moto-backed DynamoDB resource."""
    ddb.create_table(
        TableName=settings.dynamodb_tenants_table,
        KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName=settings.dynamodb_tenant_members_table,
        KeySchema=[
            {"AttributeName": "operator_sub", "KeyType": "HASH"},
            {"AttributeName": "tenant_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "operator_sub", "AttributeType": "S"},
            {"AttributeName": "tenant_id", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[{
            "IndexName": "tenant-members-index",
            "KeySchema": [{"AttributeName": "tenant_id", "KeyType": "HASH"}],
            "Projection": {"ProjectionType": "ALL"},
        }],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName=settings.dynamodb_agent_credentials_table,
        KeySchema=[
            {"AttributeName": "tenant_id", "KeyType": "HASH"},
            {"AttributeName": "key_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "tenant_id", "AttributeType": "S"},
            {"AttributeName": "key_id", "AttributeType": "S"},
            {"AttributeName": "kid", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[{
            "IndexName": "kid-index",
            "KeySchema": [{"AttributeName": "kid", "KeyType": "HASH"}],
            "Projection": {"ProjectionType": "ALL"},
        }],
        BillingMode="PAY_PER_REQUEST",
    )
    # sentra-identity-fallback (WS-B B1): PK agent_id, tenant_id as attribute.
    ddb.create_table(
        TableName=settings.dynamodb_identity_fallback_table,
        KeySchema=[{"AttributeName": "agent_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "agent_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    # sentra-platform-audit-records (WS-E E3): PK tenant_id (target) / SK record_id.
    ddb.create_table(
        TableName=settings.dynamodb_platform_audit_table,
        KeySchema=[
            {"AttributeName": "tenant_id", "KeyType": "HASH"},
            {"AttributeName": "record_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "tenant_id", "AttributeType": "S"},
            {"AttributeName": "record_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
