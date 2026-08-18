# Payment Core Agent Instructions

## Purpose

This repository is the provider-neutral payment foundation for Frappe and ERPNext. Use these
instructions for either of these tasks:

1. Maintain shared behavior in `payment_core`.
2. Research, design, scaffold, implement, and verify a separate payment-provider app using the
   collision-safe `<app_name>` selected by this workflow.

Provider-specific credentials, SDK clients, checkout pages, webhooks, reconciliation, and branding
belong in a separate provider app. Do not add them to `payment_core` unless they are genuinely
provider-neutral contracts or utilities used by more than one provider.

Codex and Cursor discover `AGENTS.md`. Claude Code does not automatically load this filename; when
using Claude Code, explicitly tell it to read and follow `AGENTS.md` before starting.

## Supported Platforms

- Target Frappe and ERPNext from `version-16` through `develop`.
- `payment_core` is required by every provider app; ERPNext is required transitively by
  `payment_core`.
- Do not copy the current repository's Python, Node, MariaDB, or package versions blindly. Before
  scaffolding, inspect the supported versions on both Frappe/ERPNext `version-16` and `develop`, then
  choose the compatible intersection and test both targets.
- Frappe apps always contain a Python package. A provider need not have an official Python SDK; use
  `frappe.integrations.utils` or a narrowly scoped HTTP client when an SDK is unavailable, stale, or
  unsuitable.

## Default Provider Identity

Unless the user overrides a value:

- Provider display name: `<Provider>`
- Provider slug: lowercase snake_case `<provider>`
- Frappe app/Python package (`<app_name>`):
  - Use `<provider>` when no official Python SDK distribution or import package uses that name.
  - Use `<provider>_payment` when an official Python SDK distribution or import package uses
    `<provider>`, avoiding a package/import collision.
- App title: `<Provider> Payment`
- Publisher: `Aerele`
- Publisher email: `hello@aerele.in`
- License: `MIT`
- Dependency hook: `required_apps = ["payment_core"]`

Research the official Python SDK and its distribution/import names before fixing `<app_name>`.
Record the result even when no SDK exists. Non-Python browser/mobile SDKs do not create a Python
package collision, but still belong in the architecture and dependency review.

Create and verify the app locally, then hand it off to the developer. This workflow must not create
or configure a hosted repository or remote, stage files, commit, push, publish a package, or deploy.
Repository organization, visibility, history, release, and deployment remain the developer's
responsibility.

## Authoritative References

Use this precedence when references disagree:

1. Current `payment_core` source, hooks, schemas, and tests in this repository.
2. Current standalone provider apps:
   - `https://github.com/aerele/stripe-payment`
   - `https://github.com/aerele/razorpay-payment`
   - Prefer sibling checkouts under the same Bench when available.
3. Current official documentation and API/OpenAPI specifications from the payment provider.
4. Current Frappe and ERPNext source for both `version-16` and `develop`.
5. Payment Core documentation beginning at
   `https://integrations.frappe.cloud/integrations/payment-integration/payment-core/payment-overview`.
6. `https://github.com/frappe/payments` only as a legacy behavior and migration reference.

The Payment Core wiki contains useful concepts but some examples still use `payments.utils`, old
hooks, and outdated platform requirements. Translate those examples to the current split-app
architecture. Never reproduce a legacy flow without checking it against current provider security
guidance and the current standalone apps.

## Working Rules

- Inspect the repository, git status, relevant sibling apps, and existing tests before proposing
  changes. Preserve unrelated user changes.
- Use existing Frappe patterns and structured APIs. Keep shared logic in `payment_core` and
  provider behavior in the provider app.
- Use tabs in Python, double quotes, and the Ruff settings from `pyproject.toml`.
- Use translatable user-facing messages with `frappe._`/`_`.
- Never edit generated or framework-owned ERPNext/Frappe source to make a provider work. Use hooks,
  custom fields, overrides, patches, and provider-owned doctypes.
- Do not invent provider API behavior. Record the official source and access date for material API,
  webhook, currency, idempotency, or status decisions in the research report and provider README.
- Do not expose or request real secrets in chat, fixtures, source, logs, screenshots, or commits.
  Use placeholders and site configuration for local test credentials.

## Developer Approval Boundaries

This file is a reusable engineering baseline, not standing approval for every provider, capability,
accounting model, environment, or external action. After the developer replies `build`, the agent may
edit the new provider app and run local, mocked checks autonomously within the approved architecture.

Before any action below, present the exact target, action, purpose, side effects, and rollback or
cleanup requirement in one concise approval question, then stop and wait:

- Install, migrate, reinstall, or uninstall the app on a Frappe site. Site selection and approval are
  handled by the dedicated installation gate below.
- Install, start, configure, expose, or publish a tunnel such as ngrok or cloudflared; change DNS,
  hosts-file, reverse-proxy, TLS, firewall, or externally reachable callback configuration.
- Create, update, rotate, revoke, or delete provider-dashboard applications, credentials, webhook
  registrations, callback URLs, event subscriptions, or account settings.
- Execute a bounded provider sandbox acceptance flow that creates remote orders, payments, refunds,
  captures, mandates, subscriptions, payouts, or other provider objects. One approval may cover a
  clearly enumerated sandbox test sequence; additional external actions require new approval.
- Use live credentials or perform any live payment, authorization, capture, refund, void, payout,
  mandate, subscription, dispute action, or other action involving real accounts or funds.
- Install system-level packages or services, restart shared services, change Bench-wide
  configuration, modify another app, or alter `payment_core`, Frappe, or ERPNext source.
- Delete or rewrite site data, uninstall an app, remove provider objects, or perform another
  destructive or difficult-to-reverse operation.

Approval for one boundary does not imply approval for another. In particular, approval to create a
tunnel does not authorize provider-dashboard webhook registration, and approval for sandbox testing
does not authorize a live transaction. These boundaries apply whether an action is performed through
a CLI, API, browser, SDK, automation, or dashboard. Never request secrets in the approval question.

## New Provider Workflow

### Phase 1: Start With the Provider Name

The first user input may contain only the payment provider name. Do not demand a completed technical
questionnaire before beginning. If the name could refer to multiple companies, products, regions, or
APIs, ask one short disambiguation question containing only the likely names. Do not include research
details or links unless the developer asks for them.

