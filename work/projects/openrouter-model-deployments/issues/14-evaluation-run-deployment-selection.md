# 14 — Select and record an Evaluation Run Model Deployment

**What to build:** An Evaluation Run defaults to OpenRouter, may select local or
OpenRouter explicitly, and binds its existing model override to that selected
deployment. Command assembly passes the Model Deployment into the Evaluation
Task and records the same value in the report and filename. Selecting an
incomplete OpenRouter deployment fails before Gold Set execution begins.

**Blocked by:** 03 — Pass a Model Deployment through Coreference Resolution;
05 — Pass a Model Deployment through the Relevance Filter; 08 — Constrain every
OpenRouter route.

Labels: completed

- [x] The Evaluation Run command accepts local and OpenRouter deployment selections and defaults to OpenRouter.
- [x] The existing model override replaces the configured model for the selected deployment verbatim.
- [x] The deployment passed to the Evaluation Task is the deployment serialized in the report.
- [x] Local and OpenRouter reports for the same upstream release have distinct structured deployment values and filenames.
- [x] Missing OpenRouter API key, requested model, or provider list fails before any Evaluation Case executes.
- [x] Gold Set loading, Evaluation Split selection, task construction, evaluators, and local `pydantic-evals` execution remain the existing system.
