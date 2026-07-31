"""
Sentra MVP - Static Site Stack (AegionAI public marketing site)

Hosts the built Vite/React marketing SPA (frontend/dist/) on AWS instead of
GoDaddy shared hosting: private S3 origin + CloudFront (HTTPS/CDN) + optional
Route53 apex/www aliases. Replaces the GoDaddy `.htaccess` SPA rewrite with a
CloudFront 403/404 -> /index.html (200) error response.

Config-gated: does nothing unless `static_site.enabled: true` in the env YAML, so
adding this stack cannot affect the existing controller/console deploys.

Cert note: CloudFront requires an ACM certificate in **us-east-1** that covers the
domains served (apex `aegionai.ai` + `www.aegionai.ai`). The existing ALB cert
(`*.aegionai.ai`) does NOT cover the apex, so this stack imports a SEPARATE cert
ARN from config (`static_site.certificate_arn`). Request+validate that cert once
(see docs/static-site-cutover.md); the stack references it by ARN so `cdk deploy`
never blocks on DNS validation.

Reference: docs/static-site-cutover.md (cutover runbook).
"""

from aws_cdk import (
    Stack,
    RemovalPolicy,
    CfnOutput,
    Duration,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_certificatemanager as acm,
    aws_route53 as route53,
    aws_route53_targets as route53_targets,
)
from constructs import Construct
from typing import Dict, Any, List
from pathlib import Path


