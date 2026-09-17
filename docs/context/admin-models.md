---
status: canonical
domain: admin-models
read_when: ["admin-models","model-economics","openrouter-models"]
source_paths: ["frontend/src/adminModelsRoutes.ts","frontend/src/adminModels.tsx","frontend/src/adminTextModelCatalog.tsx","backend/app/api/routers/admin_operations.py","backend/app/services/openrouter_image_economics.py","backend/app/services/image_model_publication.py","backend/app/services/video_pricing.py"]
test_paths: ["backend/test_admin_v2.py","backend/test_openrouter_admin_cache_v2.py","backend/test_openrouter_image_economics.py","backend/test_openrouter_token_reconciliation.py","frontend/e2e-admin-model-pages.mjs"]
related_domains: ["admin-control-center"]
forbidden_paths: ["frontend/src/LegacyApp.tsx","frontend/src/newUi.tsx"]
owner: admin-models
context_role: scoped-domain-map
updated: 2026-09-16
---
# Context: admin model catalog and economics

Назначение: bounded routing для `/admin/models/*`, каталога OpenRouter,
публикации моделей, себестоимости, token pricing, margin и тарифной доступности.
Не использовать эту карту для CRM, payments, notifications или generation UI.

## Route ownership

- `frontend/src/adminModelsRoutes.ts` — первый файл для route/page ownership.
- OpenRouter pages: text, images, video, audio, 3D, settings.
- `frontend/src/adminModels.tsx` — большой shell/hotspot; не читать целиком.
- `frontend/src/adminTextModelCatalog.tsx` — text-model catalog/economics leaf.

## Backend/API ownership

- `backend/app/api/routers/admin_operations.py` owns OpenRouter status,
  catalog refresh, pricing, exchange refresh and config mutations.
- `backend/app/services/openrouter_image_economics.py` owns structured image
  cost estimates and actual-cost comparison helpers.
- `backend/app/services/image_model_publication.py` owns published/enabled/access
  normalization for image models and tariff visibility.
- `backend/app/services/video_pricing.py` owns video pricing semantics.
- Compatibility wiring may still exist in `backend/main.py`; use
  `backend/SYMBOL_MAP.md` for an exact symbol range instead of full-reading it.

## Economics change path

For a retail-economics change, trace in this order:

1. route/page in `adminModelsRoutes.ts`;
2. leaf UI/economics logic in the relevant admin component;
3. admin pricing/config route in `admin_operations.py`;
4. economics/publication service that owns the calculation or visibility rule;
5. focused backend tests plus `frontend/e2e-admin-model-pages.mjs`.

Do not treat an admin checkbox as the only source of truth: provider pricing,
publication, tariff access, quote/reservation/settlement and user-visible model
availability must remain consistent.

## Focused verification

- `backend/test_openrouter_image_economics.py` — image cost semantics.
- `backend/test_openrouter_token_reconciliation.py` — token/economics settlement.
- `backend/test_openrouter_admin_cache_v2.py` — admin catalog/cache behavior.
- `backend/test_admin_v2.py` — trusted admin/API contracts.
- `frontend/e2e-admin-model-pages.mjs` — model-page routing/layout contract.

For auth/session changes also load `backend-auth-bots`; for broader admin shell
changes use `admin-control-center` instead of expanding this package silently.

## Guardrails

- Do not full-read `adminModels.tsx`, `backend/main.py`, large CSS or generated
  inventories when a route/symbol/range is sufficient.
- Do not touch `newUi.tsx` or `LegacyApp.tsx` for admin-model economics.
- Provider calls, catalog refresh, real payment/tariff mutations and deployment
  require separate operator/release scope.
- Production DB/media/secrets are never fixtures.
- Missing or low-confidence provider price must not silently become a cheap
  user-facing retail price.

## Change routing table

| Task | Start here | Add only when needed |
|---|---|---|
| Models navigation | `adminModelsRoutes.ts` | target leaf component |
| Text economics | `adminTextModelCatalog.tsx` | admin pricing API/tests |
| Image cost | `openrouter_image_economics.py` | publication + economics tests |
| Image visibility | `image_model_publication.py` | tariff/public access tests |
| Video cost | `video_pricing.py` | video page/tests |
| Provider settings | `admin_operations.py` | config/cache tests |

## API/evidence pointers

`admin_operations.py` exposes the bounded OpenRouter admin surface for status,
catalog status/refresh, pricing, exchange refresh and config. Use the exact route
function rather than searching all of `backend/main.py`.

`docs/generated/frontend-map.md` and `backend/SYMBOL_MAP.md` are discovery aids;
they are not proof that economics or security invariants are satisfied.

## Explicit unknowns

- Provider catalog/pricing can change independently of the source release.
- A displayed price does not prove settlement used the same price source.
- 3D model routing remains a product boundary that must not be described as
  operational solely because an admin route exists.
- Live catalog refresh/provider tests are operator actions, not unit fixtures.
