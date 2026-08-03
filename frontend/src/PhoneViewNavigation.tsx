import { Image as ImageIcon, Images, Newspaper, UserRound, Video } from 'lucide-react'

type PhoneViewNavigationProps = {
  imageActive: boolean
  videoActive: boolean
  profileActive: boolean
  onImage: () => void
  onVideo: () => void
  onFeed: () => void
  onGallery: () => void
  onProfile: () => void
}

export default function PhoneViewNavigation(props: PhoneViewNavigationProps) {
  const items = [
    { label: 'Картинка', active: props.imageActive, icon: ImageIcon, action: props.onImage },
    { label: 'Видео', active: props.videoActive, icon: Video, action: props.onVideo },
    { label: 'Лента', active: false, icon: Newspaper, action: props.onFeed },
    { label: 'Галерея', active: false, icon: Images, action: props.onGallery },
    { label: 'Профиль', active: props.profileActive, icon: UserRound, action: props.onProfile },
  ]

  return (
    <nav className="phone-v32-nav" aria-label="Телефонная навигация">
      {items.map(({ label, active, icon: Icon, action }) => (
        <button key={label} type="button" className={active ? 'active' : ''} onClick={action}>
          <Icon aria-hidden="true" /><span>{label}</span>
        </button>
      ))}
    </nav>
  )
}
