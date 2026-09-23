import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

function App() {
  return <main><h1>VideoCut</h1><p>Редактор скоро будет доступен.</p></main>;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode><App /></StrictMode>,
);
