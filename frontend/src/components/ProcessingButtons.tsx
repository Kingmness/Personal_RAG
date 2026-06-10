import React, { useState } from 'react'
import { apiClient } from '../api/client'
import { logger } from '../utils/logger'

interface ProcessingButtonsProps {
  onProcessingComplete: () => void
}

export const ProcessingButtons: React.FC<ProcessingButtonsProps> = ({ onProcessingComplete }) => {
  const [loading, setLoading] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const handleAction = async (action: string) => {
    setLoading(action)
    setMessage(null)
    logger.info('批量操作', { action })
    try {
      const data = await apiClient.batchAction(action as 'parse' | 'chunk' | 'index' | 'metadata')
      setMessage(data.message || '操作完成')
      logger.info('批量操作完成', { action, message: data.message })
      onProcessingComplete()
    } catch (err: any) {
      logger.error('批量操作失败', { action, error: err.message })
      setMessage(err.message || '操作失败，请检查后端服务是否正常运行')
    } finally {
      setLoading(null)
    }
  }

  const buttons = [
    { action: 'parse', label: '解析文档', icon: '📖', color: 'blue' },
    { action: 'chunk', label: '文本分块', icon: '✂️', color: 'green' },
    { action: 'index', label: '建立索引', icon: '🔍', color: 'purple' },
    { action: 'metadata', label: '注册元信息', icon: '📋', color: 'orange' }
  ]

  return (
    <div className="glass-panel rounded-2xl p-8">
      <div className="flex items-center gap-2 mb-6">
        <span className="text-tertiary text-2xl">✨</span>
        <h2 className="font-headline-lg text-headline-lg text-on-surface">整体文档处理</h2>
      </div>
      {message && (
        <div className={`mb-6 p-4 rounded-xl ${message.includes('失败') ? 'bg-error/10 text-error border border-error/20' : 'bg-tertiary/10 text-tertiary border border-tertiary/20'}`}>
          {message}
        </div>
      )}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {buttons.map(({ action, label, icon }) => (
          <button
            key={action}
            onClick={() => handleAction(action)}
            disabled={loading !== null}
            className="group flex flex-col items-center gap-3 p-6 rounded-xl bg-surface-container-low border border-white/5 hover:border-primary/30 transition-all active:scale-95 disabled:opacity-50"
          >
            <span className="text-3xl group-hover:scale-110 transition-transform">{icon}</span>
            <span className="font-body-md font-semibold text-on-surface">
              {loading === action ? `${label}中...` : label}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
