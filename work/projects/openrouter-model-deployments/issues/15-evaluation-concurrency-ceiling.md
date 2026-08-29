# 15 — Keep evaluation concurrency as the OpenRouter ceiling

**What to build:** The Evaluation Run's explicit case-concurrency setting also
sets the highest OpenRouter request-admission limit for that run. Reactive flow
control may lower the working limit, but no model request can raise it above the
operator's ceiling.

**Blocked by:** 13 — Adapt OpenRouter request admission after probes; 14 —
Select and record an Evaluation Run Model Deployment.

Labels: completed

- [x] The Evaluation Run passes its positive concurrency setting to OpenRouter request admission.
- [x] The same setting continues to bound concurrent Evaluation Cases in `pydantic-evals`.
- [x] Reactive restoration never admits more OpenRouter requests than the operator selected.
- [x] Local Evaluation Runs preserve their current case-concurrency behavior without entering OpenRouter flow control.
- [x] Command and concurrent Agent tests demonstrate the ceiling without live inference.