After identifying the provider, research its current official documentation before proposing scope.
Inspect, as applicable:

- Product catalog and regional availability.
- Supported currencies, payment methods, settlement markets, and merchant eligibility.
- One-off payments, authorization/capture, partial capture, voids, partial/full refunds, saved payment
  methods, customers, subscriptions, recurring payments, mandates, disputes, chargebacks, payouts,
  reconciliation, and any provider-specific capabilities.
- Marketplace/platform capabilities: connected or sub-merchant accounts, hosted onboarding, KYC/KYB,
  OAuth or account linking, split payments, application/platform fees, transfers, payouts, reserves,
  negative-balance liability, refunds across split funds, and dispute ownership.
- Card, wallet, pay-later, mobile-money, QR, real-time bank rail, bank redirect, direct debit, virtual
  account, bank transfer, cash/voucher, and in-person/terminal methods when relevant to the provider.
- Regulatory and data-scope requirements such as PCI responsibility, SCA/3DS, tokenization,
  consent/mandate evidence, data residency, and merchant-of-record versus platform liability.
- Hosted, embedded, direct API, QR, bank redirect, mobile push, and other checkout models.
- Authentication, credential types, OAuth scopes, certificates, webhook signing, idempotency, rate
  limits, API versions, SDKs, changelogs, deprecations, sandbox facilities, and test data.
- The complete administrator and payer sandbox journey: developer-dashboard identity, merchant/API
  account, buyer/test account, funding instruments, balances, phone/OTP behavior, regional
  eligibility, and the difference between wallet login, guest payment, and account creation.
- Local and deployed infrastructure prerequisites: canonical site origin and port, HTTPS callback
  requirements, browser security requirements, workers/scheduler, PDF rendering, email, and public
  webhook reachability.
- Exact browser SDK runtime contracts for the selected release, including initialization credential
  type, response envelopes, argument types, Promise inputs and resolution values, callback payloads,
  component configuration, browser-switch behavior, and asset delivery.
- Official SDK distribution/import names, maintained release lines, latest stable release, release
  dates, support/deprecation status, Python compatibility, API-version compatibility, and migration
  guidance between versions.
- Provider onboarding, account approval, feature activation, commercial, and compliance constraints.

Classify the integration into one or more provider models before presenting scope: merchant checkout,
marketplace/platform, recurring billing, mandate/direct debit, asynchronous bank or mobile payment,
virtual account/bank transfer, payout/disbursement, reconciliation-only, or in-person/terminal. Apply
only the contracts, UI, accounting, tests, and acceptance gates relevant to the selected models. Do
not force a Payment Request, browser SDK, webhook, Payment Entry, or immediate-capture design onto a
provider flow that does not use it.

Use primary sources: official API references, product documentation, SDK repositories, changelogs,
and status/version notices. Do not infer API support from marketing pages alone. Record the source
URL and access date for material findings. If official documentation is unavailable, requires
merchant access, or cannot be reached by the current agent, stop and ask the developer for official
links or exported documentation. Do not proceed from memory or unsupported assumptions.

Cross-check each capability against Payment Core, the existing Stripe and Razorpay apps, and the
supported Frappe/ERPNext branches. Distinguish technical API support from merchant or regional
availability. Label restrictions such as account approval, country, currency, payment-method,
commercial-plan, or API-version requirements.

Build and retain a detailed capability matrix in the research ledger. It must contain support status,
conditions, Payment Core fit, implementation implications, administrator prerequisites, sandbox
test identities/data, acceptance evidence required, and official sources, but do not print that
matrix in the normal developer conversation.

The first scope response must use the following structure as the entire response. Do not add a
preamble, research-completion notice, explanation, or closing paragraph:

```text
Provider: <Provider>
App/package: <app_name>
Title: <Provider> Payment
Publisher: Aerele
License: MIT
Dependency: required_apps = ["payment_core"]

Select the scopes to include:
- One-off immediate payment
- <other researched supported or conditionally supported scope>
- <other researched supported or conditionally supported scope>

Reply with the scope names, or `recommended`.
```

List each selectable scope on one line. Add `(Recommended)` to the smallest secure, useful MVP
scopes and `(Conditional)` where availability depends on provider approval, account type, or region.
Do not list unsupported or deprecated capabilities as selectable scopes.

Do not include source links, citations, API explanations, SDK versions, framework versions, currency
lists, regional policy summaries, implementation reasoning, or the full capability matrix in this
first response. Retain those details in the ledger and provide them only when requested or when a
short warning is required to prevent an invalid or unsafe selection.

Stop after the scope question. Do not ask any other question, scaffold, or edit the provider app
until the developer confirms the scope.

### Phase 2: Resolve Decisions Interactively

After feature scope is approved, resolve consequential choices one gate at a time. Research each gate
fully before asking, but keep that research in the decision ledger. Never ask the developer to supply
facts available in official documentation.

For each response:

- Ask exactly one decision.
- Use a short heading, one-sentence question, and a plain list of selectable options.
- Mark the preferred option with `(Recommended)`; do not add a paragraph explaining it.
- Include at most one short warning when an option is conditional, unsupported, incompatible, or
  unsafe. Explain details only if the developer selects that option or asks for them.
- Do not include source links, citations, research narration, repeated identity details, already
  confirmed decisions, or broad architecture summaries.
- End with the exact reply format, such as `Reply with 1, 2, or recommended.`
- Stop and wait. Do not combine the next decision into the same response.

The scope-selection response may be longer only because it must list every selectable capability.
The developer may reply `recommended` or `use the recommendation`. Maintain the full decision
ledger with entries marked `confirmed`, `researched`, `inferred`, `not applicable`, or
`unknown`. Preserve official source URLs and impacts in that ledger even though they are omitted
from normal chat.

Resolve at least these gates when applicable:

1. Identity and app naming: determine the official Python SDK distribution/import names and propose
   `<provider>` or `<provider>_payment` using the collision rule above. Treat the displayed
   identity as confirmed when the developer approves a scope unless they explicitly change it; do
   not ask a separate identity question.
2. Feature scope: one-off payments, authorization/capture, refunds, recurring or mandate flows,
   saved methods, disputes, reconciliation, and explicitly deferred features.
3. Market scope: merchant countries, customer countries, currencies, payment methods, settlement
   currencies, and conditional availability.
