# 29. Governance и версия компонентов
> **Иллюстрация:** Рисунок 12. Процесс изменения дизайн-системы.

Рисунок 12. Процесс изменения дизайн-системы.

## 29.1. Источники истины
> **1.** Figma Variables и компоненты.
>
> **2.** CSS design tokens.
>
> **3.** Storybook или аналог компонента.
>
> **4.** Design System document.
>
> **5.** Changelog и migration notes.

## 29.2. Версионирование
| **Тип изменения** | **Версия** | **Пример**                                  |
|-------------------|------------|---------------------------------------------|
| Patch             | 2.0.1      | Исправление контраста без API компонента    |
| Minor             | 2.1        | Новый компонент на существующих токенах     |
| Major             | 3.0        | Изменение основного акцента или архитектуры |

## 29.3. Design review
- Задача и пользовательский результат.

- Проверка reuse.

- Проверка токенов.

- Responsive states.

- A11y states.

- Copy review.

- QA screenshot matrix.

- Документация и changelog.

# 30. План внедрения
| **Этап**                       | **Приоритет** | **Результат**                           |
|--------------------------------|---------------|-----------------------------------------|
| Foundation tokens              | P0            | Цвет, type, spacing, radius, elevation  |
| Core components                | P0            | Buttons, fields, tabs, segmented, cards |
| Эталон «По тексту» desktop     | P0            | Золотой экран Full HD                   |
| Mobile до/после генерации      | P0            | Основной мобильный цикл                 |
| По изображению / Из нескольких | P1            | Источники, slider, roles                |
| Context Shelf                  | P1            | История и prompt context                |
| Editor shell                   | P1            | Canvas + tools + properties             |
| Video page                     | P1            | 4 режима, player, history, prompt       |
| Gallery / Feed / Profile       | P2            | Личная и социальная работа              |
| Telegram / MAX                 | P2            | Container-specific adaptation           |
| Accessibility / analytics      | Постоянно     | AA, metrics, usability                  |
| Governance                     | Постоянно     | Versioning, Storybook, review           |

## 30.1. Порядок
Следует сначала довести один эталонный Full HD экран «По тексту» и мобильный цикл до/после генерации. Затем переносить компоненты на остальные вкладки. Одновременная визуальная переработка всех экранов без component baseline запрещена.

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th><p><strong>Рекомендуемый pipeline</strong></p>
<p>Figma variables → CSS tokens → Storybook → эталонный экран → usability test → перенос на остальные страницы → визуальный regression QA.</p></th>
</tr>
</thead>
<tbody>
</tbody>
</table>

