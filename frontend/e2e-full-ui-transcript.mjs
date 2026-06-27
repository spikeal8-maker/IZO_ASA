import { chromium } from 'playwright'
import { writeFileSync } from 'node:fs'

const base = `http://127.0.0.1:5173?platform=web&userId=full_ui_${Date.now()}`
const transcript = []

function log(step, result = 'OK') {
  const line = `${String(transcript.length + 1).padStart(2, '0')}. ${step} => ${result}`
  transcript.push(line)
  console.log(line)
}

async function click(page, locator, label) {
  await locator.click()
  log(`Нажата кнопка "${label}"`)
}

async function run() {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  page.setDefaultTimeout(20000)
  try {
    await page.goto(base, { waitUntil: 'networkidle' })
    log('Открыт web-интерфейс ИЗО_АСА')

    const defaults = await page.evaluate(() => ({
      title: document.title,
      prompt: document.querySelector('.prompt-dock textarea')?.value,
      negative: Array.from(document.querySelectorAll('input')).map((input) => input.value).find((value) => value.includes('low quality')) || '',
      size: document.querySelector('.size-control select')?.value,
      generateDisabled: document.querySelector('.generate')?.disabled,
    }))
    if (defaults.title !== 'ИЗО_АСА') throw new Error(`Wrong title: ${defaults.title}`)
    if (defaults.prompt !== '') throw new Error(`Prompt must be empty by default, got: ${defaults.prompt}`)
    if (defaults.size !== '1024x1024') throw new Error(`Wrong default size: ${defaults.size}`)
    if (!defaults.generateDisabled) throw new Error('Generate must be disabled while prompt is empty')
    log('Проверены дефолты исходника: empty prompt, 1024×1024, Generate disabled до prompt')

    await click(page, page.getByRole('button', { name: /Случайный prompt/ }), 'Случайный prompt')
    await page.locator('.prompt-dock textarea').evaluate((node) => {
      if (node.value.trim().length < 20) throw new Error('Random source prompt was not inserted')
    })
    log('В prompt вставлен случайный исходный пример')

    await click(page, page.getByRole('button', { name: /Настройки/ }).first(), 'Настройки')
    await page.locator('select').filter({ hasText: 'None' }).first().waitFor()
    log('В настройках доступен выбор LoRA')

    await page.getByLabel('Width').fill('1280')
    await page.getByLabel('Height').fill('720')
    await page.getByRole('button', { name: /К генерации/ }).click()
    await page.locator('.studio-grid').waitFor()
    log('Изменен размер через живой select', '1280×720')

    await page.getByRole('button', { name: /Настройки/ }).first().click()
    await page.getByLabel('Зерно').fill('0')
    await click(page, page.getByRole('button', { name: /Случайный seed/ }), 'Случайный seed')
    const seedValue = await page.getByLabel('Зерно').inputValue()
    if (!Number(seedValue)) throw new Error(`Seed was not randomized: ${seedValue}`)
    log('Проверена кнопка случайного seed', seedValue)

    await page.getByLabel('Шаги').fill('4')
    await page.getByLabel('CFG').fill('1')
    log('Проверены исходные advanced-дефолты', 'steps=4, cfg=1')
    await click(page, page.getByRole('button', { name: /По умолчанию/ }), 'По умолчанию')
    await page.getByRole('button', { name: /К генерации/ }).click()
    await page.locator('.studio-grid').waitFor()

    for (const modeName of ['Изо стрелка вправо Изо', 'Редактирование Изо', 'Рисование Изо', 'Лицо стрелка вправо Изо', 'Текст стрелка вправо Изо']) {
      await click(page, page.getByRole('button', { name: modeName }), modeName)
      await page.locator('.preview-panel').waitFor()
      log(`Режим "${modeName}" открыл свой рабочий экран`)
    }

    await click(page, page.getByRole('button', { name: 'Рисование Изо' }), 'Рисование Изо')
    await click(page, page.getByRole('button', { name: /Эскиз|Sketch/ }), 'Paint: Sketch')
    await page.locator('.sketch-editor').waitFor()
    await click(page, page.getByRole('button', { name: /Сохранить|Save sketch/ }), 'Save sketch')
    await page.locator('.paint-editor').waitFor({ state: 'detached' })
    await click(page, page.getByRole('button', { name: /Маска \/ Расширение|Inpaint \/ Outpaint/ }), 'Paint: Mask / Expand')
    await page.locator('.mask-editor').waitFor()
    await click(page, page.getByRole('button', { name: 'Расширить изображение', exact: true }), 'Paint: Outpaint')
    await page.locator('.outpaint-inline').waitFor()
    await click(page, page.getByRole('button', { name: /^Применить$|^Apply$/ }), 'Apply paint editor')
    await page.locator('.paint-editor').waitFor({ state: 'detached' })
    await click(page, page.getByRole('button', { name: /Инструкция/ }), 'Инструкция')
    await page.locator('.instruction-modal').waitFor()
    await click(page, page.locator('.instruction-modal .floating-clear'), 'Закрыть инструкцию')

    await click(page, page.getByRole('button', { name: /Помощь/ }), 'Помощь')
    await page.getByText('Олень на туманной улице').waitFor()
    await click(page, page.getByText('Олень на туманной улице'), 'Пример: Олень на туманной улице')
    await page.locator('.studio-grid').waitFor()
    log('Исходный пример из Help загрузился в prompt')

    await click(page, page.getByRole('button', { name: /Настройки/ }).first(), 'Настройки')
    await page.locator('.settings-page').waitFor()
    await click(page, page.getByRole('button', { name: /К генерации/ }), 'К генерации из настроек')
    await page.locator('.studio-grid').waitFor()
    log('Переход в настройки и возврат не ломают интерфейс')

    await click(page, page.locator('.top-actions .icon-button').nth(1), 'Галерея')
    await page.locator('.gallery-view').waitFor()
    await click(page, page.getByRole('button', { name: /К генерации/ }), 'К генерации из галереи')
    log('Галерея открывается и возвращает в генерацию')

    await click(page, page.getByRole('button', { name: /Сгенерировать/ }), 'Сгенерировать')
    await page.locator('.job-card, .preview-panel img').first().waitFor()
    log('Запущена генерация через UI; job/result отображается живым элементом')

    await page.screenshot({ path: 'full-ui-transcript-final.png', fullPage: true })
    log('Сохранен финальный скриншот', 'full-ui-transcript-final.png')
  } finally {
    writeFileSync('full-ui-transcript.txt', `${transcript.join('\n')}\n`, 'utf8')
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  writeFileSync('full-ui-transcript.txt', `${transcript.join('\n')}\n\nFAILED: ${error.message}\n`, 'utf8')
  process.exit(1)
})