4. Account/configuration model: single or multiple merchant accounts, environment switching,
   credentials, OAuth/certificate lifecycle, and webhook endpoint ownership.
5. SDK and API version: when an official maintained SDK exists, list the supported release lines,
   latest stable version, lifecycle status, Python/Frappe compatibility, matching provider API
   versions, breaking changes, and official documentation for each viable choice. Recommend the
   latest stable version compatible with every supported target, but wait for the developer to
   choose a version/range or explicitly approve the recommendation. Resolve `latest` to a concrete
   version or compatible range and record the research date. If no suitable SDK exists, mark this
   gate `not applicable` and approve a narrowly scoped HTTP client instead.
6. Checkout and API architecture: viable products, hosted versus embedded/direct flow,
   client/server responsibilities, and webhook authority. Use only APIs, payloads, webhook schemas,
   examples, and documentation that match the approved SDK/API version.
7. ERPNext behavior: Payment Gateway and Payment Gateway Account setup, Integration Request
   lifecycle, status mapping, identifiers, refunds, settlement/reconciliation, fees, and retries.
8. Verification: Bench/site availability, the exact site origin and port, canonical `host_name`,
   worker/scheduler/PDF/email prerequisites, public HTTPS callback strategy, sandbox merchant and
   buyer account availability, compatible account countries/currencies, test funding instruments,
   browser scenarios, webhook delivery, and where the developer will configure credentials. Ask
   only for consequential choices or whether required accounts are available; never ask for secret
   values in chat or source. Creating a tunnel or exposing a local site requires explicit approval.

The detailed intake below is an accumulating research and decision ledger, not an upfront
questionnaire:

- Identity: provider name, app slug, title, publisher, email, license, target directory.
- Official sources: API reference, authentication, checkout, webhooks, errors, idempotency,
  currencies, refunds, subscriptions/mandates, SDK repository, changelog, and versioning policy.
- Environments: sandbox/live endpoints, credential pairs, test accounts, and environment switching.
- Account model: one settings record or multiple merchant/account settings records.
- Credentials: public values, secrets, webhook secrets, certificates, OAuth tokens, expiry/refresh,
  scopes, and credential test endpoint.
- Checkout: hosted redirect, embedded SDK, custom Frappe page, direct API, QR, mandate, or mobile push.
- Features: one-off payment, authorization/capture, partial payment, refund, saved method, customer,
  subscription, mandate, dispute, chargeback, reconciliation, connected accounts, onboarding, split
  payments, platform fees, transfers, payouts, and provider-specific payment methods.
- Money: supported currencies, zero/three-decimal rules, minimum/maximum amount, rounding, fees, and
  settlement currency.
- Events: browser return, server callback, webhook URL, event names, ordering, retries, timeout,
  signature algorithm/header, raw-body requirement, timestamp tolerance, and replay behavior.
- Statuses: provider states mapped to `Queued`, `Authorized`, `Completed`, `Failed`, and `Cancelled`.
- References: provider object IDs and ERPNext doctypes/fields needed for durable reconciliation.
- Operations: retry strategy, polling/scheduler needs, rate limits, timeout policy, and observability.
- Acceptance: sandbox scenarios, optional live smoke test, supported ERPNext flows, and exclusions.

### Phase 2 Completion: Research and Architecture Report

Once the decision ledger is approved, prepare a detailed internal architecture report before writing
provider code. It must cover:

- Normalized intake with unknowns and assumptions.
- Selected architecture and why it fits: hosted redirect, embedded/custom checkout, asynchronous
  push, direct debit/mandate, or webhook-first recurring flow.
- Single-account versus multi-account settings decision.
- API/SDK choice, pinned version strategy, and compatibility with both supported Frappe branches.
- End-to-end payment sequence, authoritative server data, Integration Request lifecycle, return flow,
  webhook flow, settlement, and retries.
- For marketplace/platform scope, actor and funds-flow ownership across platform, sub-merchant,
  customer, provider balance, fees, transfers, payouts, refunds, disputes, reserves, and liability.
- Provider-to-ERPNext status and identifier mapping.
- Required doctypes, custom fields, hooks, jobs, pages, JavaScript, dependencies, and migrations.
- Security threat review: amount tampering, reference substitution, callback forgery, replay,
  duplicate settlement, cross-account credential leakage, secret exposure, and unsafe redirects.
- Test matrix and any features explicitly deferred.
- Documentation or API conflicts discovered.

Use Stripe as a reference for hosted checkout, multiple accounts, verified webhooks, subscriptions,
deduplication, and reconciliation. Use Razorpay as a reference for custom checkout, server-created
orders, signed browser callbacks, capture jobs, and partial settlement. Select pieces by capability;
never copy an entire app and rename it.

Do not paste the detailed report into the normal conversation. Present only this compact approval
summary, omitting links and reasoning:

```text
Ready to build:
- App: <app_name>
- Scope: <confirmed scopes>
- Market: <confirmed market>
- Accounts: <confirmed account model>
- SDK/API: <confirmed version or direct HTTP>
- Checkout: <confirmed flow>
- ERPNext: <confirmed settlement behavior>
- Tests: unit/integration and sandbox plan

Reply `build` to scaffold and implement, or name the item to change.
```

Stop for final confirmation before scaffolding. During implementation, continue autonomously for
choices already covered by the ledger. If new evidence creates a consequential decision about money
movement, ledger behavior, public endpoints, authentication, stored customer/payment data,
dependencies, compatibility, or scope, ask one concise decision using the same interaction rules.
Ordinary naming and file placement may use the documented defaults.

### Pre-Build Environment and Acceptance Gate

Before scaffolding, create an internal environment and acceptance matrix derived from the selected
capabilities. Mark each row `required`, `not applicable`, `available`, or `blocked`. Evaluate at
least:

- Actual local site origin, including scheme, hostname, and non-default port.
- Canonical Frappe `host_name` and whether server-side PDF and asset requests can resolve it.
- Bench processes, workers, scheduler, Redis, database, asset build, PDF renderer, and email path.
- Public HTTPS requirements for webhooks, redirects, hosted checkout, embedded SDKs, and mobile
  callbacks.
- Sandbox/live merchant accounts, separate buyer/test identities when applicable, credentials,
  funding instruments, balances, account countries, supported currencies, and payment methods.
