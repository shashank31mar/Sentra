# Outreach — Ed Sim, boldstart ventures

**Channel:** LinkedIn InMail (no public pitch email; boldstart.vc/contact-us is a bare form). Direct: linkedin.com/in/edsim · x.com/edsim
**Target:** Ed Sim (Founder/GP — owns cyber + AI-infra; led Protect AI, Keycard, Snyk, BigID).
**Conflict status:** CLEAN of a direct competitor. Holds **Keycard** (agent identity/access — *complementary*, the hook). Confirm partner-level info-wall before sharing sensitive architecture.
**Fit note:** body ≈1,890 chars — under LinkedIn InMail's ~1,900 cap.

---

**Subject:** The guardrail for what agents *do* — pairs with Keycard

**Body:**

Ed — your Keycard thesis pulled me in: agents in "god mode" with real credentials and no guardrails. Keycard fixes *who the agent is*. I'm building the layer next to it — *what the action is allowed to do*.

AegionAI is a neutral control plane that stops harmful AI-agent actions inline, across AWS, Azure, GCP, and on-prem. Most tools are a single probabilistic step — an ML classifier guessing if a prompt *looks* malicious. We lead with a deterministic floor and layer the model depth on top.

Before an action executes it passes an ordered stack — cheap deterministic checks first, models only for what survives. Each layer can block, and every block names the layer that decided it:

• Identity & authorization — is this agent allowed to take this action at all?
• Policy & parameters — amount, recipient, limits — real policy (Cedar), not an allow-list
• Sequence integrity, single- and cross-cloud — did the required prior steps run, in order?
• Trust & containment — accumulated trust; quarantine an agent that misbehaves
• Cross-agent — block privilege escalation across a multi-agent chain

That floor blocks live today. On top: injection signatures (live), a small classifier we distilled from our own frontier-model verdicts to short-circuit in <100ms, and injection/memory detectors rolling out. Any layer that errors fails secure.

Second differentiator: in-VPC and air-gapped editions — regulated buyers keep payloads inside their boundary, the axis a SaaS-only competitor can't follow. Beachhead is agents that move money, where a wrong action is instant loss.

Pre-revenue, but the core is built and running live across two clouds. Provisional patent filed. Raising a $5M seed.

I'd love 30 min to walk you through the live system and get your read on where it fits the Autonomous Enterprise thesis — or I can send a two-pager if that's easier to start.

— Shashank · aegionai.ai · shashank31mar@gmail.com
