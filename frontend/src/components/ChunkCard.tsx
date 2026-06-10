import React, { useState } from 'react'
import { Chunk } from '../types'

interface ChunkCardProps {
  chunk: Chunk
  index: number
}

export const ChunkCard: React.FC<ChunkCardProps> = ({ chunk }) => {
  const [expanded, setExpanded] = useState(false)
  const [showDetails, setShowDetails] = useState(false)

  if (!chunk) {
    return null
  }

  const previewText = (chunk.text || '').length > 300 ? (chunk.text || '').slice(0, 300) + '...' : (chunk.text || '')

  return (
    <div className="glass-panel p-6 rounded-2xl mb-4 group cursor-pointer hover:border-primary/40 transition-all border-white/5">
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-3">
          <div className="px-3 py-1 bg-primary/10 rounded-md border border-primary/20 text-primary font-code-sm text-xs">
            Score: {chunk.combined_score ? chunk.combined_score.toFixed(2) : chunk.score ? chunk.score.toFixed(2) : 'N/A'}
          </div>
          <h3 className="font-label-md text-label-md font-bold text-on-surface">
            {(chunk.source || 'Unknown').replace('.pdf', '')}
          </h3>
        </div>
        <button
          onClick={() => setShowDetails(!showDetails)}
          className="text-on-surface-variant group-hover:text-primary transition-colors font-label-md text-xs"
        >
          {showDetails ? '▼' : '▶'} 详情
        </button>
      </div>

      {showDetails && (
        <div className="mb-4 p-4 bg-surface-container-low rounded-xl border border-white/5">
          <div className="grid grid-cols-3 gap-4 mb-3">
            <div>
              <span className="text-on-surface-variant text-xs font-label-md">检索分:</span>
              <span className="ml-1 text-primary font-semibold text-sm font-code-sm">
                {chunk.score ? chunk.score.toFixed(4) : 'N/A'}
              </span>
            </div>
            <div>
              <span className="text-on-surface-variant text-xs font-label-md">LLM相关分:</span>
              <span className="ml-1 text-secondary font-semibold text-sm font-code-sm">
                {chunk.relevance_score !== undefined ? chunk.relevance_score.toFixed(2) : 'N/A'}
              </span>
            </div>
            <div>
              <span className="text-on-surface-variant text-xs font-label-md">融合分:</span>
              <span className="ml-1 text-tertiary font-semibold text-sm font-code-sm">
                {chunk.combined_score !== undefined ? chunk.combined_score.toFixed(4) : 'N/A'}
              </span>
            </div>
          </div>
          {chunk.reasoning && (
            <div className="mt-2">
              <span className="text-on-surface-variant text-xs font-label-md">评分理由:</span>
              <p className="text-on-surface text-sm mt-1 leading-relaxed font-body-md">{chunk.reasoning}</p>
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 mb-4 text-sm">
        <div>
          <span className="text-on-surface-variant font-label-md text-xs">页码:</span>
          <span className="ml-1 text-on-surface font-medium font-body-md">第 {chunk.page || 'N/A'} 页</span>
        </div>
        <div>
          <span className="text-on-surface-variant font-label-md text-xs">来源:</span>
          <span className="ml-1 text-on-surface font-medium font-body-md">{(chunk.source || 'N/A').replace('.pdf', '')}</span>
        </div>
      </div>

      <div className="text-on-surface leading-relaxed whitespace-pre-wrap font-body-md">
        {expanded ? (chunk.text || '') : previewText}
      </div>

      {(chunk.text || '').length > 300 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-4 text-primary text-sm hover:underline font-medium font-label-md"
        >
          {expanded ? '收起' : '展开全部'}
        </button>
      )}
    </div>
  )
}