- ERPNext Company, Payment Gateway Account, payment account, account currency, and reference-document
  prerequisites.
- Provider-dashboard feature activation, account approval, KYC, commercial plan, and regional
  restrictions.
- The automated, browser, sandbox, webhook, and ERPNext evidence required for each selected scope.

Do not treat API connectivity or mocked tests as proof that browser checkout, provider-dashboard
configuration, webhook delivery, ERPNext accounting, or a regional payer flow works.

When external HTTPS is required, resolve one consequential decision covering an existing public
domain, an approved temporary tunnel such as ngrok/cloudflared, or deferred webhook acceptance.
Do not install, start, configure, expose, or publish a tunnel without approval. After approval,
configure and verify the public endpoint before proposing provider webhook registration; do not wait
for webhook failure to reveal that the site is unreachable. Registering or changing the endpoint or
event list in a provider dashboard is a separate external action and requires separate approval.

### Phase 3: Scaffold the Separate App

- Work from a Frappe Bench containing `frappe`, `erpnext`, and `payment_core`. If the repository is
  not inside a Bench, explain the prerequisite instead of fabricating Bench state.
- Create the provider as a sibling under `<bench>/apps/<app_name>`, normally with
  `bench new-app <app_name>`. Answer scaffold prompts with the approved identity.
- Do not nest the provider app inside this repository.
- Add the approved provider SDK distribution to `pyproject.toml` only when justified. Pin the
  approved compatible version/range and configure a matching provider API version in code when
  supported. Do not silently upgrade to another SDK major or use examples from a different version.
- Declare `required_apps = ["payment_core"]` in `hooks.py`.
- Keep `frappe`/`erpnext` dependencies Bench-managed unless the repository's established packaging
  approach changes.
- Create the automated unit-test suite with the app, including network mocks and fixtures/builders
  needed to test provider behavior without live calls.
- Add a provider-repository `.pre-commit-config.yaml` consistent with the maintained Payment Core,
  Stripe, and Razorpay repositories; adapt hooks only when the generated app's languages require it.
- After the developer selects and authorizes a site through the gate below, install the app only on
  that site and run the local-site preflight before provider-dashboard configuration or payment-flow
  testing.

Expected baseline structure (adapt it to capabilities):

```text
<app_name>/
  pyproject.toml
  README.md
  .pre-commit-config.yaml
  <app_name>/
    hooks.py
    modules.txt
    install.py                 # only when custom fields/setup are needed
    gateway/
      client.py                # isolated auth/client and timeouts
      constants.py             # API version, URLs, currency rules
      references.py            # metadata/reference binding
      checkout.py              # initiation/return flow when applicable
      webhooks.py              # verification, dedupe, dispatch
      reconciliation.py        # event-to-ERPNext effects when applicable
      subscriptions.py         # only when supported
      settlement.py            # only for provider-specific settlement
    <provider>/doctype/<provider>_settings/
      <provider>_settings.json
      <provider>_settings.py
      <provider>_settings.js   # only for useful Desk actions
    templates/pages/           # only for provider-owned checkout pages
    public/                    # provider SDK integration and logo
    tests/
      __init__.py
      test_client.py           # auth, requests, errors, retries, and version behavior
      test_checkout.py         # initiation/return flow when applicable
      test_webhooks.py         # signatures, dedupe, ordering, and replay
      test_settlement.py       # status/accounting/idempotency behavior when applicable
```

### Site Selection and Installation Gate

When the provider app is ready for its first site-backed validation:

1. Discover the sites available in the current Bench using read-only inspection. For each candidate,
   report whether `frappe`, `erpnext`, `payment_core`, and `<app_name>` are installed.
2. Do not infer a target from the current directory, default site, `currentsite.txt`, the only
   available site, or a site used for another provider.
3. Ask exactly one concise question:

```text
Select the site on which to install and test <app_name>:
- <site-1> (local/development, if known)
- <site-2> (shared/production, if known)
- Skip installation

Reply with the exact site name or `skip`.
```

4. Treat selection of a local/development site as approval to run the app installation and required
   migration on that site only. If the selected site appears shared, staging, production, or contains
   live data, explain the impact and obtain a second explicit confirmation before changing it.
5. Verify the selected site exists and has compatible Frappe, ERPNext, and Payment Core versions.
   If the app is absent, run `bench --site <confirmed_site> install-app <app_name>`; otherwise do not
   reinstall it. Run the required migration and app-specific asset/cache steps, then report results.
6. Never install or migrate the provider on another site without a new site-selection approval.
   Selection does not authorize changing `host_name`, DNS, email, workers, credentials, tunnels,
   provider dashboards, or executing a sandbox/live payment.
7. If no suitable site exists, stop and give the prerequisite for the developer to create or provide
   one. Do not create a new site unless the developer separately requests and approves it.

### Local Site Preflight

Run this preflight immediately after installing the provider on a local site and before configuring
remote dashboards or testing Payment Request:

1. Inspect installed apps and exact Frappe/ERPNext branches; run migrations before diagnosing UI or
   schema behavior.
2. Determine the origin actually used by the browser, including its port. Do not assume port 80 or
   443 from the hostname alone.
3. Inspect the site's `host_name`. If it is missing or wrong, set it to the complete canonical
   origin, clear cache, and verify generated absolute URLs. A site served at
   `http://example.test:8000` must not be configured as `http://example.test`.
4. Verify the canonical URL from both the browser and the server process. Confirm DNS/hosts mapping,
   listening port, assets, and provider-owned pages.
5. Build provider assets, clear relevant caches, and confirm the served asset contains the current
   implementation rather than relying on the source file alone.
6. Render a representative ERPNext PDF through the same print path used by Payment Request. Resolve
   `wkhtmltopdf`, hostname, port, asset, or network errors before payment testing.
7. Verify email configuration or deliberately use the supported muted-email path during acceptance;
   do not let email/PDF failure masquerade as a provider failure.
8. Verify workers and scheduler when capture, polling, retries, reconciliation, or webhooks use them.
9. When callbacks are required, verify the approved HTTPS endpoint from outside the local network
   before entering it in the provider dashboard.

Local HTTP is not, by itself, the cause of an OAuth/API credential `401`. Diagnose credential,
environment, account, and endpoint failures independently from HTTPS callback reachability.

### Administrator UX Requirements

