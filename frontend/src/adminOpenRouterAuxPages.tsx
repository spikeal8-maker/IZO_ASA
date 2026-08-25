export type OpenRouterAudioModel = {
  id: string
  name: string
  inputPerMillionUsd: number
  outputPerMillionUsd: number
  contextLength: number
}

export function OpenRouterAudioPage({ models, error, selectedModel, usdRub }: {
  models: OpenRouterAudioModel[]
  error?: string | null
  selectedModel: string
  usdRub: number | null
}) {
  return <article className="card video-catalog-card">
    <div className="video-catalog-head">
      <div className="video-catalog-title"><div><h2 className="card-title">Каталог звуковых моделей</h2><p className="card-note">OpenRouter-модели, которые принимают аудио и возвращают текст.</p></div></div>
      <div className="video-catalog-meta"><span className="state ok">{models.length} моделей</span></div>
    </div>
    <div className="matrix-wrap">
      {models.length ? <table className="api-table">
        <thead><tr><th>Модель</th><th>Вход / 1M</th><th>Выход / 1M</th><th>Контекст</th><th>Пример 1000 + 250</th><th>Маршрут</th></tr></thead>
        <tbody>{models.map((model) => {
          const sampleUsd = model.inputPerMillionUsd / 1000 + model.outputPerMillionUsd / 4000
          const sampleRub = usdRub === null ? null : sampleUsd * usdRub
          const selected = selectedModel === model.id
          return <tr key={model.id}>
            <td><strong>{model.name}</strong><small className="model-id">{model.id}</small></td>
            <td>${model.inputPerMillionUsd.toFixed(4)}</td><td>${model.outputPerMillionUsd.toFixed(4)}</td>
            <td>{model.contextLength.toLocaleString('ru-RU')}</td>
            <td><strong>${sampleUsd.toFixed(6)}</strong><small>{sampleRub === null ? 'курс не загружен' : `${sampleRub.toFixed(4)} ₽ себестоимость`}</small></td>
            <td><span className={`state ${selected ? 'ok' : ''}`}>{selected ? 'выбрана для голоса' : 'доступна'}</span></td>
          </tr>
        })}</tbody>
      </table> : <p className="hint">{error ? `Каталог временно недоступен: ${error}` : 'OpenRouter не вернул моделей с аудиовходом и текстовым ответом.'}</p>}
    </div>
  </article>
}

export function OpenRouterThreeDPage() {
  return <article className="card">
    <div className="card-head"><div><h2 className="card-title">Каталог 3D-моделей</h2><p className="card-note">Страница выделена заранее, но в текущем проверенном каталоге OpenRouter нет подключённого контракта генерации 3D.</p></div><span className="state warn">ожидает интеграции</span></div>
    <div className="dependency-note">
      <div><strong>Модели не выдумываются</strong><span>Включение появится только после стабильного API-контракта, цен и форматов результата.</span></div>
      <div><strong>Экономика обязательна</strong><span>До включения нужны себестоимость, цена токена, маржа, лимиты тарифа и живой контрактный тест.</span></div>
    </div>
  </article>
}
