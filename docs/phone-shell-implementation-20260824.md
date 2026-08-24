# PHONE-SHELL-001 — нативный мобильный App Shell

Статус: **CODE COMPLETE; BROWSER AND AUTOMATED E2E GREEN; NOT DEPLOYED**.

## Реализовано

- React shell вместо iframe для `/phone` и всех `/phone/*` маршрутов;
- redirect `/phone` на последний доступный или стартовый workspace;
- прямые `/phone/image`, `/phone/video`, `/phone/chat`, `/phone/audio`,
  `/phone/3d` с сохранением маршрута после refresh;
- server-owned manifest `/api/phone/v1/platform`;
- общая шапка, лента, галерея, профиль и два вида баланса;
- нижняя навигация из manifest и центральное меню для полного списка;
- 3D находится в меню, а не шестой тесной кнопкой;
- disabled/partial/planned состояния не имитируют работающую функцию;
- loading, trusted-auth, unavailable, stale-cache и offline состояния;
- центральный modal host, notification host, закрытие меню по фону, Escape,
  кнопке и свайпу вниз;
- safe-area, reduced-motion и брейкпоинты 390/430/узкий экран.

Старые `phone-prototype.html`, `phone-runtime.js`, iframe component и legacy E2E
не удалены: они остаются reference до функционального паритета. Новая
бизнес-логика в них больше не добавляется.

## Evidence

- frontend lint: green;
- production build: green;
- native browser test в Chrome: 390×844 и 430×932, overflow отсутствует;
- `/phone/chat` после reload остаётся `/phone/chat`;
- menu swipe close: green;
- browser console errors: 0;
- automated `e2e:phone-shell`: green на двух viewport;
- native shell iframe count: 0.

## Ограничение пакета

Feature-панели пока являются честными точками подключения. Этот пакет не
объявляет image/video/chat/audio/3D workflow перенесёнными. Следующий пакет
`PHONE-CORE-001` добавляет общий transport jobs/media/billing и recovery,
после чего feature-пакеты заменяют панели рабочими областями по очереди.