Design provider settings and operational DocTypes for administrators, not only for schema
correctness:

- Group fields into labelled sections and balanced desktop columns with Section Break and Column
  Break fields where this improves readability. Keep logically related values together; do not
  split fields solely to equalize counts.
- Show environment and enabled/disabled state prominently. Separate public identifiers, encrypted
  credentials, merchant identity, webhook configuration, and operational state.
- Add concise descriptions identifying where each value comes from in the provider dashboard and
  whether it differs between sandbox and live.
- Make generated endpoint URLs read-only and copyable. Never require administrators to construct a
  webhook URL by hand when the app can generate it safely.
- Use dependency/mandatory rules so fields appear only for applicable features and environments.
- Provide permission-checked actions such as Test Credentials where useful, with actionable errors
  that distinguish invalid credentials, wrong environment, missing activation, permission, network,
  and provider availability failures.
- Visually inspect the migrated forms on every supported Frappe branch, including narrow and normal
  desktop widths. Schema tests do not prove a usable layout.
- Keep secret fields masked and ensure Desk calls, exceptions, and browser payloads cannot echo them.

### Phase 4: Implement the Core Contract

- The settings controller must inherit `GatewayControllerMixin` before `Document` and implement:
  - `get_payment_url(**kwargs)`
  - `validate_transaction_currency(currency)`
- Implement `create_request(data)` only when the selected flow needs a callback/controller request.
- Register settings through `payment_core.utils.create_payment_gateway()` on the appropriate
  lifecycle event and call `call_hook_method("payment_gateway_enabled", gateway=...)`.
- For one settings record, use the plain gateway name and no dynamic controller. For multiple
  accounts, create a stable unique gateway name and pass both settings DocType and controller name.
- Register provider services with `payment_gateway_module = {"<Provider>": "<module.path>"}` when
  provider service lookup is needed.
- Register subscription creation with `gateway_subscription_handler` only when implemented.
- Use `payment_core.api.controllers.get_gateway_controller_name()` instead of duplicating controller
  resolution.
- Use `payment_core.utils.guard_payment_reference()`, `get_reference_amount()`,
  `authorize_reference()`, `success_redirect()`, and `settle_payment_request()` where their behavior
  matches the provider. Extend provider-side only for a documented difference such as partial
  settlement.
- Log remote operations with Frappe's `Integration Request`. Persist enough immutable server-side
  context to bind callbacks to the original reference, amount, currency, account, and provider ID.
- Use hooks only when needed: `doc_events`, `scheduler_events`, install/uninstall/migrate handlers,
  and custom-field setup must be capability-driven and idempotent.

## Browser SDK Contract Verification

When checkout uses a provider browser SDK, treat it as a separately versioned dependency even when
it is loaded directly from the provider:

- Record the exact SDK product, version or release channel, URL, access date, and matching official
  documentation. If the URL is unpinned, record the runtime version used for acceptance and retain a
  contract smoke test that detects breaking changes.
- Determine whether initialization requires a public client ID, client token, access token, JWT,
  session token, or another artifact. Names that sound similar are not interchangeable. Generate
  short-lived browser artifacts server-side with the exact documented endpoint/grant and never
  expose merchant secrets.
- Verify every client/server boundary, including Frappe's `message` response envelope, JSON error
  envelope, CSRF behavior, data attributes, and type conversion.
- Verify argument types, Promise requirements, Promise resolution shapes, order/session identifier
  types, callback payloads, component/button types, eligibility methods, cancellation, popup or
  browser-switch behavior, and error callbacks against the selected SDK release.
- If official prose, examples, TypeScript declarations, and observed runtime behavior disagree,
  inspect the exact loaded release, record the discrepancy, implement the runtime-safe contract, and
  add a regression test. Do not alternate between guessed shapes until the browser accepts one.
- Add JavaScript tests with a mocked SDK for initialization, create-order, approval, capture,
  cancellation, error, and every contract-sensitive return shape. Python controller tests do not
  cover these contracts.
- Test the built checkout through a real HTTP browser session. Confirm that guest/authenticated
  cookies, valid CSRF tokens where required, server-created identifiers, caught Promise failures,
  user-facing errors, and redirects all work from the served asset.
- After changes, rebuild assets, clear caches, hard-refresh or use a fresh browser context, and
  verify the served asset rather than assuming the browser received the source edit.

For Promise-based order/session APIs, explicitly test both the container and resolved value types.
For example, a requirement for `Promise<{ orderId: string }>` is not satisfied by a string, a
`Promise<string>`, or `{ id: string }` even though each contains the same identifier.

## ERPNext Compatibility and Accounting Preflight

Exercise the provider through actual ERPNext forms and lifecycle methods on every supported branch,
not only provider controllers:

1. Create, save, and test the provider Settings record.
2. Create and inspect the Payment Gateway and Payment Gateway Account.
3. Select the gateway on an ERPNext Payment Request linked to a real payable reference.
4. Submit through the actual email/print path and open the generated payment URL.
5. Complete the provider flow and inspect Integration Request, Payment Entry, reference outstanding
   amount, currency, company, and accounting dimensions.

Document and validate Payment Gateway Account prerequisites. For an inward payment, the payment
account is normally a Company-owned Asset account with an appropriate Bank or Cash account type; its
account currency and multi-currency configuration must support the transaction. Test the combined
reference currency, gateway-account currency, company currency, party-account currency, and payment
account rather than validating each field in isolation.

Check for legacy ERPNext guards, imports, links, and messages that still require the `payments` app.
If the actual flow emits a legacy "payments app is not installed" failure:

1. Identify the exact framework source, branch behavior, and primary exception.
2. Separate stale or secondary `_server_messages` from the traceback that failed the request.
3. Do not edit framework-owned ERPNext/Frappe files or modify `payment_core` merely to suppress it.
4. Propose a provider-owned compatibility hook/override only when it is narrow, safe, tested on all
   supported branches, and approved.
5. Otherwise document the upstream incompatibility and dependency as a blocker; never hide an
   unrelated PDF, email, permission, or accounting failure behind the legacy message.

## Non-Negotiable Payment Security

- Never trust client-supplied amount, currency, ERPNext reference, merchant account, order ID,
  subscription ID, or payment status. Resolve and bind authoritative values server-side.
- Validate reference existence and permissions before initiating payment. Reject cancelled,
  expired, already-paid, or otherwise non-payable references.
