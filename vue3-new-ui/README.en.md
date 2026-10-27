# HOIM Frontend

[中文](README.md) | **English**

The Web frontend for the HOIM hospital information management system. It lives in `vue3-new-ui/` in the [hoimsystem repository](https://github.com/Palpitate-xus/hoimsystem) and works with the FastAPI backend in `fastapi_be/`.

The application covers outpatient registration and doctor workstations, inpatient and nursing workflows, pharmacy and inventory, laboratory and imaging, health examinations, billing, patient services, operational reports, and administration. Menus and actions follow the signed-in user's role and business permissions.

## Stack and structure

| Purpose | Technology |
| --- | --- |
| Pages and components | Vue 3.5, Element Plus 2, Sass |
| Routing and state | Vue Router 5, Vuex 4 |
| HTTP and charts | Axios, ECharts 6 |
| Development and builds | Rspack 2, Vue Loader, Babel |
| Tests | Node.js built-in test runner, Playwright |

See [package.json](package.json) for dependency ranges and commands, and [package-lock.json](package-lock.json) for resolved versions.

```text
vue3-new-ui/
├── src/
│   ├── views/          # Business pages, AI workbench and management center
│   ├── components/     # Business components, shared assistant and domain AI panels
│   ├── api/            # API clients and source/result contracts
│   ├── router/         # Routes and role metadata
│   ├── store/          # Session and application state
│   ├── config/         # Title, port and network settings
│   └── styles/         # Shared styles
├── layouts/            # Application layouts
├── public/             # HTML template and static files
├── tests/              # Node.js tests
├── scripts/            # Build checks, data generation and Node.js tests
├── e2e/                # Playwright tests and isolated fixtures
└── rspack.config.js    # Build, development server and proxy configuration
```

## Run locally

Use Node.js matching `^20.19.0 || >=22.12.0` and npm 10 or later.

```bash
git clone https://github.com/Palpitate-xus/hoimsystem.git
cd hoimsystem/vue3-new-ui
npm ci --legacy-peer-deps
npm run serve:rspack
```

Open <http://localhost:8091>. Follow the [project README](../README.en.md) and [deployment guide](../doc/installation-guide.md) for backend configuration, database migrations and API startup. Asynchronous AI tasks use a separate backend worker; its startup steps are in the [AI usage guide](../doc/ai-guide.md).

### Port and API settings

| Setting | Current value and location |
| --- | --- |
| Development port | `devPort: "8091"` in [setting.config.js](src/config/setting.config.js), used by the Rspack development server |
| Routing mode | `routerMode: "hash"` in the same file |
| API prefix | `baseURL: "/api"` in [net.config.js](src/config/net.config.js), used in development and production |
| Development proxy | `devServer.proxy` in [rspack.config.js](rspack.config.js) forwards `/api` to `http://localhost:8000`, preserving the request path |
| Build output | `outputDir: "dist"` in `setting.config.js` |

To use another backend, change the development proxy's `target`. Change `devPort` to use another local port. For production, serve `dist/` through a static Web server and proxy same-origin `/api` requests to the backend. See the [deployment guide](../doc/installation-guide.md) for examples.

Enable development Mock explicitly from the command line:

```bash
VUE_APP_MOCK_ENABLE=true npm run serve:rspack
```

[rspack.js](rspack.js) and the development middleware read this flag; its default is `false`. The default startup command connects to FastAPI through the proxy.

## AI workbench and business entry points

| Entry | Usage |
| --- | --- |
| `/#/ai/workbench` | AI business assistant: select an authorized capability and patient or business scope, review the inputs, submit a task, and inspect results, evidence and review feedback |
| `/#/ai/manage` | AI management center: the `super_admin` role manages features, models, Prompts, knowledge, sources and access, and inspects tasks, usage and audit records |
| Business record rows | Actions such as “检查病历” (review record), “核查处方” (review prescription), “核查用药” (review medication) and “术前评估” (preoperative assessment) carry the current record, patient and encounter scope |
| Operational and source pages | Bed, inventory, operational reporting, drug label and research pages provide the relevant source selection, review and analysis entry points |

The [80-capability catalog](../doc/ai-capabilities.md) covers text summaries and clinical references, document drafts, medication checks, patient communication, speech, imaging, ECG, risk rules, operational forecasting, research and training. Available tasks follow role permissions, feature configuration and the intended use of the selected sources. Results present evidence, missing information and items for human review.

### Super administrator management

The management center contains 41 entries in four groups, with a searchable “查找管理入口” directory:

| Group | Contents |
| --- | --- |
| 功能与模型 — Features and models | Feature activation, roles and quotas, Prompt versions, text models and specialist services |
| 知识与数据 — Knowledge and data | Knowledge review and clinical, operational, drug label, research, operations support, training and other source management |
| 任务与用量 — Tasks and usage | Global technical task directory, tasks and feedback, usage statistics |
| 权限与审计 — Permissions and audit | Patient access grants, configuration audit and feedback de-identification review |

Configure the actual model service and its permitted uses, prepare and review knowledge or domain sources, then select roles, model, Prompt, quota and validation records in “能力与启用” before enabling a capability. Source directories, published material and task content each follow their own access checks. See the [AI usage guide](../doc/ai-guide.md) for the configuration workflow.

### Review and copy document sections

Outpatient notes, admission notes, progress notes, discharge summaries and imaging report drafts display the document body separately from the summary, warnings and missing information. “复制文书正文” (copy document body) opens a section review dialog. Select and review the sections; confirm review of any warnings or missing items before copying. The clipboard preserves the selected section text and order. Continue editing, signing and submitting through the original business page.

Training follows “select course → answer and submit → review score and rationale → request AI explanation.” Fixed scores and model feedback are shown separately.

## Build and checks

Run these commands from `vue3-new-ui/`:

| Command | Purpose |
| --- | --- |
| `npm run serve:rspack` | Start the development server |
| `npm run build` | Regenerate production resources in `dist/` |
| `npm run audit` | Audit npm dependencies at the `low` threshold |
| `npm run check:bundle` | Check the existing `dist/` against individual JS, total JS and total asset size budgets |
| `npm run verify` | Run the dependency audit, production build and bundle budget check in sequence |
| `npm run build:zip` | Build and create `dist/dist.zip` |
| `npm run test:e2e -- <test-path>` | Run selected Playwright tests |

Node.js tests live in `tests/` and `scripts/`. Run individual files or both test collections:

```bash
node --test tests/aiManagementNavigation.test.cjs scripts/ai-document-draft.test.cjs
node --test tests/*.test.cjs scripts/*.test.cjs
```

See [playwright.config.js](playwright.config.js) for browser test settings. Install Chromium, then select tests for the affected area:

```bash
npx playwright install chromium
npm run test:e2e -- --list
npm run test:e2e -- e2e/ai-management-navigation.spec.js --workers=1
```

Some tests start an isolated page through a fixture. Tests that visit the full application use `E2E_BASE_URL`, which defaults to `http://localhost:8091`. Start the frontend first, or point these tests at a server hosting the build:

```bash
E2E_BASE_URL=http://localhost:8091 npm run test:e2e -- e2e/ai-workbench.spec.js --workers=1
npx playwright show-report
```

## Documentation and attribution

- [Project overview and backend startup](../README.en.md)
- [AI usage and configuration guide](../doc/ai-guide.md)
- [AI capability catalog](../doc/ai-capabilities.md)
- [Deployment guide](../doc/installation-guide.md)

The frontend layout foundation comes from [Vue Admin Better](https://github.com/zxwk1998/vue-admin-better), extended with HOIM hospital workflows and the AI platform. The upstream MIT license and copyright notice are retained in this directory's [LICENSE](LICENSE).
