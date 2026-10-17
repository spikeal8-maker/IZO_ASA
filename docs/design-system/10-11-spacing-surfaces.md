# 10. Spacing, сетка и плотность
> **Иллюстрация:** Рисунок 5. Базовая геометрия системы.

Рисунок 5. Базовая геометрия системы.

## 10.1. Spacing scale
Базовая шкала: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64 CSS px. В коде используются rem и clamp(); значения являются визуальными ориентирами, а не жёсткой привязкой к физическим пикселям.

## 10.2. Плотность
| **Контекст** | **Плотность**   | **Правило**                                 |
|--------------|-----------------|---------------------------------------------|
| Mobile       | Comfort         | Минимум 44×44, больше вертикального воздуха |
| Laptop       | Compact/Comfort | Сокращаются отступы, но не текст            |
| Full HD      | Comfort         | Эталонная плотность                         |
| 4K           | Comfort+        | Увеличиваются текст, контролы и история     |
| Editor       | Compact tools   | Холст получает максимум площади             |

## 10.3. Composer width
<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>--composer-width: clamp(23rem, 22vw, 34rem);<br />
--history-height: clamp(5.5rem, 7vw, 9rem);<br />
--control-height: clamp(2.75rem, 2.2vw, 3.25rem);</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 10.4. Scroll policy
- Desktop: только Composer вертикально.

- History: только горизонтально.

- Stage: без scroll; масштабирование через fit/zoom.

- Mobile: один основной вертикальный scroll страницы/состояния.

- Вложенные вертикальные scroll-зоны на mobile запрещены, кроме длинного prompt text в раскрытом контексте.

# 11. Форма, глубина и поверхности
## 11.1. Радиусы
| **Token** | **Размер** | **Компоненты**                |
|-----------|------------|-------------------------------|
| radius-xs | 6 px       | Бейджи, метки                 |
| radius-sm | 10 px      | Compact button, миниатюра     |
| radius-md | 13 px      | Обычная кнопка, поле, select  |
| radius-lg | 17 px      | Панель, CTA, крупная карточка |
| radius-xl | 22 px      | Bottom sheet, крупный popover |

## 11.2. Уровни поверхности
| **Уровень**   | **Средство**               | **Пример**                     |
|---------------|----------------------------|--------------------------------|
| 0 Canvas      | \#070A08, без рамки        | Фон приложения                 |
| 1 Region      | Surface 1 + divider        | Composer, Context Shelf        |
| 2 Interactive | Surface 2 + control stroke | Кнопка, select, card           |
| 3 Active      | Lime fill/outline          | CTA, selected                  |
| 4 Overlay     | Shadow + backdrop          | Popover, bottom sheet, confirm |

## 11.3. Тени
<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>.button-secondary {<br />
box-shadow:<br />
inset 0 1px rgba(255,255,255,.04),<br />
0 2px 0 rgba(0,0,0,.18);<br />
}<br />
.overlay { box-shadow: 0 16px 46px rgba(0,0,0,.40); }</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th><p><strong>Запрет</strong></p>
<p>Glassmorphism, тяжёлые размытия и светящиеся рамки не являются основой интерфейса. Они допустимы только в ограниченных иллюстративных состояниях.</p></th>
</tr>
</thead>
<tbody>
</tbody>
</table>