- Create provider orders/sessions server-side. Store their IDs in the Integration Request; callbacks
  must compare against those stored IDs, not accept replacements from the browser.
- Verify browser callback and webhook authenticity before settlement or any privileged database
  write. Use the exact raw request bytes when the provider signs the raw body.
- Fail closed when a signing secret/header is absent. Use the official SDK verifier or a correct
  implementation with constant-time comparison. Enforce timestamp tolerance/replay protection when
  supported.
- A guest endpoint needs an explicit authentication story: provider signature, opaque Integration
  Request token, server-side provider lookup, or a documented combination. `allow_guest=True` alone
  is never authorization.
- Elevate to Administrator only after authenticity and reference checks, scope elevation to the
  smallest settlement block, and restore the original user in `finally`.
- Use encrypted Password fields and Frappe password APIs. Do not put secrets in Data fields, module
  globals, query strings, logs, Integration Request payloads, fixtures, or browser JavaScript.
- Isolate credentials per settings record and per request. Do not mutate provider SDK global API
  keys; concurrent requests for different merchant accounts must not cross credentials.
- Set explicit network timeouts. Classify retryable errors and respect provider rate limits.
- Use stable idempotency keys for provider create/capture/refund calls when available. Never use
  timestamps/random values for a retry of the same logical operation.
- Deduplicate webhooks with a provider event ID enforced by a database uniqueness constraint where
  possible. A redirect and webhook may race; settlement must have an atomic first-writer claim or an
  equivalent lock and remain idempotent.
- Do not call `frappe.db.commit()` in request/webhook handlers. Use the request transaction,
  savepoints for isolated event work, and let failed webhook processing return a retryable HTTP code.
- Do not store or process raw card/bank credentials. Prefer provider-hosted or provider-tokenized
  collection to keep sensitive payment data outside Frappe.
- Do not log full webhook payloads if they contain secrets or regulated personal/payment data.
  Redact or select auditable fields.
- Validate redirects; prefer local known routes or explicitly approved origins.

## Money and ERPNext Integrity

- Use provider-defined minor-unit rules and integer amounts at API boundaries. Cover zero-decimal
  and three-decimal currencies where applicable; do not assume every currency uses 100 subunits.
- Validate supported currency, minimum/maximum amount, capture amount, and provider-returned amount
  and currency before marking an Integration Request completed.
- Map `Authorized` separately from `Completed` when capture is deferred. Never create/finalize a
  Payment Entry solely from an unverified browser redirect.
- Settlement must be idempotent and must not overpay the reference. Account for existing Payment
  Entries and outstanding amount. Partial-payment support requires explicit tests.
- Refunds, disputes, fees, chargebacks, and subscription invoices need an approved accounting
  mapping. Do not silently mutate submitted ledger documents from a webhook without that mapping.
- Marketplace flows need an approved ownership and accounting model for gross amount, platform fee,
  provider fee, sub-merchant payable, transfers, payouts, reserves, negative balances, refund
  allocation, and dispute liability. Do not assume a Payment Entry alone represents the full flow.
- Store provider transaction/account identifiers needed for later refund, audit, and reconciliation.
- Scheduler and webhook batches must isolate failures per row/event and be safe to rerun.

## Settings and Operations

- Settings credentials use Password fields; public client keys may use Data fields.
- Support sandbox/live separation without accidentally using sandbox credentials in production.
- Do not make a remote credential check on every save. Provide a permission-checked "Test
  Credentials" action when useful.
- Clear credential/webhook caches on settings update and deletion.
- For multi-account webhooks, resolve the correct settings record cryptographically or from verified
  provider account metadata. Never guess from untrusted payload fields.
- Generate or display webhook endpoint URLs in settings when administrators must register them.
- Install, migrate, and uninstall hooks must be repeatable. Remove only fields/data owned by the
  provider app, and never delete accounting transactions during uninstall.

## Provider Dashboard, Sandbox, and Webhook Runbook

Before sandbox acceptance, write a provider-specific administrator runbook using current official
documentation. It must identify the exact dashboard menus and cover, when applicable:

1. Creating or selecting the sandbox merchant/API/Business account.
2. Creating the provider application and obtaining sandbox credentials.
3. Creating a separate Personal/buyer/test account and ensuring it has a supported country,
   currency, balance, card, bank, or other test funding instrument.
4. Distinguishing developer-dashboard login, merchant credentials, buyer credentials, API
   credentials, webhook secrets/IDs, browser keys, and short-lived browser tokens.
5. Normalizing copied credentials safely, preserving significant characters, pairing them with the
   correct environment/account/app, and testing them without exposing their values.
6. Creating a public HTTPS webhook/callback, selecting exact event types, storing the returned
   webhook identifier/signing secret, and keeping sandbox/live registrations separate.
7. Sending, resending, or simulating a signed event and confirming external delivery, verification,
   deduplication, processing, and provider acknowledgement.
8. Switching to live only after sandbox acceptance, account approval, compliance, and a separate
   live webhook are ready.

Writing the runbook is autonomous documentation work. Executing dashboard steps 1-8 is not: show the
specific proposed sandbox actions and wait for approval before creating or changing provider-side
state. Live setup and live testing always require a separate approval.

The runbook must state whether each tested payer journey is existing wallet/account login, guest
card payment, creation of a new provider account, remembered-buyer/Fastlane authentication, hosted
redirect, embedded checkout, QR, bank redirect, mandate, or mobile approval. Test data appropriate
to one journey must not be assumed valid for another. In particular, do not tell a developer to use
a fictitious phone number when that exact screen sends a real OTP; prefer a pre-created sandbox
buyer unless account creation itself is in scope.

Research and document the merchant-country x buyer-country x currency x payment-method matrix.
Distinguish global API support from account eligibility and runtime transaction eligibility. Create
sandbox identities for at least one permitted combination and one intentional rejection. Validate
unsupported combinations early with actionable messages rather than allowing the provider popup to
be the first explanation.

Classify credential failures precisely. A provider `401` normally indicates invalid/mismatched
credentials, environment, app, grant, scope, or account activation; it is not explained by the
Frappe checkout page using local HTTP. Record the provider request ID and safe error code/details,
but never credentials or tokens.

### Conditional PayPal Regression Gate

