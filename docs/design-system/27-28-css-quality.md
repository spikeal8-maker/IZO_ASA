# 27. Дизайн-токены и CSS
## 27.1. Foundation tokens
<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>:root {<br />
--color-canvas: #070A08;<br />
--color-surface-1: #0E1410;<br />
--color-surface-2: #151D17;<br />
--color-surface-hover: #1C271F;<br />
--color-field: #090E0B;<br />
--color-media-bg: #050805;<br />
<br />
--color-divider: #202A23;<br />
--color-stroke-subtle: #354239;<br />
--color-stroke-control: #5D6D62;<br />
<br />
--color-text-primary: #F3F7F3;<br />
--color-text-secondary: #C4CEC6;<br />
--color-text-muted: #8F9C92;<br />
--color-text-disabled: #626D65;<br />
<br />
--color-accent: #C7F500;<br />
--color-accent-hover: #DCFF34;<br />
--color-accent-text: #101707;<br />
--color-danger: #FF625D;<br />
--color-warning: #E5B94E;<br />
--color-premium: #D8B5FF;<br />
--color-purple-text: #B37AF5;<br />
}</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 27.2. Geometry
<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>:root {<br />
--radius-xs: .375rem;<br />
--radius-sm: .625rem;<br />
--radius-md: .8125rem;<br />
--radius-lg: 1.0625rem;<br />
--radius-xl: 1.375rem;<br />
--composer-width: clamp(23rem, 22vw, 34rem);<br />
--control-height: clamp(2.75rem, 2.2vw, 3.25rem);<br />
--primary-height: clamp(3.375rem, 2.8vw, 4rem);<br />
}</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 27.3. Container query
<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>.composer { container-type: inline-size; }<br />
<br />
@container (min-width: 27rem) {<br />
.prompt-actions {<br />
display: grid;<br />
grid-template-columns: repeat(4, minmax(0, 1fr));<br />
}<br />
}<br />
<br />
@container (max-width: 21.99rem) {<br />
.prompt-actions { grid-template-columns: repeat(2, 1fr); }<br />
}</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 27.4. Focus
<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>:focus-visible {<br />
outline: 2px solid #C7F500;<br />
outline-offset: 2px;<br />
}<br />
.sticky-footer { scroll-padding-bottom: var(--primary-height); }</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

# 28. Аналитика, usability и QA
## 28.1. Usability-план
Минимальный качественный тест: 15 человек - 5 новичков, 5 регулярных пользователей генераторов, 5 пользователей ИЗО ACA. Тестируются текущая версия и новый эталонный экран.

> **1.** Создать изображение по тексту.
>
> **2.** Использовать старый промпт.
>
> **3.** Преобразовать изображение и сравнить До/После.
>
> **4.** Собрать сцену из трёх референсов.
>
> **5.** Создать видео по тексту.
>
> **6.** Открыть результат в редакторе.
>
> **7.** Понять, какой токен будет списан.

## 28.2. Viewport matrix
| **Категория**    | **Размер** |
|------------------|------------|
| Small mobile     | 320×568    |
| Mobile           | 360×800    |
| iPhone-like      | 390×844    |
| Large mobile     | 430×932    |
| Tablet portrait  | 768×1024   |
| Tablet landscape | 1024×768   |
| Laptop           | 1366×768   |
| Full HD          | 1920×1080  |
| 2K               | 2560×1440  |
| 4K               | 3840×2160  |
| Ultrawide        | 3440×1440  |

## 28.3. Acceptance checklist
- Нет обрезанного русского текста.

- Нет горизонтального scroll вне разрешённых лент.

- Focus не закрывается sticky-элементами.

- Контраст проходит автоматическую и ручную проверку.

- Цели не меньше продуктового минимума.

- Компонент работает во всех состояниях.

- История показывает пропорции.

- Промпт длиной 2000 символов не ломает layout.

- 4 референса и длинные названия моделей не ломают Composer.

- Результат на mobile позволяет изменить промпт и создать ещё.
