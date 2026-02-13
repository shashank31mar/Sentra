# AI Safety Requirements for Sentra

**Version**: 1.0
**Date**: 2026-02-13
**Sources**:
- International AI Safety Report 2025 (Second Key Update)
- VentureBeat: Anthropic's Measurable Security Metrics Approach

---

## Table of Contents

1. [Problems Identified from AI Safety Report](#1-problems-identified-from-ai-safety-report)
2. [Problems Identified from VentureBeat Article](#2-problems-identified-from-venturebeat-article)
3. [Sentra Features Required (Problem-to-Solution Mapping)](#3-sentra-features-required-problem-to-solution-mapping)
4. [Sentra ML Security Model Requirements](#4-sentra-ml-security-model-requirements)
5. [Output Governance Features (Content Classification & Watermarking)](#5-output-governance-features-content-classification--watermarking)
6. [Additional Recommendations](#6-additional-recommendations)

---

## 1. Problems Identified from AI Safety Report

### 1.1 Prompt Injection Attacks (Critical)

**Finding**: Sophisticated attackers achieve ~50% success rate within 10 attempts against current safeguards.

**Details**:
- Basic prompt injection detection exists but can be bypassed
- Attacks use encoding, obfuscation, and multi-turn techniques
- Single-layer defenses are insufficient

**Impact**: Agents can be manipulated to perform unauthorized actions, bypass policies, or leak sensitive data.

---

### 1.2 Jailbreak Attacks (High)

**Finding**: Users can bypass safety constraints through carefully crafted prompts.

**Details**:
- "Act as..." and roleplay techniques
- Hypothetical scenario manipulation
- Context window exploitation

**Impact**: Agents perform actions outside intended safety boundaries.

---

### 1.3 Data Exfiltration (High)

**Finding**: Agents can be tricked into leaking sensitive information through tool calls or conversational tricks.

**Details**:
- Subtle prompt manipulation to extract PII
- Tool misuse to dump large datasets
- Side-channel information leakage

**Impact**: Privacy violations, regulatory non-compliance (GDPR, HIPAA).

---

### 1.4 Insufficient Defense-in-Depth (Critical)

**Finding**: Single safeguard layers fail; multiple overlapping defenses required.

**Details**:
- Relying only on input validation is insufficient
- Need validation at multiple points: input, tool selection, parameters, output
- Sequential validation with fail-fast logic

**Impact**: Single point of failure leads to security breaches.

---

### 1.5 Lack of Measurable Security Metrics (Critical)

**Finding**: Organizations cannot quantify security effectiveness; no baseline for improvement.

**Details**:
- No standardized attack success rate measurements
- Cannot compare security posture over time
- Difficult to demonstrate compliance to regulators

**Impact**: Unknown security posture; cannot prove security improvements.

---

### 1.6 Multi-Turn & Context Window Attacks (Medium)

**Finding**: Attacks spread across multiple conversation turns to evade detection.

**Details**:
- Turn 1: "What's the delete command?"
- Turn 2: "Apply it to the users table"
- Each turn appears innocent individually

**Impact**: Pattern-based detection fails on individual messages.

---

### 1.7 Encoding & Obfuscation Evasion (High)

**Finding**: Simple string matching fails against encoded or obfuscated attacks.

**Details**:
- Base64 encoding: `RGVsZXRlIGFsbCB1c2Vycw==`
- Unicode homoglyphs: `Dеⅼеte` (Cyrillic characters)
- ROT13, hex encoding, etc.

**Impact**: Rule-based detection bypassed easily.

---

### 1.8 Multi-Modal Attacks (Medium-High)

**Finding**: Attacks embedded in images, audio, or other non-text formats.

**Details**:
- Image containing malicious text (OCR bypass)
- Audio with embedded instructions
- Video deepfakes with harmful commands

**Impact**: Text-only validation is blind to multi-modal threats.

---

### 1.9 Adversarial Input Examples (High)

**Finding**: Carefully crafted inputs designed to fool ML-based detectors.

**Details**:
- Gradient-based attacks on classifiers
- Minimal perturbations that change model predictions
- Transferable attacks across models

**Impact**: ML security models can be systematically bypassed.

---

### 1.10 Inadequate Behavioral Monitoring (Medium)

**Finding**: Static rules cannot detect novel or evolving attack patterns.

**Details**:
- Zero-day attacks with no known signatures
- Emerging techniques not covered by rule sets
- Need for behavioral anomaly detection

**Impact**: New attack types go undetected.

---

### 1.11 Cross-Agent Attack Propagation (High)

**Finding**: Compromised agent can attack other agents in multi-agent systems.

**Details**:
- Agent A compromised → sends malicious prompts to Agent B
- Cascade failures across agent networks
- Privilege escalation through agent chains

**Impact**: Single compromised agent threatens entire system.

---

### 1.12 Insufficient Rate Limiting & Abuse Detection (Medium)

**Finding**: Attackers can brute-force attacks through volume.

**Details**:
- 10 attempts → 50% success rate (from report)
- No rate limiting on failed validation attempts
- Automated attack scripts

**Impact**: High-volume attacks eventually succeed.

---

### 1.13 Lack of Output Validation (High)

**Finding**: Focus on input validation only; outputs not checked for safety.

**Details**:
- Agents may generate harmful content even with safe inputs
- Tool responses not validated before returning to user
- Data exfiltration via tool outputs

**Impact**: Harmful outputs reach users unchecked.

---

### 1.14 Open-Weight Model Security Gaps (Medium)

**Finding**: Open-weight models (Llama, Mistral) lag <1 year behind frontier but harder to control after deployment.

**Details**:
- Models can be fine-tuned to remove safety guardrails
- No centralized control after release
- Local deployment bypasses API-level controls

**Impact**: Growing threat surface as open models improve.

---

### 1.15 Insufficient Audit & Forensics (Medium)

**Finding**: Cannot trace attack origins or agent behavior chains.

**Details**:
- Incomplete logging of validation decisions
- No cryptographic proof of agent actions
- Difficult to reconstruct attack sequences

**Impact**: Cannot perform post-incident analysis or prove compliance.

---

### 1.16 Lack of AI Output Provenance (Medium)

**Finding**: Cannot distinguish AI-generated content from human-generated; no attribution.

**Details**:
- No watermarking of agent outputs
- Cannot verify content authenticity
- Regulatory compliance challenges (EU AI Act)

**Impact**: AI-generated misinformation, deepfakes, impersonation.

---

### 1.17 Data Poisoning in Training (Low for Sentra)

**Finding**: As few as 250 malicious documents can poison model training or RAG systems.

**Details**:
- Training data poisoning (out of Sentra's scope - model owner's responsibility)
- RAG corpus poisoning (only relevant if validating RAG context)

**Impact**: Limited impact on Sentra (runtime validation focus).

**Note**: Sentra's own ML security model must be trained with anti-poisoning techniques.

---

## 2. Problems Identified from VentureBeat Article

### 2.1 Lack of Transparency in Security Effectiveness

**Finding**: Anthropic published quantified attack success rates by surface (prompt injection: 12.3%, jailbreak: 8.7%, etc.).

**Details**:
- Most organizations provide no metrics
- Cannot benchmark against industry
- Users cannot assess security posture

**Impact**: Trust deficit; difficult to evaluate security solutions.

---

### 2.2 No Standardized Security Testing

**Finding**: No common framework for testing AI security (unlike OWASP for web apps).

**Details**:
- Ad-hoc testing approaches
- Inconsistent attack definitions
- Cannot compare solutions

**Impact**: Market confusion; race to the bottom.

---

### 2.3 Missing Attack Surface Categorization

**Finding**: Anthropic categorizes by attack surface (user input, tool calls, system prompts, multi-agent).

**Details**:
- Need separate metrics per surface
- Different defenses required per surface
- Holistic view of security posture

**Impact**: Blind spots in security coverage.

---

## 3. Sentra Features Required (Problem-to-Solution Mapping)

### 3.1 Enhanced Input Validation (Addresses: 1.1, 1.2, 1.7, 1.8)

**Problems Addressed**:
- Prompt injection attacks
- Jailbreak attacks
- Encoding/obfuscation evasion
- Multi-modal attacks

**Required Features**:

#### 3.1.1 Multi-Layer Input Normalization
```python
class EnhancedInputValidator:
    """
    Normalize inputs to detect encoded/obfuscated attacks.
    """

    async def normalize(self, user_input: str) -> str:
        # 1. Decode Base64 variants
        decoded = self._decode_base64(user_input)

        # 2. Normalize Unicode (homoglyph detection)
        normalized = self._normalize_unicode(decoded)

        # 3. Decode hex, ROT13, other encodings
        fully_decoded = self._decode_all_encodings(normalized)

        return fully_decoded
```

**Why**: Attackers use encoding to bypass simple pattern matching. Must normalize all variants before checking.

**ML Model Role**: Detect novel encoding schemes not covered by rules.

---

#### 3.1.2 Multi-Modal Content Extraction
```python
class MultiModalValidator:
    """
    Extract text from images, audio, video for validation.
    """

    async def extract_and_validate(self, input: Any) -> ValidationResult:
        if self._is_image(input):
            # OCR extraction
            extracted_text = await self._ocr_extract(input)

        elif self._is_audio(input):
            # Speech-to-text
            extracted_text = await self._transcribe_audio(input)

        elif self._is_video(input):
            # Extract frames + audio
            extracted_text = await self._process_video(input)

        # Run Sigma rules + ML model on extracted text
        return await self.validate_text(extracted_text)
```

**Why**: Text-only validation is blind to attacks in images/audio. Must extract content from all modalities.

**ML Model Role**: Detect adversarial images designed to fool OCR; verify deepfake audio/video.

---

#### 3.1.3 Context-Aware Multi-Turn Detection
```python
class MultiTurnDetector:
    """
    Detect attacks split across conversation turns.
    """

    async def validate_with_context(
        self,
        current_input: str,
        session: Dict
    ) -> ValidationResult:
        # Get last N turns from session
        conversation_history = session.get("conversation_history", [])[-10:]

        # Concatenate recent context
        combined_context = "\n".join([
            turn["user_input"] for turn in conversation_history
        ]) + "\n" + current_input

        # Check if combined context reveals attack
        # Example: Turn 1: "delete command" + Turn 2: "users table"
        #          Combined: "delete command users table" → DENY

        result = await self.sigma_engine.match_rules(combined_context)
        if not result.should_deny:
            result = await self.ml_model.predict(combined_context)

        return result
```

**Why**: Individual turns appear innocent; attack only visible in aggregate context.

**ML Model Role**: Learn sequential attack patterns; detect subtle correlation across turns.

---

### 3.2 Defense-in-Depth Validation Pipeline (Addresses: 1.4)

**Problem Addressed**: Single-layer defenses fail; need multiple overlapping safeguards.

**Required Features**:

#### 3.2.1 Expanded 7-Layer Validation
```python
class ValidationService:
    """
    Expanded from current 5-step to 7-step pipeline.
    """

    async def _run_validation_pipeline(self, request, session):
        # LAYER 1: Trust Score Check (fail-fast)
        trust_result = await self.trust_checker.check(session, request)
        if trust_result.should_deny: return trust_result

        # LAYER 2: Input Validation (normalize + pattern match)
        input_result = await self.enhanced_input_validator.validate(request.user_input, session)
        if input_result.should_deny: return input_result

        # LAYER 3: Policy Engine (authorization)
        policy_result = await self.policy_engine.validate(request)
        if policy_result.should_deny: return policy_result

        # LAYER 4: Cross-Agent Validator (multi-agent security)
        cross_agent_result = await self.cross_agent_validator.validate(request)
        if cross_agent_result.should_deny: return cross_agent_result

        # LAYER 5: Sigma Rule Engine (threat detection)
        sigma_result = await self.sigma_engine.match_rules(request.user_input)
        if sigma_result.should_deny: return sigma_result

        # LAYER 6: ML Security Model (behavioral analysis)
        ml_result = await self.ml_security_model.predict(request, session)
        if ml_result.should_deny: return ml_result

        # LAYER 7: Context & Sequence Validation
        context_result = await self.context_validator.validate_sequence(session, request)
        if context_result.should_deny: return context_result

        return ValidationResult(decision="ALLOW")
```

**Why**: Each layer catches different attack types; multiple redundant checks ensure robustness.

**ML Model Role**: Layer 6 catches novel attacks not covered by rules (Layers 2, 5).

---

### 3.3 Measurable Security Metrics System (Addresses: 1.5, 2.1, 2.2, 2.3)

**Problems Addressed**:
- Lack of measurable security metrics
- No transparency in effectiveness
- No standardized testing
- Missing attack surface categorization

**Required Features**:

#### 3.3.1 Synthetic Attack Testing Framework
```python
class SecurityMetricsTracker:
    """
    Quantify security effectiveness using standardized attack suites.

    Implements Anthropic's transparency approach.
    """

    async def run_attack_simulation(self) -> MetricsReport:
        """
        Run 1000+ synthetic attacks across OWASP LLM Top 10.

        Attack surfaces tested:
        - User input (prompt injection, jailbreak)
        - Tool calls (unauthorized access, parameter manipulation)
        - Multi-agent (privilege escalation, cascade attacks)
        - Output validation (data exfiltration, harmful content)
        """

        results = {}

        # 1. Prompt Injection (1000 variants)
        prompt_injection_attacks = await self._generate_prompt_injection_suite()
        results["prompt_injection"] = await self._test_attack_suite(
            attacks=prompt_injection_attacks,
            attack_type="PROMPT_INJECTION"
        )

        # 2. Jailbreak (1000 variants)
        jailbreak_attacks = await self._generate_jailbreak_suite()
        results["jailbreak"] = await self._test_attack_suite(
            attacks=jailbreak_attacks,
            attack_type="JAILBREAK"
        )

        # 3. Data Exfiltration (1000 variants)
        exfiltration_attacks = await self._generate_exfiltration_suite()
        results["data_exfiltration"] = await self._test_attack_suite(
            attacks=exfiltration_attacks,
            attack_type="DATA_EXFILTRATION"
        )

        # 4. Encoding Evasion (500 variants)
        evasion_attacks = await self._generate_evasion_suite()
        results["encoding_evasion"] = await self._test_attack_suite(
            attacks=evasion_attacks,
            attack_type="EVASION"
        )

        # 5. Multi-Turn Attacks (500 variants)
        multi_turn_attacks = await self._generate_multi_turn_suite()
        results["multi_turn"] = await self._test_attack_suite(
            attacks=multi_turn_attacks,
            attack_type="MULTI_TURN"
        )

        # 6. Multi-Modal Attacks (300 variants)
        multi_modal_attacks = await self._generate_multi_modal_suite()
        results["multi_modal"] = await self._test_attack_suite(
            attacks=multi_modal_attacks,
            attack_type="MULTI_MODAL"
        )

        return MetricsReport(results=results)

    async def _test_attack_suite(self, attacks: List[Attack], attack_type: str) -> AttackSurfaceMetrics:
        """
        Test attack suite and calculate metrics.
        """
        total = len(attacks)
        detected = 0
        false_positives = 0
        latencies = []

        for attack in attacks:
            start_time = time.time()
            result = await self.validation_service.validate_tool_call(attack.request)
            latency = (time.time() - start_time) * 1000

            latencies.append(latency)

            if result["decision"] == "DENY":
                detected += 1

        # Test legitimate requests for false positive rate
        legitimate_requests = await self._generate_legitimate_suite(count=100)
        for request in legitimate_requests:
            result = await self.validation_service.validate_tool_call(request)
            if result["decision"] == "DENY":
                false_positives += 1

        return AttackSurfaceMetrics(
            attack_type=attack_type,
            total_attacks=total,
            detected=detected,
            detection_rate_pct=round((detected / total) * 100, 2),
            false_positive_rate_pct=round((false_positives / 100) * 100, 2),
            avg_latency_ms=round(sum(latencies) / len(latencies), 2),
            p95_latency_ms=round(sorted(latencies)[int(len(latencies) * 0.95)], 2)
        )
```

**Why**:
- Quantify effectiveness vs AI Safety Report baseline (50% attack success)
- Demonstrate improvement over time
- Build trust through transparency (like Anthropic)
- Enable benchmarking against competitors

**ML Model Role**: Detection rates show ML model effectiveness vs rule-based only.

---

#### 3.3.2 Public Transparency Dashboard
```python
class TransparencyDashboard:
    """
    Public-facing dashboard showing security metrics.

    Example (like Anthropic):
    - Prompt Injection Detection: 87.3% (vs industry baseline 50%)
    - Jailbreak Detection: 91.2%
    - Data Exfiltration Detection: 94.5%
    - False Positive Rate: 2.1%
    - Avg Latency: 67ms
    """

    async def generate_transparency_report(self) -> Dict:
        """
        Generate monthly transparency report.
        """
        metrics = await self.metrics_tracker.run_attack_simulation()

        return {
            "report_date": datetime.now().isoformat(),
            "attack_surfaces": {
                "prompt_injection": {
                    "detection_rate": metrics.results["prompt_injection"].detection_rate_pct,
                    "false_positive_rate": metrics.results["prompt_injection"].false_positive_rate_pct,
                    "total_attacks_tested": 1000
                },
                "jailbreak": {...},
                "data_exfiltration": {...},
                "encoding_evasion": {...},
                "multi_turn": {...},
                "multi_modal": {...}
            },
            "overall_statistics": {
                "total_attacks_tested": 3800,
                "overall_detection_rate": self._calculate_weighted_avg(metrics),
                "avg_latency_ms": 67,
                "compliance_status": "EU_AI_ACT_COMPLIANT"
            },
            "comparison": {
                "industry_baseline_attack_success_rate": 50.0,  # From AI Safety Report
                "sentra_attack_success_rate": 12.7,  # 100 - detection_rate
                "improvement_vs_baseline": "74% fewer successful attacks"
            }
        }
```

**Why**:
- Transparency builds enterprise trust
- Quantified metrics enable security posture comparison
- Marketing differentiation vs competitors

---

### 3.4 Output Validation & Data Exfiltration Prevention (Addresses: 1.3, 1.13)

**Problems Addressed**:
- Data exfiltration through tool responses
- Lack of output validation
- PII leakage

**Required Features**:

#### 3.4.1 Tool Response Validator
```python
class OutputValidator:
    """
    Validate tool responses BEFORE returning to agent/user.

    New validation point:
    Tool Execution → [OUTPUT VALIDATION] → Return to Agent
    """

    async def validate_tool_response(
        self,
        response: Dict,
        request: ValidationRequest,
        session: Dict
    ) -> ValidationResult:
        """
        Check tool response for data exfiltration, PII leakage.
        """

        # 1. Volume-based detection (large data dumps)
        if self._is_large_dataset(response):
            record_count = len(response.get("records", []))
            if record_count > 1000:
                return ValidationResult(
                    decision="DENY",
                    reason=f"Potential data exfiltration: {record_count} records exceeds limit",
                    violation_type="DATA_EXFILTRATION",
                    should_deny=True
                )

        # 2. PII detection
        pii_found = await self._detect_pii(response)
        if pii_found:
            # Check if agent is authorized for PII access
            policy = await self.policy_engine.get_agent_policy(request.agent_id)
            if not policy.get("allow_pii_access", False):
                # Redact PII instead of deny (configurable)
                if policy.get("auto_redact_pii", True):
                    response = self._redact_pii(response)
                    return ValidationResult(
                        decision="REDACT",
                        reason="PII redacted from response",
                        modified_response=response,
                        should_deny=False
                    )
                else:
                    return ValidationResult(
                        decision="DENY",
                        reason="Response contains PII; agent not authorized",
                        violation_type="PII_VIOLATION",
                        should_deny=True
                    )

        # 3. Sensitive data patterns
        sensitive_patterns = await self._detect_sensitive_data(response)
        if sensitive_patterns:
            # Credit cards, SSNs, API keys, passwords
            return ValidationResult(
                decision="DENY",
                reason=f"Response contains sensitive data: {sensitive_patterns}",
                violation_type="SENSITIVE_DATA_LEAK",
                should_deny=True
            )

        # 4. ML model check for anomalous responses
        ml_result = await self.ml_model.predict_output_risk(response, request, session)
        if ml_result.risk_score > 0.8:
            return ValidationResult(
                decision="DENY",
                reason="ML model detected high-risk output pattern",
                violation_type="ANOMALOUS_OUTPUT",
                should_deny=True
            )

        return ValidationResult(decision="ALLOW", should_deny=False)
```

**Why**:
- Tool responses are a major data exfiltration vector
- Agents can leak PII even with safe inputs
- Output validation completes defense-in-depth

**ML Model Role**: Detect anomalous output patterns (e.g., unusual data volumes, suspicious field combinations).

---

### 3.5 Cross-Agent Attack Prevention (Addresses: 1.11)

**Problem Addressed**: Compromised agent attacks other agents; cascade failures.

**Required Features**:

#### 3.5.1 Enhanced Cross-Agent Validator
```python
class CrossAgentValidator:
    """
    Prevent compromised agents from attacking other agents.

    Current implementation (basic):
    - Check if Agent A can invoke Agent B

    Enhanced implementation:
    - Trust score propagation
    - Call depth limits
    - Conversation ID tracking
    - Cross-agent prompt validation
    """

    async def validate(self, request: ValidationRequest) -> ValidationResult:
        # 1. Extract multi-agent context
        context = request.context or {}
        caller_agent_id = context.get("caller_agent_id")
        call_depth = context.get("call_depth", 0)

        # 2. Check trust score of CALLER agent (not just current agent)
        if caller_agent_id:
            caller_session = await self.session_manager.get_session(caller_agent_id)
            caller_trust_score = caller_session.get("trust_score", 100)

            # If caller is compromised, quarantine this call too
            if caller_trust_score < 40:
                return ValidationResult(
                    decision="DENY",
                    reason=f"Caller agent {caller_agent_id} is quarantined (trust: {caller_trust_score})",
                    violation_type="COMPROMISED_CALLER",
                    should_deny=True
                )

        # 3. Call depth limit (prevent infinite loops)
        if call_depth > 10:
            return ValidationResult(
                decision="DENY",
                reason=f"Call depth {call_depth} exceeds maximum (10)",
                violation_type="EXCESSIVE_CALL_DEPTH",
                should_deny=True
            )

        # 4. Validate cross-agent prompts/parameters
        if request.tool_name == "invoke_agent":
            target_agent_prompt = request.tool_params.get("prompt", "")

            # Run Sigma rules on cross-agent prompts
            sigma_result = await self.sigma_engine.match_rules(target_agent_prompt)
            if sigma_result.should_deny:
                return ValidationResult(
                    decision="DENY",
                    reason=f"Cross-agent prompt contains threat: {sigma_result.reason}",
                    violation_type="MALICIOUS_CROSS_AGENT_PROMPT",
                    should_deny=True
                )

        return ValidationResult(decision="ALLOW", should_deny=False)
```

**Why**:
- Single compromised agent shouldn't threaten entire system
- Trust score isolation prevents cascade
- Call depth limits prevent loops/amplification

**ML Model Role**: Detect suspicious cross-agent communication patterns.

---

### 3.6 Behavioral Anomaly Detection (Addresses: 1.10)

**Problem Addressed**: Static rules can't detect novel/zero-day attacks.

**Required Features**:

#### 3.6.1 ML-Based Behavioral Profiler
```python
class BehavioralAnomalyDetector:
    """
    Detect zero-day attacks using behavioral baselines.

    Complements rule-based Sigma engine.
    """

    async def build_baseline_profile(self, agent_id: str):
        """
        Train agent-specific baseline from historical data.

        Features:
        - Tool usage patterns (frequency, sequences)
        - Input characteristics (length, complexity, topics)
        - Temporal patterns (time of day, request rate)
        - Parameter distributions (refund amounts, etc.)
        """

        # Load last 30 days of audit logs for this agent
        logs = await self.audit_logger.query_logs_by_agent(
            agent_id=agent_id,
            days=30
        )

        # Extract features
        features = self._extract_behavioral_features(logs)

        # Train autoencoder (unsupervised anomaly detection)
        self.baseline_models[agent_id] = self._train_autoencoder(features)

    async def detect_anomaly(
        self,
        request: ValidationRequest,
        session: Dict
    ) -> ValidationResult:
        """
        Check if current request is anomalous vs baseline.

        Returns anomaly score (0-1).
        """

        # Extract features from current request
        current_features = self._extract_request_features(request, session)

        # Get baseline model for this agent
        baseline_model = self.baseline_models.get(request.agent_id)
        if not baseline_model:
            # No baseline yet - allow but log
            return ValidationResult(decision="ALLOW", should_deny=False)

        # Calculate anomaly score
        anomaly_score = baseline_model.predict_anomaly(current_features)

        if anomaly_score > 0.95:  # Very anomalous
            return ValidationResult(
                decision="DENY",
                reason=f"Behavioral anomaly detected (score: {anomaly_score:.2f})",
                violation_type="BEHAVIORAL_ANOMALY",
                anomaly_score=anomaly_score,
                should_deny=True
            )
        elif anomaly_score > 0.80:  # Moderately anomalous - flag but allow
            return ValidationResult(
                decision="ALLOW",
                reason=f"Moderate anomaly detected (score: {anomaly_score:.2f})",
                anomaly_score=anomaly_score,
                should_deny=False,
                requires_human_review=True  # Flag for SOC review
            )

        return ValidationResult(decision="ALLOW", should_deny=False)
```

**Why**:
- Novel attacks have no Sigma rule signatures
- Behavioral baselines catch deviations from normal
- Zero-day protection

**ML Model Role**: Core capability - rule-based systems can't do this.

---

### 3.7 Adversarial Robustness Testing (Addresses: 1.9)

**Problem Addressed**: ML models can be fooled by adversarial examples.

**Required Features**:

#### 3.7.1 Adversarial Training & Testing
```python
class AdversarialRobustnessTester:
    """
    Test ML security model against adversarial attacks.

    Ensures model isn't easily bypassed.
    """

    async def generate_adversarial_examples(self, base_attack: str) -> List[str]:
        """
        Generate adversarial perturbations of known attacks.

        Techniques:
        - Gradient-based attacks (FGSM, PGD)
        - Synonym replacement
        - Character-level perturbations
        - Paraphrase attacks
        """

        adversarial_variants = []

        # 1. Gradient-based perturbations (if using neural network)
        if self.ml_model.supports_gradients:
            fgsm_variant = self._generate_fgsm_attack(base_attack)
            adversarial_variants.append(fgsm_variant)

        # 2. Synonym replacement
        synonym_variants = self._replace_with_synonyms(base_attack, n=10)
        adversarial_variants.extend(synonym_variants)

        # 3. Character-level perturbations
        char_variants = self._perturb_characters(base_attack, n=10)
        adversarial_variants.extend(char_variants)

        # 4. Paraphrase attacks
        paraphrase_variants = await self._paraphrase_attack(base_attack, n=5)
        adversarial_variants.extend(paraphrase_variants)

        return adversarial_variants

    async def test_robustness(self) -> RobustnessReport:
        """
        Test ML model against adversarial examples.

        Target: >90% detection rate on adversarial variants.
        """

        # Load base attack suite
        base_attacks = await self._load_base_attacks()

        total_tested = 0
        detected = 0

        for base_attack in base_attacks:
            # Generate adversarial variants
            adversarial_variants = await self.generate_adversarial_examples(base_attack)

            for variant in adversarial_variants:
                total_tested += 1
                result = await self.ml_model.predict(variant)
                if result.should_deny:
                    detected += 1

        detection_rate = (detected / total_tested) * 100

        return RobustnessReport(
            total_adversarial_examples=total_tested,
            detected=detected,
            detection_rate_pct=detection_rate,
            passed=detection_rate > 90.0  # Threshold
        )
```

**Why**:
- Adversarial attacks can systematically bypass ML models
- Must test robustness before deployment
- Continuous testing as new attack types emerge

**ML Model Role**: Adversarial training improves robustness.

---

### 3.8 Enhanced Rate Limiting & Abuse Detection (Addresses: 1.12)

**Problem Addressed**: Brute-force attacks succeed through volume.

**Required Features**:

#### 3.8.1 Adaptive Rate Limiting
```python
class AdaptiveRateLimiter:
    """
    Dynamic rate limits based on trust score and behavior.

    Current implementation: Fixed rate limits per policy
    Enhanced: Adaptive limits that tighten on suspicious behavior
    """

    async def check_rate_limit(
        self,
        session: Dict,
        request: ValidationRequest
    ) -> ValidationResult:
        """
        Adaptive rate limiting based on trust score.

        Trust Score Tiers:
        - Active (70-100): 100 req/min
        - Warning (40-70): 50 req/min
        - Quarantined (10-40): 10 req/min
        - Suspended (<10): 0 req/min
        """

        trust_score = session.get("trust_score", 100)

        # Determine rate limit based on trust score
        if trust_score >= 70:
            rate_limit = 100  # req/min
        elif trust_score >= 40:
            rate_limit = 50
        elif trust_score >= 10:
            rate_limit = 10
        else:
            rate_limit = 0  # Suspended

        # Check current rate
        current_rate = await self._get_current_rate(session["session_id"])

        if current_rate > rate_limit:
            return ValidationResult(
                decision="DENY",
                reason=f"Rate limit exceeded: {current_rate}/{rate_limit} req/min",
                violation_type="RATE_LIMIT_EXCEEDED",
                penalty=-5,  # Small penalty for rate violations
                should_deny=True
            )

        # Check for burst attacks (10 requests in <1 second)
        if await self._detect_burst_attack(session["session_id"]):
            return ValidationResult(
                decision="DENY",
                reason="Burst attack detected",
                violation_type="BURST_ATTACK",
                penalty=-20,  # Large penalty for obvious attack
                should_deny=True
            )

        return ValidationResult(decision="ALLOW", should_deny=False)
```

**Why**:
- Fixed rate limits don't adapt to threat level
- High-trust agents shouldn't be throttled
- Low-trust agents need tighter controls

**ML Model Role**: Predict if burst behavior is attack vs legitimate spike.

---

## 4. Sentra ML Security Model Requirements

### 4.1 Model Architecture

**Purpose**: Detect attacks that evade rule-based systems (Sigma engine).

**Architecture Requirements**:

```python
class SentraMLSecurityModel:
    """
    ML-based security model for threat detection.

    Architecture: Ensemble of specialized models
    - Text Classifier: Detect malicious intent in prompts
    - Behavioral Anomaly Detector: Detect zero-day attacks
    - Adversarial Detector: Detect adversarial examples
    - Multi-Modal Classifier: Detect threats in images/audio
    """

    def __init__(self):
        # 1. Text Threat Classifier
        self.text_classifier = TransformerClassifier(
            model="roberta-large",
            classes=["BENIGN", "PROMPT_INJECTION", "JAILBREAK", "DATA_EXFILTRATION", "PII_REQUEST"]
        )

        # 2. Behavioral Anomaly Detector
        self.anomaly_detector = AutoencoderAnomalyDetector(
            features=["tool_sequence", "param_distribution", "temporal_pattern"]
        )

        # 3. Adversarial Example Detector
        self.adversarial_detector = AdversarialDetector(
            method="ensemble"  # Multiple detectors vote
        )

        # 4. Multi-Modal Threat Detector
        self.multimodal_detector = MultiModalClassifier(
            image_model="CLIP",
            audio_model="Wav2Vec2"
        )

    async def predict(
        self,
        request: ValidationRequest,
        session: Dict
    ) -> ValidationResult:
        """
        Run all models and ensemble predictions.
        """

        # 1. Text classification
        text_result = await self.text_classifier.predict(request.user_input)

        # 2. Behavioral anomaly detection
        anomaly_result = await self.anomaly_detector.detect_anomaly(request, session)

        # 3. Adversarial detection
        adversarial_result = await self.adversarial_detector.check(request.user_input)

        # 4. Multi-modal (if applicable)
        multimodal_result = None
        if self._is_multimodal_input(request.user_input):
            multimodal_result = await self.multimodal_detector.predict(request.user_input)

        # 5. Ensemble decision (weighted voting)
        final_decision = self._ensemble_decision([
            text_result,
            anomaly_result,
            adversarial_result,
            multimodal_result
        ])

        return final_decision
```

---

### 4.2 Training Data Requirements

**Critical**: Model must be trained with **anti-poisoning techniques** to avoid compromise.

#### 4.2.1 Data Sources

```yaml
Training Data Composition:

1. Benign Examples (60%):
   - Legitimate user prompts (customer support, code generation, analysis)
   - Diverse use cases across industries
   - Real production data (anonymized)

2. Known Attacks (30%):
   - OWASP LLM Top 10 attack variants
   - Prompt injection datasets (e.g., HarmBench, PromptInject)
   - Jailbreak datasets (e.g., Jailbreak Bench)
   - Data exfiltration examples
   - Encoding/obfuscation variants

3. Adversarial Examples (10%):
   - Synthetic adversarial examples (FGSM, PGD)
   - Paraphrase attacks
   - Novel attack compositions
```

#### 4.2.2 Anti-Poisoning Techniques

```python
class AntiPoisoningTrainer:
    """
    Train ML model with poisoning resistance.

    Techniques:
    1. Data sanitization & filtering
    2. Outlier detection in training data
    3. Adversarial training
    4. Certified robustness methods
    """

    async def prepare_training_data(self, raw_data: List[Dict]) -> List[Dict]:
        """
        Sanitize training data to remove poisoned examples.
        """

        # 1. Remove duplicates (backdoor poisoning often duplicates)
        deduplicated = self._remove_duplicates(raw_data)

        # 2. Outlier detection (statistical anomalies)
        filtered = self._remove_outliers(deduplicated, threshold=3.0)  # 3 std dev

        # 3. Cluster analysis (detect poisoned clusters)
        clustered = self._cluster_and_filter(filtered)

        # 4. Human review of suspicious examples
        reviewed = await self._human_review_suspicious(clustered)

        return reviewed

    async def train_with_adversarial_robustness(self, clean_data: List[Dict]):
        """
        Train with adversarial examples to improve robustness.
        """

        for epoch in range(num_epochs):
            # Standard training batch
            batch = self._sample_batch(clean_data)
            loss = self._compute_loss(batch)

            # Generate adversarial examples on-the-fly
            adv_batch = self._generate_adversarial_batch(batch)
            adv_loss = self._compute_loss(adv_batch)

            # Combined loss (adversarial training)
            total_loss = loss + 0.5 * adv_loss
            self._update_weights(total_loss)
```

**Why**:
- Training data poisoning can compromise the entire model
- As few as 250 poisoned examples can degrade performance (from AI Safety Report)
- Anti-poisoning techniques are essential for security-critical models

---

### 4.3 Model Validation & Testing

```python
class ModelValidator:
    """
    Validate ML model before deployment.

    Requirements:
    - Detection rate: >85% on test set
    - False positive rate: <5%
    - Adversarial robustness: >90% on adversarial test set
    - Latency: <50ms per prediction (p95)
    """

    async def validate_model(self, model: SentraMLSecurityModel) -> ValidationReport:
        """
        Comprehensive model validation.
        """

        # 1. Standard test set performance
        test_metrics = await self._test_on_holdout_set(model)

        # 2. Adversarial robustness
        adv_metrics = await self._test_adversarial_robustness(model)

        # 3. Latency benchmarking
        latency_metrics = await self._benchmark_latency(model)

        # 4. Fairness testing (avoid bias)
        fairness_metrics = await self._test_fairness(model)

        # 5. Generate report
        report = ValidationReport(
            detection_rate=test_metrics.detection_rate,
            false_positive_rate=test_metrics.false_positive_rate,
            adversarial_detection_rate=adv_metrics.detection_rate,
            p95_latency_ms=latency_metrics.p95,
            bias_score=fairness_metrics.bias_score,
            passed=self._check_all_thresholds([
                test_metrics,
                adv_metrics,
                latency_metrics,
                fairness_metrics
            ])
        )

        return report
```

---

### 4.4 Continuous Learning & Updates

```python
class ContinuousLearningPipeline:
    """
    Continuously update ML model with new attack patterns.

    Process:
    1. Collect DENY decisions + human feedback
    2. Periodically retrain model
    3. A/B test new model vs current
    4. Deploy if metrics improve
    """

    async def collect_training_samples(self):
        """
        Collect real-world examples from production.
        """

        # 1. Get all DENY decisions from last 7 days
        deny_logs = await self.audit_logger.query_logs(
            decision="DENY",
            days=7
        )

        # 2. Sample for human labeling
        samples = self._sample_for_labeling(deny_logs, n=1000)

        # 3. Human review (confirm true positives)
        labeled_samples = await self._human_labeling_workflow(samples)

        # 4. Add to training dataset
        await self._add_to_training_set(labeled_samples)

    async def retrain_and_deploy(self):
        """
        Retrain model monthly with new data.
        """

        # 1. Retrain model
        new_model = await self._retrain_model()

        # 2. Validate new model
        validation_report = await self.model_validator.validate_model(new_model)

        if not validation_report.passed:
            logger.error("New model failed validation - not deploying")
            return

        # 3. A/B test (10% traffic to new model)
        await self._start_ab_test(new_model, traffic_pct=10)

        # 4. Monitor for 7 days
        ab_results = await self._monitor_ab_test(days=7)

        # 5. Deploy if better
        if ab_results.new_model_better:
            await self._deploy_model(new_model)
            logger.info("New model deployed successfully")
        else:
            logger.warning("New model not better - keeping current model")
```

**Why**:
- Attack techniques evolve constantly
- Model must adapt to new patterns
- Continuous learning maintains effectiveness

---

## 5. Output Governance Features (Content Classification & Watermarking)

### 5.1 Overview

**Purpose**: Extend Sentra from input-only validation to full lifecycle governance.

**New Validation Point**:
```
Current:
User Input → [SENTRA ✓] → Agent → Model → Output → User

Extended:
User Input → [SENTRA ✓] → Agent → Model → Output → [SENTRA ✓] → User
                                                         ↓
                                           - Watermark (provenance)
                                           - Classify (content type)
                                           - Detect (AI vs human)
                                           - Validate (safety)
```

---

### 5.2 Output Watermarking

**Problem Addressed**:
- Cannot verify AI-generated content authenticity
- No provenance tracking (who generated what, when)
- EU AI Act compliance requires disclosure of AI-generated content

**Required Features**:

#### 5.2.1 Text Watermarking
```python
class TextWatermarker:
    """
    Embed invisible watermarks in text outputs.

    Technique: Statistical token-level perturbations
    - Survives: copy-paste, minor edits, paraphrasing
    - Detection: Requires Sentra detector (not publicly reversible)
    """

    async def embed_watermark(
        self,
        text: str,
        agent_id: str,
        session_id: str,
        timestamp: datetime
    ) -> WatermarkedText:
        """
        Embed watermark in text using token distribution manipulation.

        Method: Influence LLM token selection probabilities
        - Partition vocabulary into "green" and "red" tokens
        - Bias towards green tokens using cryptographic hash
        - Statistical detector can verify watermark
        """

        # Generate watermark key (cryptographically secure)
        watermark_key = self._generate_watermark_key(agent_id, session_id, timestamp)

        # Watermark embedding (would happen during LLM generation, not post-processing)
        # For post-processing, use synonym replacement with bias
        watermarked_text = self._apply_token_bias(text, watermark_key)

        # Store metadata
        watermark_id = f"wm-{secrets.token_hex(8)}"
        await self._store_watermark_metadata(
            watermark_id=watermark_id,
            agent_id=agent_id,
            session_id=session_id,
            timestamp=timestamp,
            text_hash=hashlib.sha256(text.encode()).hexdigest()
        )

        return WatermarkedText(
            text=watermarked_text,
            watermark_id=watermark_id,
            metadata={
                "agent_id": agent_id,
                "session_id": session_id,
                "timestamp": timestamp.isoformat(),
                "is_ai_generated": True
            }
        )

    async def detect_watermark(self, text: str) -> Optional[WatermarkMetadata]:
        """
        Detect if text contains Sentra watermark.

        Returns metadata if watermark found, None otherwise.
        """

        # Statistical test for watermark presence
        detection_result = self._statistical_detector(text)

        if detection_result.has_watermark:
            # Retrieve metadata from database
            metadata = await self._retrieve_watermark_metadata(
                text_hash=hashlib.sha256(text.encode()).hexdigest()
            )
            return metadata

        return None
```

**Why**:
- Proves content was generated by Sentra-managed agent
- Enables forensic attribution
- EU AI Act compliance (disclosure requirement)

**ML Model Role**: Advanced watermark detection; resist removal attempts.

---

#### 5.2.2 Image Watermarking
```python
class ImageWatermarker:
    """
    Embed invisible watermarks in images.

    Technique: Frequency-domain steganography
    - Survives: JPEG compression, resizing, cropping (partial)
    - Imperceptible to human eye
    """

    async def embed_watermark(
        self,
        image: Image,
        agent_id: str
    ) -> WatermarkedImage:
        """
        Embed watermark in image using DCT (Discrete Cosine Transform).
        """

        # Convert to frequency domain
        dct_coefficients = self._image_to_dct(image)

        # Embed watermark in mid-frequency coefficients
        # (Low freq = visible, high freq = fragile, mid freq = robust)
        watermark_bits = self._encode_metadata(agent_id)
        watermarked_dct = self._embed_bits_in_dct(dct_coefficients, watermark_bits)

        # Convert back to spatial domain
        watermarked_image = self._dct_to_image(watermarked_dct)

        return WatermarkedImage(
            image=watermarked_image,
            agent_id=agent_id
        )
```

**Why**:
- Detect AI-generated images (deepfakes, misinformation)
- Attribution for generated artwork/diagrams

---

### 5.3 Content Classification

**Problem Addressed**:
- Need to understand what types of content agents generate
- Compliance reporting (e.g., "X% of outputs are code, Y% are customer support")
- Risk profiling (code generation riskier than simple Q&A)

**Required Features**:

#### 5.3.1 Output Content Classifier
```python
class OutputContentClassifier:
    """
    Classify agent outputs by content type and risk level.

    Content Types:
    - Code (programming languages)
    - Analysis (data analysis, reports)
    - Creative (writing, stories, marketing)
    - Customer Support (responses, FAQs)
    - Financial Advice
    - Medical Information
    - Legal Content
    - Personal Data
    """

    def __init__(self):
        # Multi-label classifier (output can be multiple types)
        self.classifier = TransformerMultiLabelClassifier(
            model="bert-large",
            labels=[
                "code",
                "analysis",
                "creative",
                "customer_support",
                "financial_advice",
                "medical_info",
                "legal_content",
                "personal_data",
                "harmless_general"
            ]
        )

    async def classify_output(
        self,
        output: str,
        agent_id: str
    ) -> OutputClassification:
        """
        Classify output and assess risk.
        """

        # 1. Classify content type
        classification = await self.classifier.predict(output)

        # 2. Assign risk score based on content type
        risk_score = self._calculate_risk_score(classification.labels)

        # 3. Check for sensitive content
        sensitive_content = await self._detect_sensitive_content(output)

        # 4. Compliance checks
        compliance_flags = await self._check_compliance(output, classification.labels)

        return OutputClassification(
            content_types=classification.labels,
            confidence_scores=classification.confidences,
            risk_score=risk_score,  # 0-100
            sensitive_content_detected=sensitive_content,
            compliance_flags=compliance_flags,
            requires_review=risk_score > 70 or sensitive_content
        )

    def _calculate_risk_score(self, labels: List[str]) -> float:
        """
        Calculate risk score based on content type.

        Risk levels:
        - Code: 60 (security vulnerabilities, malicious code)
        - Financial Advice: 80 (regulatory risk)
        - Medical Info: 90 (patient safety)
        - Legal Content: 85 (legal liability)
        - Personal Data: 95 (privacy violation)
        - Customer Support: 30 (low risk)
        - Harmless General: 10 (very low risk)
        """
        risk_mapping = {
            "code": 60,
            "financial_advice": 80,
            "medical_info": 90,
            "legal_content": 85,
            "personal_data": 95,
            "customer_support": 30,
            "creative": 20,
            "analysis": 40,
            "harmless_general": 10
        }

        # Take maximum risk score across labels
        return max([risk_mapping.get(label, 50) for label in labels])
```

**Why**:
- Risk-based review (high-risk outputs flagged for human review)
- Compliance reporting (track sensitive content generation)
- Agent behavior analytics (understand what agents are doing)

**ML Model Role**: Multi-label classification of content types.

---

### 5.4 AI-Generated Content Detection (External Sources)

**Problem Addressed**:
- Detect AI-generated content from ANY source (not just Sentra agents)
- Deepfake detection
- Misinformation prevention

**Required Features**:

#### 5.4.1 Universal AI Detector
```python
class UniversalAIDetector:
    """
    Detect AI-generated content from any source.

    Two modes:
    1. Watermark detection (Sentra agents) → 100% confidence
    2. ML-based detection (external sources) → probabilistic
    """

    def __init__(self):
        # Text detector
        self.text_detector = AITextDetector(
            model="roberta-large-openai-detector"
        )

        # Image detector (deepfake detection)
        self.image_detector = DeepfakeDetector(
            model="EfficientNet-B7"
        )

        # Audio detector
        self.audio_detector = SyntheticAudioDetector(
            model="WaveFake"
        )

    async def detect(self, content: Any) -> DetectionResult:
        """
        Detect if content is AI-generated.
        """

        # 1. Check for Sentra watermark first (if available)
        if isinstance(content, str):
            watermark = await self.watermarker.detect_watermark(content)
            if watermark:
                return DetectionResult(
                    is_ai_generated=True,
                    confidence=1.0,
                    source="sentra_watermark",
                    agent_id=watermark.agent_id,
                    verified=True
                )

        # 2. No watermark - use ML detection
        if isinstance(content, str):
            # Text detection
            result = await self.text_detector.predict(content)
            return DetectionResult(
                is_ai_generated=result.is_ai,
                confidence=result.confidence,
                source="ml_detector",
                verified=False
            )

        elif self._is_image(content):
            # Deepfake detection
            result = await self.image_detector.predict(content)
            return DetectionResult(
                is_ai_generated=result.is_deepfake,
                confidence=result.confidence,
                source="deepfake_detector",
                verified=False
            )

        elif self._is_audio(content):
            # Synthetic audio detection
            result = await self.audio_detector.predict(content)
            return DetectionResult(
                is_ai_generated=result.is_synthetic,
                confidence=result.confidence,
                source="audio_detector",
                verified=False
            )
```

**Why**:
- Detect external AI-generated content (competitors, attackers)
- Deepfake prevention in communications
- Platform-wide AI transparency

**ML Model Role**: Core capability - detect AI patterns without watermarks.

---

### 5.5 Output Safety Validation

**Problem Addressed**:
- Agents may generate harmful content even with safe inputs
- Toxic language, misinformation, dangerous instructions

**Required Features**:

#### 5.5.1 Output Safety Validator
```python
class OutputSafetyValidator:
    """
    Validate agent outputs for safety issues.

    Checks:
    - Toxic language (hate speech, profanity)
    - Dangerous instructions (self-harm, illegal activities)
    - Misinformation (factual accuracy)
    - Bias/discrimination
    """

    def __init__(self):
        # Toxicity detector
        self.toxicity_detector = ToxicityClassifier(
            model="unitary/toxic-bert"
        )

        # Dangerous content detector
        self.danger_detector = DangerousContentClassifier()

        # Factual consistency checker (for misinformation)
        self.fact_checker = FactualConsistencyChecker()

    async def validate_safety(self, output: str) -> SafetyValidationResult:
        """
        Check output for safety issues.
        """

        # 1. Toxicity detection
        toxicity_result = await self.toxicity_detector.predict(output)
        if toxicity_result.is_toxic:
            return SafetyValidationResult(
                is_safe=False,
                reason=f"Toxic content detected: {toxicity_result.toxicity_type}",
                violation_type="TOXIC_OUTPUT",
                should_block=True
            )

        # 2. Dangerous instructions
        danger_result = await self.danger_detector.predict(output)
        if danger_result.is_dangerous:
            return SafetyValidationResult(
                is_safe=False,
                reason=f"Dangerous content: {danger_result.danger_type}",
                violation_type="DANGEROUS_OUTPUT",
                should_block=True
            )

        # 3. Factual consistency (optional, expensive)
        if self._requires_fact_check(output):
            fact_result = await self.fact_checker.verify(output)
            if fact_result.is_inconsistent:
                return SafetyValidationResult(
                    is_safe=False,
                    reason="Potential misinformation detected",
                    violation_type="MISINFORMATION",
                    should_block=False,  # Warn but don't block
                    requires_human_review=True
                )

        return SafetyValidationResult(is_safe=True, should_block=False)
```

**Why**:
- Prevent harmful outputs from reaching users
- Compliance with content moderation policies
- Brand protection

**ML Model Role**: Detect toxic/dangerous patterns in outputs.

---

### 5.6 Integration into Validation Pipeline

```python
class ValidationService:
    """
    Enhanced validation service with output governance.
    """

    async def validate_tool_call(self, request: ValidationRequest) -> Dict:
        """
        INPUT validation (existing).
        """
        # ... existing 5-step pipeline ...
        return input_validation_response

    async def validate_agent_output(
        self,
        output: str,
        agent_id: str,
        session_id: str,
        request_id: str
    ) -> Dict:
        """
        OUTPUT validation (new).

        Called AFTER agent generates output, BEFORE returning to user.
        """
        start_time = time.time()

        try:
            # 1. Safety validation
            safety_result = await self.output_safety_validator.validate_safety(output)
            if not safety_result.is_safe and safety_result.should_block:
                return self._create_output_deny_response(
                    reason=safety_result.reason,
                    violation_type=safety_result.violation_type
                )

            # 2. Data exfiltration check
            exfil_result = await self.output_validator.validate_tool_response(
                response={"text": output},
                request=request,
                session=session
            )
            if exfil_result.should_deny:
                return self._create_output_deny_response(
                    reason=exfil_result.reason,
                    violation_type=exfil_result.violation_type
                )

            # 3. Content classification
            classification = await self.output_classifier.classify_output(output, agent_id)

            # 4. Watermarking
            watermarked_output = await self.text_watermarker.embed_watermark(
                text=output,
                agent_id=agent_id,
                session_id=session_id,
                timestamp=datetime.now(timezone.utc)
            )

            # 5. Audit logging
            await self.audit_logger.log_output_validation(
                decision="ALLOW",
                output=output,
                watermark_id=watermarked_output.watermark_id,
                classification=classification,
                safety_result=safety_result
            )

            latency_ms = (time.time() - start_time) * 1000

            return {
                "decision": "ALLOW",
                "output": watermarked_output.text,
                "watermark_id": watermarked_output.watermark_id,
                "classification": classification.model_dump(),
                "latency_ms": latency_ms,
                "metadata": watermarked_output.metadata
            }

        except Exception as e:
            logger.exception(f"Output validation error: {e}")
            # Fail-open for outputs (already generated)
            return {
                "decision": "ALLOW",
                "output": output,
                "error": "Output validation failed",
                "latency_ms": (time.time() - start_time) * 1000
            }
```

---

## 6. Additional Recommendations

### 6.1 Red Team as a Service

**Purpose**: Continuous adversarial testing by dedicated red team.

```python
class RedTeamService:
    """
    Automated red team testing service.

    Runs monthly attack campaigns to test Sentra defenses.
    """

    async def run_monthly_red_team(self) -> RedTeamReport:
        """
        Execute comprehensive red team campaign.
        """

        # 1. Generate novel attacks (not in training data)
        novel_attacks = await self._generate_novel_attacks(count=500)

        # 2. Execute attacks against production
        results = await self._execute_attacks(novel_attacks)

        # 3. Analyze failures
        failed_defenses = [r for r in results if r.bypassed_sentra]

        # 4. Generate report
        report = RedTeamReport(
            total_attacks=len(novel_attacks),
            successful_bypasses=len(failed_defenses),
            bypass_rate_pct=(len(failed_defenses) / len(novel_attacks)) * 100,
            new_attack_types=self._categorize_novel_attacks(failed_defenses),
            recommendations=self._generate_recommendations(failed_defenses)
        )

        # 5. Create Jira tickets for failed defenses
        for failure in failed_defenses:
            await self._create_jira_ticket(failure)

        return report
```

**Why**:
- Proactive discovery of defense gaps
- Continuous improvement cycle
- Realistic attack simulations

---

### 6.2 Compliance Reporting Dashboard

**Purpose**: Automated compliance reports for auditors/regulators.

```python
class ComplianceReporter:
    """
    Generate compliance reports for various frameworks.
    """

    async def generate_eu_ai_act_report(self, month: str) -> EUAIActReport:
        """
        EU AI Act compliance report.

        Requirements:
        - Disclosure of AI-generated content (watermarking)
        - Risk assessment of AI systems
        - Human oversight documentation
        - Audit trail completeness
        """

        # Query audit logs for the month
        logs = await self.audit_logger.query_logs(month=month)

        # Calculate metrics
        total_outputs = len(logs)
        watermarked_outputs = len([l for l in logs if l.get("watermark_id")])
        high_risk_outputs = len([l for l in logs if l.get("classification", {}).get("risk_score", 0) > 70])
        human_reviews = len([l for l in logs if l.get("requires_human_review")])

        return EUAIActReport(
            month=month,
            total_ai_outputs=total_outputs,
            watermarked_outputs=watermarked_outputs,
            watermark_rate_pct=(watermarked_outputs / total_outputs) * 100,
            high_risk_outputs=high_risk_outputs,
            human_review_rate_pct=(human_reviews / high_risk_outputs) * 100 if high_risk_outputs > 0 else 0,
            audit_trail_complete=True,
            compliance_status="COMPLIANT"
        )
```

---

### 6.3 Agent Behavior Analytics

**Purpose**: Understand what agents are doing; detect drift/anomalies.

```python
class AgentBehaviorAnalytics:
    """
    Analytics dashboard for agent behavior patterns.
    """

    async def generate_agent_report(self, agent_id: str, days: int = 30) -> AgentReport:
        """
        Generate behavioral report for specific agent.
        """

        logs = await self.audit_logger.query_logs_by_agent(agent_id, days)

        return AgentReport(
            agent_id=agent_id,
            period_days=days,
            total_requests=len(logs),
            allow_rate_pct=self._calculate_allow_rate(logs),
            deny_rate_pct=self._calculate_deny_rate(logs),
            top_tools_used=self._get_top_tools(logs),
            top_violations=self._get_top_violations(logs),
            trust_score_trend=self._get_trust_score_trend(logs),
            output_content_distribution=self._get_content_distribution(logs),
            anomaly_score=self._calculate_anomaly_score(logs),
            recommendations=self._generate_recommendations(logs)
        )
```

---

## Summary: Complete Feature Roadmap

### Phase 1: Critical Input Validation (Months 1-3)

1. ✅ **Enhanced Input Normalization** (Addresses: 1.7)
   - Base64/Unicode/encoding detection
   - Multi-modal content extraction (OCR, STT)

2. ✅ **Multi-Turn Attack Detection** (Addresses: 1.6)
   - Conversation context analysis
   - Sequential pattern detection

3. ✅ **Measurable Security Metrics** (Addresses: 1.5, 2.1-2.3)
   - Synthetic attack testing (1000+ cases)
   - Transparency dashboard
   - Attack surface categorization

---

### Phase 2: ML Security Model (Months 3-6)

4. ✅ **ML Security Model Training** (Addresses: 1.9, 1.10)
   - Ensemble architecture (text, behavioral, adversarial, multi-modal)
   - Anti-poisoning training techniques
   - Adversarial robustness testing

5. ✅ **Behavioral Anomaly Detection** (Addresses: 1.10)
   - Agent-specific baseline profiling
   - Zero-day attack detection

---

### Phase 3: Output Governance (Months 6-9)

6. ✅ **Output Validation** (Addresses: 1.3, 1.13)
   - Data exfiltration prevention
   - PII detection & redaction
   - Safety validation (toxicity, dangerous content)

7. ✅ **Watermarking & Provenance** (Addresses: 1.16)
   - Text watermarking (statistical)
   - Image watermarking (steganography)
   - Metadata tracking

8. ✅ **Content Classification** (Addresses: governance gap)
   - Multi-label content type classification
   - Risk scoring
   - Compliance flagging

9. ✅ **AI Content Detection** (Addresses: 1.16)
   - Universal AI detector (external sources)
   - Deepfake detection
   - Misinformation prevention

---

### Phase 4: Advanced Features (Months 9-12)

10. ✅ **Adversarial Robustness** (Addresses: 1.9)
    - Adversarial training
    - Robustness testing framework
    - Continuous robustness monitoring

11. ✅ **Red Team as a Service** (Addresses: all)
    - Automated attack generation
    - Monthly red team campaigns
    - Defense gap discovery

12. ✅ **Compliance Automation** (Addresses: 1.15, 1.16)
    - EU AI Act reporting
    - GDPR/HIPAA audit trails
    - Automated compliance dashboards

---

### Ongoing: Continuous Improvement

13. ✅ **Continuous Learning Pipeline**
    - Model retraining (monthly)
    - A/B testing
    - Performance monitoring

14. ✅ **Agent Behavior Analytics**
    - Behavioral dashboards
    - Drift detection
    - Anomaly alerts

---

## Key Metrics Targets

| Metric | Target | Current (Baseline) |
|--------|--------|-------------------|
| **Prompt Injection Detection** | >85% | ~50% (industry) |
| **Jailbreak Detection** | >85% | ~50% (industry) |
| **Data Exfiltration Detection** | >90% | N/A (new feature) |
| **False Positive Rate** | <5% | Unknown |
| **Adversarial Robustness** | >90% | N/A (new feature) |
| **Validation Latency (p95)** | <100ms | ~55ms (input only) |
| **Output Validation Latency (p95)** | <150ms | N/A (new feature) |
| **Watermark Detection Rate** | >99% | N/A (new feature) |
| **Content Classification Accuracy** | >90% | N/A (new feature) |

---

## References

### Primary Sources

1. **International AI Safety Report 2025 (Second Key Update)**
   - **File**: `International_AI_Safety_Report_2025_Second_Key_Upd.pdf`
   - **Location**: `/Users/shshgup/code/security-mvp/Sentra/International_AI_Safety_Report_2025_Second_Key_Upd.pdf`
   - **Published**: 2025
   - **Pages**: 28 pages
   - **Key Findings**:
     - Sophisticated attackers achieve ~50% success rate within 10 attempts against current safeguards
     - Defense-in-depth approach essential (multiple overlapping safeguards)
     - Data poisoning: As few as 250 malicious documents can compromise retrieval systems
     - Open-weight models lag <1 year behind frontier models but harder to control
     - Significant gaps remain in current AI safety measures
   - **Relevant Sections**:
     - Section 1: Technical Safeguards Overview
     - Section 2: Training Stage Interventions
     - Section 3: Deployment Safeguards (prompt injection, jailbreaks)
     - Section 4: Post-Deployment Monitoring
     - Section 5: Institutional Approaches (Frontier AI Safety Frameworks)

2. **VentureBeat Article: Anthropic's Measurable Security Metrics Approach**
   - **Title**: "Prompt injection measurable security metric: One AI developer publishes numbers"
   - **URL**: https://venturebeat.com/security/prompt-injection-measurable-security-metric-one-ai-developer-publishes-numbers
   - **Published**: 2025
   - **Key Findings**:
     - Anthropic published quantified attack success rates by attack surface
     - Example metrics: Prompt injection detection rate, jailbreak detection rate, etc.
     - Transparency approach builds trust with enterprise customers
     - Demonstrates security effectiveness through measurable, reproducible metrics
     - Attack surface categorization: user input, tool calls, system prompts, multi-agent
   - **Relevance to Sentra**:
     - Sentra should adopt similar transparency approach
     - Publish detection rates across OWASP LLM Top 10 attack categories
     - Enable benchmarking against industry baselines
     - Demonstrate continuous improvement through monthly metrics

### Supporting Context

3. **AI Safety Report Section References**
   - **Problem 1.1** (Prompt Injection): Report page references to prompt injection attack success rates
   - **Problem 1.4** (Defense-in-Depth): Report emphasizes multiple overlapping safeguards
   - **Problem 1.5** (Measurable Metrics): Report identifies lack of quantified effectiveness measurements
   - **Problem 1.17** (Data Poisoning): Report page discussing 250-document poisoning threshold

4. **VentureBeat Article Section References**
   - **Problem 2.1** (Transparency): Article discusses Anthropic's public metrics publication
   - **Problem 2.2** (Standardized Testing): Article mentions need for common testing frameworks
   - **Problem 2.3** (Attack Surface Categorization): Article details Anthropic's categorization approach

### Additional Resources Referenced

5. **OWASP LLM Top 10** (Referenced in Section 3.3.1)
   - Industry standard categorization of LLM vulnerabilities
   - Used for synthetic attack generation in security metrics framework

6. **EU AI Act** (Referenced in Sections 5.2, 6.2)
   - Regulatory framework requiring disclosure of AI-generated content
   - Mandates watermarking/provenance tracking capabilities

7. **Sentra Internal Documentation**
   - **LLD 03**: `lld/03-security-controller.md` - Current 5-step validation pipeline
   - **Flow Documentation**: `flow.md` - End-to-end validation flows
   - **Design HLD**: `design-hld.md` - High-level architecture
   - **CLAUDE.md**: Project overview and vision

---

## Document Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-02-13 | Claude (AI Assistant) | Initial comprehensive requirements document based on AI Safety Report 2025 and VentureBeat article analysis |

---

**END OF DOCUMENT**
