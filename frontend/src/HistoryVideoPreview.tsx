import { Film } from 'lucide-react'
import type { ReactElement } from 'react'

type HistoryVideoPreviewProps = {
  id: string
  src: string
  prompt: string
  onOpenVideo: () => void
}

export default function HistoryVideoPreview({
  id,
  src,
  prompt,
  onOpenVideo,
}: HistoryVideoPreviewProps): ReactElement {
  return <div className="iv3-history-video-preview">
    <video
      key={id}
      src={src}
      controls
      playsInline
      preload="metadata"
      autoPlay
      aria-label={prompt || 'Видео из истории'}
    />
    <div className="iv3-history-video-caption">
      <span>Видео из истории</span>
      <p>Ролик можно посмотреть здесь. Использовать видео как исходное изображение нельзя.</p>
      <button type="button" onClick={onOpenVideo}><Film aria-hidden="true" />Открыть во вкладке «Видео»</button>
    </div>
  </div>
}
