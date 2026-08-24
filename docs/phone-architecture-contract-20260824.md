# PHONE-ARCH-001 — контракт мобильной платформы

Статус: **CODE COMPLETE; TARGETED TESTS AND FRONTEND BUILD GREEN; NOT DEPLOYED**.

## Граница

`/phone` остаётся частью текущего React/FastAPI продукта. Новая бизнес-логика
не добавляется в `phone-prototype.html`, `phone-runtime.js` или временный
sidecar. Эти файлы сохраняются только как переходный reference до достижения
паритета.

Нативная структура frontend:

```text
frontend/src/phone/
  contracts.ts  — versioned product-safe типы
  api.ts        — authenticated transport
  routes.ts     — прямые маршруты и refresh contract
  shell/*       — общий App Shell (следующий пакет)
  features/*    — image, video, chat, audio, 3d
```

Backend остаётся модульным монолитом:

```text
backend/app/api/routers/phone_platform.py
backend/app/services/phone_platform.py
```

`backend/main.py` только подключает router и передаёт trusted-session boundary.

## Versioned manifest

`GET /api/phone/v1/platform` требует trusted user и возвращает только
пользовательские возможности:

- пять workspace и прямые маршруты;
- доступность, стадия и разрешённые операции;
- размещение в основной навигации или центральном меню;
- версии contracts capabilities/jobs/media/billing;
- свойства общего shell.

Manifest не содержит provider name, checkpoint, workflow, provider URL,
секреты или себестоимость. Feature flags вычисляются сервером. В первой версии
image/video/chat включены, audio честно отмечен partial и выключен до полного
workflow, 3D отмечен planned и выключен до provider spike.

## Совместимость

- Существующие `/api/phone/chat/*`, `/api/generate`, `/api/video/*`, gallery и
  media endpoints не удаляются.
- Phone v1 facade будет переходить на общие domain services пакетами, без
  копирования SQL и provider logic.
- Старые `/phone` iframe и runtime удаляются только после browser parity tests.
- Desktop routes не меняются.

## Evidence

- phone platform/router/chat tests: `13 passed`;
- Python compilation: green;
- frontend lint and production build: green;
- generated backend/frontend maps refreshed.

## Следующий пакет

`PHONE-SHELL-001`: прямые `/phone/*` маршруты, нативный React shell, загрузка
manifest, состояния loading/auth/offline/error, навигация, modal и notification
hosts. Feature screens сначала подключаются через явные compatibility panels;
iframe не становится архитектурой нового shell.