When the selected provider is PayPal, re-research current official documentation and ensure the
following known regressions cannot recur; this list is a minimum gate, not a substitute for current
research:

- Use Sandbox REST credentials from the Business/merchant app for server APIs, and a distinct
  Personal sandbox account as the buyer. A live PayPal/developer-dashboard login is not a sandbox
  buyer credential, and the merchant must not pay itself.
- Test a merchant-country, buyer-country, and currency combination PayPal permits. Validate INR and
  India domestic-payment restrictions before creating or submitting ERPNext Payment Requests.
- For the selected PayPal Web SDK v6 release, verify the exact browser `clientToken` type and
  generation endpoint, `createInstance` parameters, component/button configuration, and one-time
  payment session contract. Test that `.start()` receives a Promise and that its resolved value has
  the exact `{ orderId: string }` shape required by the loaded release.
- Verify that the server create-order response survives both the provider SDK serialization and
  Frappe's `message` envelope without converting, nesting, or dropping the string order ID.
- Render a real non-`None` CSRF token for checkout browser POSTs when the Frappe session requires it;
  provider webhooks must use their provider-authenticated guest path instead of browser CSRF.
- Use a public HTTPS endpoint for real webhook delivery; document the exact PayPal event selections,
  Webhook ID, resend procedure, and separate Sandbox/Live setup.
- Guide card testing with current official test cards only. Do not enter a fake phone into PayPal
  account-signup OTP; log in with a pre-created Personal sandbox buyer unless signup is being tested.
- Confirm Payment Gateway Account and Company payment-account currency/account type, submit the
  actual Payment Request PDF/email path, complete capture, receive the webhook, and verify exactly
  one Payment Entry and correct outstanding amount.

## Required Tests

Every provider app must include an automated unit-test suite under `<app_name>/tests`, with
discoverable `test_*.py` modules. Use pure unit tests for isolated conversion, signing, mapping,
and client behavior; use Frappe integration tests where database, DocType, permissions, hooks, or
transactions are involved. Mock all provider network calls in automated tests and keep sandbox tests
separate. Test the approved SDK/API version explicitly, including version-specific request and
webhook behavior.

- Controller satisfies the V1 contract and registers the correct Payment Gateway.
- Settings schema has capability-driven required/dependency rules, encrypted secrets, read-only
  generated endpoints, and intentional Section/Column Break layout; visually inspect the result.
- Credential validation covers whitespace/copy normalization where safe, wrong environment,
  invalid secret, missing scopes/activation, provider-safe error translation, and no secret leakage.
- Single/multi-account controller resolution and credential isolation.
- Supported/unsupported currencies, minor-unit round trips, special decimal currencies, limits,
  and rounding boundaries.
- Invalid/missing references, cancelled/paid references, and server-authoritative amount/currency.
- Stable idempotency keys and safe retry behavior.
- Callback signature success/failure, missing secret/header, wrong reference/provider ID, replay,
  and raw-body handling.
- Guest endpoints reject unauthenticated/tampered requests and authenticated users require expected
  permissions.
- A real HTTP checkout-page test covers guest/session cookies, rendered CSRF token, Frappe response
  envelopes, error envelopes, and server-side rejection of a stale/cancelled/already-paid reference.
- Browser SDK tests mock the exact selected release contract: initialization token type, component
  eligibility, create-order Promise container/resolution shape, identifier types, approval/capture,
  cancellation, errors, and redirects. Run the provider's JavaScript formatter/linter/tests.
- Built/served assets are checked after rebuild and cache clearing so source-only changes cannot pass
  verification while the browser executes stale code.
- Webhook event deduplication, failed-event retry, unknown-event ignore, out-of-order events, and
  per-event rollback.
- Redirect/webhook races cannot settle twice.
- Status mapping for success, authorization, pending/asynchronous, failure, cancellation, expiry,
  and refund when supported.
- Settlement skips paid references, creates correct Payment Entries, and handles partial payments
  only when supported.
- Marketplace/platform tests cover connected-account isolation, onboarding state, split and fee
  totals, transfer/payout ownership, refund allocation, dispute liability, and webhook routing when
  those capabilities are selected.
- Scheduler jobs early-exit when idle, isolate row failures, avoid per-row setup work, and remain
  rerunnable.
- Install/migrate/uninstall behavior for provider custom fields.
- ERPNext integration tests cover gateway/account creation and applicable company, account type,
  account currency, reference currency, party-account currency, Payment Request, Payment Entry, and
  outstanding-amount behavior. Test legacy `payments`-app guards on each supported branch.
- The representative Payment Request submission path covers print/PDF and email or the explicitly
  selected muted-email path; provider success must not conceal infrastructure failure.
- No manual database commits in public request handlers and no secret leakage in responses/logs.

When the provider offers an official sandbox or test environment and the developer approves the
bounded acceptance sequence, run at least one permitted merchant/buyer/currency/payment-method flow
through verified completion and the applicable ERPNext accounting effect. Also test an intentional
provider rejection, failed payment, cancellation, duplicate delivery, tampered callback, and every
advertised capability. Verify a real provider-to-public-HTTPS webhook when webhooks are in scope.

If the provider has no safe test environment or required accounts are unavailable, do not substitute
a live transaction. Stop at the accurate evidence level and provide the provider-approved manual
test plan. A live smoke test is optional and always requires explicit approval and test-safe funds.
Do not describe an app as production-ready until the applicable layered acceptance gates below pass
and operational webhook/retry behavior is documented.

## Layered Acceptance Gates

Track and report verification using these evidence levels; do not collapse them into an ambiguous
claim such as "tested" or "working":

- `implemented`: code exists.
- `automated verified`: unit/integration tests passed with provider network calls mocked.
- `browser verified`: current served assets completed the checkout UI contract in a real browser.
- `sandbox API verified`: the provider sandbox created/retrieved the expected remote objects.
- `sandbox payment verified`: a permitted sandbox buyer/instrument completed approval and
  authorization/capture.
- `webhook verified`: the provider delivered a signed event to the configured public HTTPS endpoint.
- `ERPNext settled`: exactly one correct Payment Entry/accounting effect occurred and the reference
  outstanding amount/status changed correctly.
- `live verified`: an explicitly approved live smoke transaction completed.

A one-off provider is not ready for handoff until the applicable flow verifies, in order:

