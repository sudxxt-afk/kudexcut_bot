import { StrictMode, useEffect, useMemo, useState } from 'react';
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
  close: () => void;
};

declare global {
  interface Window {
    Telegram?: { WebApp: TelegramWebApp };
  }
}

function formatTime(seconds: number): string {
  const safeSeconds = Math.max(0, seconds);
  const minutes = Math.floor(safeSeconds / 60);
  const remainder = (safeSeconds % 60).toFixed(1).padStart(4, '0');
  return `${String(minutes).padStart(2, '0')}:${remainder}`;
}

function App() {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const sessionId = params.get('session');
  const [session, setSession] = useState<Session | null>(null);
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    window.Telegram?.WebApp.ready();
    if (!sessionId) {
      setError('Сессия редактора не найдена. Отправь видео боту заново.');
      setLoading(false);
      return;
    }

    const initData = window.Telegram?.WebApp.initData ?? '';
    fetch(`/api/sessions/${sessionId}`, {
      headers: { 'X-Telegram-Init-Data': initData },
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error((await response.json()).detail ?? 'Не удалось открыть видео');
        }
        return response.json() as Promise<Session>;
      })
      .then((data) => {
        setSession(data);
        setEnd(data.duration_seconds);
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [sessionId]);

  async function submitTrim() {
    if (!session || !sessionId) return;
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
      if (!response.ok) {
        throw new Error((await response.json()).detail ?? 'Не удалось отправить задачу');
      }
      setError('Диапазон принят. Обработка будет добавлена следующим этапом.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Произошла ошибка');
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <main className="state">Загружаю видео…</main>;
  if (error && !session) return <main className="state error">{error}</main>;
  if (!session) return <main className="state error">Сессия недоступна.</main>;

  return (
    <main className="editor">
      <header><h1>Обрезка видео</h1><span>{session.width}×{session.height}</span></header>
      <video className="preview" controls src={session.video_url} />
      <section className="range-card">
        <div className="timeline-labels"><span>{formatTime(start)}</span><span>{formatTime(end)}</span></div>
        <input aria-label="Начало фрагмента" type="range" min={0} max={session.duration_seconds} step={0.1} value={start} onChange={(event) => setStart(Math.min(Number(event.target.value), end - 0.1))} />
        <input aria-label="Конец фрагмента" type="range" min={0} max={session.duration_seconds} step={0.1} value={end} onChange={(event) => setEnd(Math.max(Number(event.target.value), start + 0.1))} />
        <div className="fields"><label>Начало<input type="number" min={0} max={end - 0.1} step={0.1} value={start} onChange={(event) => setStart(Number(event.target.value))} /></label><label>Конец<input type="number" min={start + 0.1} max={session.duration_seconds} step={0.1} value={end} onChange={(event) => setEnd(Number(event.target.value))} /></label></div>
      </section>
      <button className="primary" disabled={submitting || end <= start} onClick={submitTrim}>{submitting ? 'Отправляю…' : 'Готово'}</button>
      {error && <p className="notice">{error}</p>}
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
