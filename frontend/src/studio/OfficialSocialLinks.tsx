const OFFICIAL_SOCIALS = [
  { label: 'Telegram', href: 'https://t.me/izo_asa_bot' },
  { label: 'MAX', href: 'https://max.ru/id231408577954_4_bot' },
  { label: 'ВКонтакте', href: 'https://vk.com/club240405661' },
] as const

export default function OfficialSocialLinks() {
  return (
    <section className="n2-help-section" id="help-social">
      <h3>Официальные соцсети ИЗО АСА</h3>
      <p>Новости сервиса, новые возможности и опубликованные работы доступны на наших официальных площадках.</p>
      <div className="n2-help-links" aria-label="Официальные соцсети ИЗО АСА">
        {OFFICIAL_SOCIALS.map((social) => <a key={social.href} href={social.href} target="_blank" rel="noreferrer">{social.label}</a>)}
      </div>
    </section>
  )
}