1. Installation, migration, assets, workers/scheduler, and local-site preflight.
2. Settings form layout, environment pairing, and credential test.
3. Payment Gateway, Payment Gateway Account, Company, and payment-account configuration.
4. Payment Request submission through its real print/email path.
5. Checkout loading from a fresh browser context with current served assets.
6. Server-authoritative order/session creation and exact browser SDK contract.
7. Approval by a compatible sandbox buyer/test instrument.
8. Authorization/capture with amount, currency, account, and identifier verification.
9. Signed webhook delivery, replay handling, and deduplication when applicable.
10. Integration Request final state, exactly-once Payment Entry/effect, and correct outstanding amount.
11. Cancellation, rejection, retry, duplicate, stale-reference, and regional/currency failure paths.
12. Capability-specific refund, partial capture/payment, subscription, mandate, dispute, or
    reconciliation scenarios.

If provider credentials, buyer accounts, tunnel approval, compliance activation, or another manual
prerequisite is unavailable, stop at the accurate evidence level and provide the remaining numbered
actions. Passing mocked tests must never be presented as browser, sandbox, webhook, accounting, or
live verification.

## Documentation Definition of Done

The provider README must let a new administrator install, configure, and verify the provider without
access to the implementation conversation. Include capability-driven sections for:

- Supported Frappe/ERPNext branches, provider SDK/API/browser SDK versions, feature list, explicit
  exclusions, provider account eligibility, and commercial/compliance prerequisites.
- Installation, migration, asset build/cache, worker/scheduler, canonical `host_name`, port, DNS,
  PDF, email, HTTPS, and tunnel prerequisites.
- A field-by-field Settings guide stating the provider-dashboard source of each value, which values
  are secrets, and how Sandbox/Live values differ.
- Provider-dashboard application creation, merchant/API account, separate buyer/test identities,
  balance/funding instruments, official test data, phone/OTP behavior, and login instructions.
- Supported/unsupported merchant countries, buyer countries, currencies, settlement currencies,
  payment methods, amount limits, and important tested combinations.
- Webhook URL creation, exact event list, identifier/signing secret, public HTTPS setup, delivery
  test/resend, log inspection, retries, and separate Sandbox/Live registrations.
- ERPNext Company, Chart of Accounts, Payment Gateway Account, payment account type/currency,
  reference document, Payment Request, print/email, Payment Entry, refund, and reconciliation setup.
- A complete successful sandbox walkthrough from settings through provider approval, webhook,
  Integration Request, Payment Entry, and outstanding-amount verification.
- Go-live checklist, credential rotation, observability, retry/reconciliation operations, and safe
  rollback/disable procedure.
- Troubleshooting keyed to user-visible symptoms and safe provider error codes, including credentials
  versus HTTP/HTTPS, unsupported regions/currencies, stale assets, CSRF, browser SDK token/shape
  errors, popup/cookie restrictions, PDF/port failures, webhook delivery/signature failures, sandbox
  identity confusion, OTP/account-creation traps, and legacy ERPNext `payments` messages.

Use current official menu names and record documentation access dates. Dashboard labels can change,
so give enough surrounding context to locate renamed items. Public official sandbox test values may
be documented; never include real credentials, private tokens, personal phone numbers, or live card
data. Verify every command and route in the README against the built app.

## Pre-commit and Handoff Readiness

Once implementation and tests are ready for developer handoff:

1. Ensure the provider directory is a local Git repository. If the scaffold did not initialize one,
   ask whether the developer wants `git init` solely so repository-local pre-commit hooks can run.
2. Ensure the provider repository contains the approved `.pre-commit-config.yaml`.
3. Ensure `pre-commit` is available in the Bench/development Python environment. Install it as
   development tooling when absent; do not add it as an application runtime dependency.
4. From the provider repository, run `pre-commit install` to install
   `.git/hooks/pre-commit`.
5. Run `pre-commit run --all-files` until every hook passes. If hooks modify files, review the
   changes, rerun the unit/integration tests, and run all hooks again.
6. Inspect the final diff for generated files, unrelated changes, and secrets.
7. Report the changed files, verification evidence, remaining manual functional-flow steps, and any
   blockers to the developer.

Stop at handoff. Do not stage files, create commits or tags, configure remotes, create hosted
repositories, push branches, publish packages, or deploy. The developer decides how and where to
version, publish, and deploy the completed app.

## Verification Commands

Run focused tests during development, then the complete relevant checks. Use only the site approved
through the Site Selection and Installation Gate.

```bash
# From the provider repository
pre-commit install
pre-commit run --all-files

# From the Bench root
bench --site <confirmed_site> migrate
bench --site <confirmed_site> run-tests --app <app_name>

# CI-equivalent test form used by these repositories
bench --site <confirmed_site> run-parallel-tests --app <app_name> --total-builds 1 --build-number 0
```

Add CI for both `version-16` and `develop`, using the Python/Node/MariaDB versions supported by each
target. Run the repository's Frappe Semgrep rules and test-correctness rules. If a check cannot run,
state exactly why, what was run instead, and the remaining risk.

## Deliverables for a New Provider

Before handoff, provide all of the following inside the generated provider repository:

- Working provider app with no provider-specific changes required in `payment_core` unless an
  approved reusable contract was genuinely missing.
- Settings and setup UI, gateway registration, checkout/initiation, verified return/webhooks,
  Integration Request logging, settlement/reconciliation, and capability-specific jobs.
- Discoverable automated unit/integration test suite and branch-compatible CI/lint/security
  configuration.
- Provider-repository `.pre-commit-config.yaml`, installed Git hook, and a successful
  `pre-commit run --all-files` at handoff.
- README covering prerequisites, installation, sandbox/live setup, credentials, webhook URLs/events,
  supported countries/currencies/features, administrator and buyer test accounts, official test
  data, ERPNext accounting setup, complete sandbox procedure, operations, go-live, and
  troubleshooting according to the Documentation Definition of Done.
- A final implementation report listing researched sources, assumptions, status mapping, security
  controls, migrations/custom fields, exact layered acceptance evidence, deferred features, and any
  remaining manual sandbox/live steps.

Keep generated claims precise. "Implemented" means code and automated tests exist; "verified" means
the relevant checks ran successfully; "sandbox verified" and "live verified" require actual provider
execution and must not be inferred from mocks.
