import { StrictMode, useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

type Session = {
  session_id: string;
  file_name: string;
  mime_type: string;
  file_size: number;
  duration_seconds: number;
  width: number;
  height: number;
  status: string;
  video_url: string;
};

type TelegramWebApp = {
  initData: string;
  ready: () => void;
  expand?: () => void;
  close: () => void;
};

declare global {
  interface Window {
    Telegram?: { WebApp: TelegramWebApp };
  }
}

const MIN_CLIP_DURATION = 0.1;
const THUMBNAIL_COUNT = 9;

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function formatTime(seconds: number): string {
  const safeSeconds = Math.max(0, seconds);
  const minutes = Math.floor(safeSeconds / 60);
  const remainder = (safeSeconds % 60).toFixed(1).padStart(4, '0');
  return `${String(minutes).padStart(2, '0')}:${remainder}`;
}

function normalizeTime(value: number): number {
  return Math.round(value * 10) / 10;
}

function App() {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const sessionId = params.get('session');
  const videoRef = useRef<HTMLVideoElement>(null);
  const timelineRef = useRef<HTMLDivElement>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [thumbnails, setThumbnails] = useState<string[]>([]);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [previewSelection, setPreviewSelection] = useState(false);
  const [dragging, setDragging] = useState<'start' | 'end' | 'playhead' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [processingStatus, setProcessingStatus] = useState<string | null>(null);

  useEffect(() => {
    window.Telegram?.WebApp.ready();
    window.Telegram?.WebApp.expand?.();
    if (!sessionId) {
      setError('Сессия редактора не найдена. Отправь видео боту заново.');
      setLoading(false);
      return;
    }

    const initData = window.Telegram?.WebApp.initData ?? '';
    if (!initData) {
      setError('Открой редактор через Telegram.');
      setLoading(false);
      return;
    }

    let cancelled = false;
    fetch(`/api/sessions/${sessionId}`, { headers: { 'X-Telegram-Init-Data': initData } })
      .then(async (response) => {
        if (!response.ok) throw new Error((await response.json()).detail ?? 'Не удалось открыть видео');
        return response.json() as Promise<Session>;
      })
      .then(async (data) => {
        const videoResponse = await fetch(data.video_url, {
          headers: { 'X-Telegram-Init-Data': initData },
        });
        if (!videoResponse.ok) throw new Error('Не удалось загрузить видео');
        const videoBlob = await videoResponse.blob();
        if (cancelled) return;
        setSession(data);
        setDuration(data.duration_seconds);
        setStart(0);
        setEnd(data.duration_seconds);
        setVideoUrl(URL.createObjectURL(videoBlob));
      })
      .catch((reason: Error) => {
        if (!cancelled) setError(reason.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      setVideoUrl((currentUrl) => {
        if (currentUrl) URL.revokeObjectURL(currentUrl);
        return null;
      });
      thumbnails.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [sessionId]);

  useEffect(() => {
    if (!videoUrl || !duration) return;
    let cancelled = false;
    const source = document.createElement('video');
    source.src = videoUrl;
    source.muted = true;
    source.preload = 'auto';
    const canvas = document.createElement('canvas');
    canvas.width = 180;
    canvas.height = 110;
    const context = canvas.getContext('2d');
    if (!context) return;

    const createStrip = async () => {
      await new Promise<void>((resolve) => {
        source.addEventListener('loadeddata', () => resolve(), { once: true });
        source.load();
      });
      const urls: string[] = [];
      for (let index = 0; index < THUMBNAIL_COUNT && !cancelled; index += 1) {
        source.currentTime = (duration * index) / Math.max(THUMBNAIL_COUNT - 1, 1);
        await new Promise<void>((resolve) => {
          source.addEventListener('seeked', () => resolve(), { once: true });
        });
        context.drawImage(source, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.7));
        if (blob) urls.push(URL.createObjectURL(blob));
      }
      if (!cancelled) setThumbnails(urls);
      else urls.forEach((url) => URL.revokeObjectURL(url));
    };
    void createStrip();
    return () => {
      cancelled = true;
      source.pause();
      setThumbnails((current) => {
        current.forEach((url) => URL.revokeObjectURL(url));
        return [];
      });
    };
  }, [duration, videoUrl]);

  useEffect(() => {
    if (!sessionId || !processingStatus || ['completed', 'failed'].includes(processingStatus)) return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`/api/sessions/${sessionId}/status`, {
          headers: { 'X-Telegram-Init-Data': window.Telegram?.WebApp.initData ?? '' },
        });
        if (!response.ok) throw new Error('Не удалось получить статус обработки');
        const data = await response.json() as { status: string };
        if (cancelled) return;
        setProcessingStatus(data.status);
        if (data.status === 'completed') setError('Готово. Видео отправлено в Telegram.');
        if (data.status === 'failed') setError('Не удалось обработать видео. Попробуй ещё раз.');
      } catch (reason) {
        if (!cancelled) {
          setProcessingStatus('failed');
          setError(reason instanceof Error ? reason.message : 'Не удалось получить статус обработки');
        }
      }
    }, 1500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [processingStatus, sessionId]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const onTimeUpdate = () => {
      setCurrentTime(video.currentTime);
      if (previewSelection && video.currentTime >= end - 0.03) {
        video.pause();
        video.currentTime = end;
        setPreviewSelection(false);
      }
    };
    const onLoadedMetadata = () => {
      const actualDuration = Number.isFinite(video.duration) ? video.duration : duration;
      setDuration(actualDuration);
      setEnd((value) => Math.min(value || actualDuration, actualDuration));
    };
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    video.addEventListener('timeupdate', onTimeUpdate);
    video.addEventListener('loadedmetadata', onLoadedMetadata);
    video.addEventListener('play', onPlay);
    video.addEventListener('pause', onPause);
    return () => {
      video.removeEventListener('timeupdate', onTimeUpdate);
      video.removeEventListener('loadedmetadata', onLoadedMetadata);
      video.removeEventListener('play', onPlay);
      video.removeEventListener('pause', onPause);
    };
  }, [duration, end, previewSelection]);

  function timeFromPointer(clientX: number): number {
    const rect = timelineRef.current?.getBoundingClientRect();
    if (!rect || !duration) return 0;
    return normalizeTime(clamp(((clientX - rect.left) / rect.width) * duration, 0, duration));
  }

  function updateFromPointer(clientX: number) {
    const value = timeFromPointer(clientX);
    if (dragging === 'start') setStart(Math.min(value, end - MIN_CLIP_DURATION));
    if (dragging === 'end') setEnd(Math.max(value, start + MIN_CLIP_DURATION));
    if (dragging === 'playhead') seek(value);
  }

  function seek(value: number) {
    const next = clamp(value, 0, duration);
    setCurrentTime(next);
    if (videoRef.current) videoRef.current.currentTime = next;
  }

  function togglePlay() {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) void video.play();
    else video.pause();
  }

  function previewClip() {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = start;
    setCurrentTime(start);
    setPreviewSelection(true);
    void video.play();
  }

  function handleTimelinePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if ((event.target as HTMLElement).dataset.handle) return;
    timelineRef.current?.setPointerCapture(event.pointerId);
    setDragging('playhead');
    updateFromPointer(event.clientX);
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (dragging) updateFromPointer(event.clientX);
  }

  function handlePointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    timelineRef.current?.releasePointerCapture(event.pointerId);
    setDragging(null);
  }

  function setStartValue(value: number) {
    if (!Number.isFinite(value)) return;
    setStart(clamp(normalizeTime(value), 0, Math.max(0, end - MIN_CLIP_DURATION)));
  }

  function setEndValue(value: number) {
    if (!Number.isFinite(value)) return;
    setEnd(clamp(normalizeTime(value), Math.min(duration, start + MIN_CLIP_DURATION), duration));
  }

  async function submitTrim() {
    if (!session || !sessionId || end <= start) return;
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch(`/api/sessions/${sessionId}/trim`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Telegram-Init-Data': window.Telegram?.WebApp.initData ?? '',
        },
        body: JSON.stringify({ start, end }),
      });
      if (!response.ok) throw new Error((await response.json()).detail ?? 'Не удалось отправить задачу');
      const accepted = await response.json() as { status: string };
      setProcessingStatus(accepted.status);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Произошла ошибка');
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <main className="state">Загружаю видео…</main>;
  if (error && !session) return <main className="state error">{error}</main>;
  if (!session) return <main className="state error">Сессия недоступна.</main>;

  const startPercent = duration ? (start / duration) * 100 : 0;
  const endPercent = duration ? (end / duration) * 100 : 100;
  const playheadPercent = duration ? (currentTime / duration) * 100 : 0;
  const selectedDuration = Math.max(0, end - start);

  return (
    <main className="editor-shell">
      <header className="editor-header">
        <button className="icon-button" aria-label="Закрыть редактор" onClick={() => window.Telegram?.WebApp.close()}>×</button>
        <div className="title-block"><strong>Обрезать видео</strong><span>{session.file_name}</span></div>
        <span className="clip-badge">{formatTime(selectedDuration)}</span>
      </header>

      <section className="preview-stage">
        <video ref={videoRef} className="preview" src={videoUrl ?? undefined} playsInline preload="metadata" />
        <button className={`preview-play ${isPlaying ? 'is-playing' : ''}`} aria-label={isPlaying ? 'Пауза' : 'Воспроизвести'} onClick={togglePlay}>
          {isPlaying ? 'Ⅱ' : '▶'}
        </button>
        <div className="preview-time"><b>{formatTime(currentTime)}</b><span>/ {formatTime(duration)}</span></div>
      </section>

      <section className="editor-controls">
        <div className="timeline-toolbar">
          <div><span className="eyebrow">Выберите фрагмент</span><strong>{formatTime(start)} — {formatTime(end)}</strong></div>
          <span className="selected-duration">{formatTime(selectedDuration)}</span>
        </div>
        <div
          ref={timelineRef}
          className={`timeline ${dragging ? 'is-dragging' : ''}`}
          onPointerDown={handleTimelinePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
        >
          <div className="filmstrip">
            {thumbnails.length > 0
              ? thumbnails.map((thumbnail, index) => <img key={thumbnail} src={thumbnail} alt={`Кадр ${index + 1}`} />)
              : Array.from({ length: THUMBNAIL_COUNT }, (_, index) => <span className="thumbnail-placeholder" key={index} />)}
          </div>
          <div className="timeline-dim left" style={{ width: `${startPercent}%` }} />
          <div className="timeline-dim right" style={{ width: `${100 - endPercent}%` }} />
          <div className="selection" style={{ left: `${startPercent}%`, width: `${endPercent - startPercent}%` }} />
          <button className="timeline-handle start-handle" data-handle="start" aria-label="Начало фрагмента" style={{ left: `${startPercent}%` }} onPointerDown={(event) => { event.stopPropagation(); timelineRef.current?.setPointerCapture(event.pointerId); setDragging('start'); }} />
          <button className="timeline-handle end-handle" data-handle="end" aria-label="Конец фрагмента" style={{ left: `${endPercent}%` }} onPointerDown={(event) => { event.stopPropagation(); timelineRef.current?.setPointerCapture(event.pointerId); setDragging('end'); }} />
          <button className="playhead" data-handle="playhead" aria-label="Позиция воспроизведения" style={{ left: `${playheadPercent}%` }} onPointerDown={(event) => { event.stopPropagation(); timelineRef.current?.setPointerCapture(event.pointerId); setDragging('playhead'); }} />
        </div>
        <div className="timeline-scale"><span>00:00</span><span>{formatTime(duration)}</span></div>
      </section>

      <section className="tools-row">
        <button className={`tool-button ${isPlaying && previewSelection ? 'active' : ''}`} onClick={previewClip} aria-label="Предпросмотр выбранного фрагмента">
          <span className="tool-icon">{isPlaying && previewSelection ? '■' : '▶'}</span><span>Просмотр</span>
        </button>
        <label className="time-field"><span>Начало</span><input type="number" min={0} max={end - MIN_CLIP_DURATION} step={0.1} value={start} onChange={(event) => setStartValue(Number(event.target.value))} /></label>
        <label className="time-field"><span>Конец</span><input type="number" min={start + MIN_CLIP_DURATION} max={duration} step={0.1} value={end} onChange={(event) => setEndValue(Number(event.target.value))} /></label>
      </section>

      <div className="bottom-bar">
        <button className="primary" disabled={submitting || processingStatus !== null || end <= start} onClick={submitTrim}>
          {submitting ? 'Отправляю…' : processingStatus ? `Обработка: ${processingStatus}` : 'Готово'}
        </button>
      </div>
      {error && <p className="notice">{error}</p>}
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
