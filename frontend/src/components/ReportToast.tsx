import { useEffect } from 'react'

interface ReportToastProps {
  message: string
  type: 'success' | 'error'
  onDismiss: () => void
}

export default function ReportToast({ message, type, onDismiss }: ReportToastProps) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, 4000)
    return () => clearTimeout(timer)
  }, [onDismiss])

  const isSuccess = type === 'success'

  return (
    <div
      className={[
        'fixed bottom-6 right-6 z-50 flex items-start gap-3 px-4 py-3 rounded-lg border shadow-lg',
        'max-w-sm text-sm animate-fade-in',
        isSuccess
          ? 'bg-green-950/90 border-green-700 text-green-200'
          : 'bg-red-950/90 border-red-700 text-red-200',
      ].join(' ')}
      role="status"
      aria-live="polite"
    >
      <span className={`text-base leading-none mt-0.5 shrink-0 ${isSuccess ? 'text-green-400' : 'text-red-400'}`}>
        {isSuccess ? '✓' : '✕'}
      </span>
      <span className="flex-1">{message}</span>
      <button
        onClick={onDismiss}
        aria-label="Fechar notificação"
        className={`shrink-0 ml-1 leading-none opacity-60 hover:opacity-100 transition-opacity ${isSuccess ? 'text-green-300' : 'text-red-300'}`}
      >
        ✕
      </button>
    </div>
  )
}