# 31. Источники и нормативная база
**\[1\] Material Design 3 — Color roles.** [<u>https://m3.material.io/styles/color/roles</u>](https://m3.material.io/styles/color/roles) — Семантические роли цвета.

**\[2\] Material Design 3 — Design tokens.** [<u>https://m3.material.io/foundations/design-tokens</u>](https://m3.material.io/foundations/design-tokens) — Роли цвета, type, shape и elevation.

**\[3\] Fluent 2 — Design tokens.** [<u>https://fluent2.microsoft.design/design-tokens</u>](https://fluent2.microsoft.design/design-tokens) — Единый язык между дизайном и разработкой.

**\[4\] Fluent 2 — Color.** [<u>https://fluent2.microsoft.design/color</u>](https://fluent2.microsoft.design/color) — Global и alias color tokens.

**\[5\] Fluent 2 — Typography.** [<u>https://fluent2.microsoft.design/typography</u>](https://fluent2.microsoft.design/typography) — Иерархия текста.

**\[6\] Fluent 2 — Layout.** [<u>https://fluent2.microsoft.design/layout</u>](https://fluent2.microsoft.design/layout) — Пространство и приоритет.

**\[7\] Adobe Spectrum — Button.** [<u>https://spectrum.adobe.com/page/button/</u>](https://spectrum.adobe.com/page/button/) — Уровни визуальной громкости кнопок.

**\[8\] Adobe Spectrum — Inclusive design.** [<u>https://spectrum.adobe.com/page/inclusive-design/</u>](https://spectrum.adobe.com/page/inclusive-design/) — Мышь, клавиатура, touch, voice и a11y API.

**\[9\] Apple HIG — Typography.** [<u>https://developer.apple.com/design/human-interface-guidelines/typography</u>](https://developer.apple.com/design/human-interface-guidelines/typography) — Масштабирование и читаемость.

**\[10\] Apple HIG — Layout.** [<u>https://developer.apple.com/design/human-interface-guidelines/layout</u>](https://developer.apple.com/design/human-interface-guidelines/layout) — Проверка устройств, ориентаций и локализаций.

**\[11\] Apple HIG — Accessibility.** [<u>https://developer.apple.com/design/human-interface-guidelines/accessibility</u>](https://developer.apple.com/design/human-interface-guidelines/accessibility) — Инклюзивный дизайн.

**\[12\] Apple HIG — Motion.** [<u>https://developer.apple.com/design/human-interface-guidelines/motion</u>](https://developer.apple.com/design/human-interface-guidelines/motion) — Последовательное движение.

**\[13\] WCAG 2.2 — Contrast Minimum.** [<u>https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html</u>](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) — 4.5:1 и 3:1.

**\[14\] WCAG 2.2 — Non-text Contrast.** [<u>https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html</u>](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html) — Контраст границ и состояний.

**\[15\] WCAG 2.2 — Target Size Minimum.** [<u>https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum</u>](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum) — Минимум 24 CSS px; внутренний стандарт 44.

**\[16\] WCAG 2.2 — Text Spacing.** [<u>https://www.w3.org/WAI/WCAG22/Understanding/text-spacing.html</u>](https://www.w3.org/WAI/WCAG22/Understanding/text-spacing.html) — Адаптация к пользовательским spacing settings.

**\[17\] WCAG 2.2 — Resize Text.** [<u>https://www.w3.org/WAI/WCAG22/Understanding/resize-text.html</u>](https://www.w3.org/WAI/WCAG22/Understanding/resize-text.html) — 200% без потери функций.

**\[18\] WCAG 2.2 — Use of Color.** [<u>https://www.w3.org/WAI/WCAG22/Understanding/use-of-color</u>](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color) — Цвет не единственный сигнал.

**\[19\] WCAG 2.2 — Focus Appearance.** [<u>https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html</u>](https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html) — Видимый focus indicator.

**\[20\] WCAG 2.2 — Focus Not Obscured.** [<u>https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum.html</u>](https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum.html) — Sticky элементы не скрывают focus.

**\[21\] MDN — Container queries.** [<u>https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Containment/Container_queries</u>](https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Containment/Container_queries) — Адаптация компонента по контейнеру.

**\[22\] MDN — clamp().** [<u>https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Values/clamp</u>](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Values/clamp) — Fluid sizing.

**\[23\] MDN — Media queries.** [<u>https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Media_queries</u>](https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Media_queries) — Viewport и user preferences.

**\[24\] Onest — official repository.** [<u>https://github.com/simpals/onest</u>](https://github.com/simpals/onest) — Экранная читаемость и интерфейсное применение.

Дата обращения к источникам: 16 июля 2026. Документ использует официальные спецификации и дизайн-системы как нормативную базу; конкретная визуальная система ИЗО ACA является самостоятельным продуктовым решением.

**32. Design Constitution**

Короткая проверка любого нового решения

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th><p><strong>12 правил, которые нельзя нарушать</strong></p>
<p>1) Медиа важнее интерфейса. 2) Один функциональный акцент. 3) Один главный CTA. 4) Обычный текст не жирный. 5) Один набор иконок. 6) Медиа не обрезается без явного crop. 7) Контекст работы сохраняется. 8) Сложность раскрывается постепенно. 9) Компоненты адаптируются к контейнеру. 10) Mobile меняет сценарий. 11) Редактор имеет canvas-архитектуру. 12) Доступность проверяется до релиза.</p></th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## Формула ИЗО ACA
Тёмный холст + спокойные зелёно-чёрные поверхности + светлый читаемый текст + один лаймовый функциональный акцент + умеренная тактильность + Onest Variable + адаптивные токены + предсказуемые паттерны.

## Финальный вопрос перед релизом
<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th><p><strong>Проверка</strong></p>
<p>Станет ли результат пользователя больше, понятнее или доступнее? Если ответ «нет», новый визуальный эффект, кнопка или панель, вероятно, не нужны.</p></th>
</tr>
</thead>
<tbody>
</tbody>
</table>

> **Иллюстрация:** Итоговая палитра дизайн-системы ИЗО ACA: тёмные поверхности, лаймовый акцент и семантические цвета

**ИЗО ACA · Design System 2.0**

*Спокойная рабочая система должна быть ясной до того, как станет эффектной.*