class StaticSiteStack(Stack):
    """
    Static Site Stack - AegionAI public marketing site on S3 + CloudFront.

    Creates (only when static_site.enabled):
    - Private S3 bucket (origin; no public access — served only via CloudFront OAC)
    - CloudFront distribution (HTTPS via imported ACM cert, SPA fallback, caching)
    - BucketDeployment that syncs frontend/dist/ and invalidates the CDN on deploy
    - Optional Route53 A/AAAA alias records for apex + www (when hosted_zone_id given)

    Exports:
    - Distribution domain name (dxxxx.cloudfront.net) and ID
    - Bucket name
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: Dict[str, Any],
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        site_cfg: Dict[str, Any] = config.get("static_site", {})

        # ---- Domains served by the distribution (aliases) ------------------
        # Primary domain + any extras (e.g. www). Empty -> CloudFront default
        # domain only (dxxxx.cloudfront.net), still fully functional for testing.
        primary_domain: str = site_cfg.get("domain_name", "")
        extra_domains: List[str] = list(site_cfg.get("alternate_domains", []))
        domains: List[str] = [d for d in ([primary_domain] + extra_domains) if d]

        certificate_arn: str = site_cfg.get("certificate_arn", "")

        # A distribution can only attach a cert (and thus aliases) if BOTH the
        # cert ARN and at least one domain are configured. Otherwise we serve on
        # the default CloudFront domain — useful for a pre-DNS smoke test.
        use_custom_domain = bool(certificate_arn) and bool(domains)

        # ---- S3 origin bucket (private) ------------------------------------
        site_bucket = s3.Bucket(
            self,
            "SiteBucket",
            bucket_name=site_cfg.get("bucket_name"),  # None -> CFN auto-name
            # Private: no public ACLs/policies. CloudFront reaches it via OAC.
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            # Marketing assets are redeployable from source; safe to destroy the
            # bucket with the stack. Flip via config for a retain-on-delete posture.
            removal_policy=(
                RemovalPolicy.RETAIN
                if site_cfg.get("retain_on_delete", False)
                else RemovalPolicy.DESTROY
            ),
            auto_delete_objects=not site_cfg.get("retain_on_delete", False),
        )

        # ---- ACM cert (imported by ARN; must be us-east-1) -----------------
        certificate = None
        if use_custom_domain:
            certificate = acm.Certificate.from_certificate_arn(
                self, "SiteCertificate", certificate_arn=certificate_arn
            )

        # ---- CloudFront distribution ---------------------------------------
        # SPA fallback: a client-side-routed SPA needs deep links (/foo) and any
        # missing key to return index.html with 200 — the CloudFront equivalent
        # of the GoDaddy `.htaccess` "fallback everything to index.html" rule.
        spa_error_responses = [
            cloudfront.ErrorResponse(
                http_status=403,
                response_http_status=200,
                response_page_path="/index.html",
                ttl=Duration.minutes(5),
            ),
            cloudfront.ErrorResponse(
                http_status=404,
                response_http_status=200,
                response_page_path="/index.html",
                ttl=Duration.minutes(5),
            ),
        ]

        distribution = cloudfront.Distribution(
            self,
            "SiteDistribution",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                # S3Origin auto-creates an Origin Access Identity and grants it
                # read on the private bucket — CloudFront is the only reader, the
                # bucket stays BLOCK_ALL public access. (This CDK version predates
                # the OAC-based S3BucketOrigin; OAI is the equivalent here.)
                origin=origins.S3Origin(site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                compress=True,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
            ),
            domain_names=domains if use_custom_domain else None,
            certificate=certificate,
            error_responses=spa_error_responses,
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,  # NA + EU (cheapest)
            comment="AegionAI marketing site",
            minimum_protocol_version=cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
        )

        # ---- Deploy built assets + invalidate on every deploy --------------
        # Path to frontend/dist relative to this file: cdk/stacks/ -> repo root.
        dist_path = (
            Path(__file__).resolve().parents[2] / "frontend" / "dist"
        )
        s3deploy.BucketDeployment(
            self,
            "DeploySite",
            sources=[s3deploy.Source.asset(str(dist_path))],
            destination_bucket=site_bucket,
            distribution=distribution,
            distribution_paths=["/*"],  # invalidate the whole CDN cache on deploy
            prune=True,  # remove stale objects the new build no longer contains
        )

        # ---- Optional Route53 alias records (apex + www) -------------------
        # Only when a public hosted zone is provided (DNS-in-Route53 path). For
        # the "keep DNS at GoDaddy" path, leave hosted_zone_id unset and point
        # GoDaddy records at distribution.domain_name manually (see runbook).
        hosted_zone_id: str = site_cfg.get("hosted_zone_id", "")
        hosted_zone_name: str = site_cfg.get("hosted_zone_name", "")
        if hosted_zone_id and hosted_zone_name and use_custom_domain:
            zone = route53.HostedZone.from_hosted_zone_attributes(
                self,
                "SiteHostedZone",
                hosted_zone_id=hosted_zone_id,
                zone_name=hosted_zone_name,
            )
            cf_target = route53.RecordTarget.from_alias(
                route53_targets.CloudFrontTarget(distribution)
            )
            for domain in domains:
                # A record label relative to the zone: apex -> "", www -> "www".
                if domain == hosted_zone_name:
                    record_name = None
                elif domain.endswith("." + hosted_zone_name):
                    record_name = domain[: -(len(hosted_zone_name) + 1)]
                else:
                    # Alias in a zone that doesn't cover this domain — skip.
                    continue
                safe = domain.replace(".", "-")
                route53.ARecord(
                    self,
                    f"AliasA-{safe}",
                    zone=zone,
                    record_name=record_name,
                    target=cf_target,
                )
                route53.AaaaRecord(
                    self,
                    f"AliasAAAA-{safe}",
                    zone=zone,
                    record_name=record_name,
                    target=cf_target,
                )

        # ---- Outputs -------------------------------------------------------
        self.bucket = site_bucket
        self.distribution = distribution

        CfnOutput(
            self,
            "DistributionDomainName",
            value=distribution.distribution_domain_name,
            description="CloudFront domain — point GoDaddy DNS here (CNAME/alias)",
        )
        CfnOutput(
            self,
            "DistributionId",
            value=distribution.distribution_id,
            description="CloudFront distribution ID (for manual cache invalidation)",
        )
        CfnOutput(
            self,
            "SiteBucketName",
            value=site_bucket.bucket_name,
            description="S3 origin bucket name",
        )
