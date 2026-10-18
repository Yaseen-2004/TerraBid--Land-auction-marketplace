import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';

const ToastContext = createContext(null);

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id) => setToasts((list) => list.filter((t) => t.id !== id)), []);

  const push = useCallback(
    (toast) => {
      const id = nextId.current++;
      setToasts((list) => [...list.slice(-4), { type: 'info', ...toast, id }]);
      setTimeout(() => dismiss(id), toast.duration ?? 4500);
    },
    [dismiss],
  );

  const value = useMemo(
    () => ({
      push,
      success: (message, title) => push({ type: 'success', message, title }),
      error: (message, title) => push({ type: 'error', message, title }),
      info: (message, title) => push({ type: 'info', message, title }),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.type}`} onClick={() => dismiss(t.id)}>
            {t.title && <strong>{t.title}</strong>}
            <span>{t.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
