import React from 'react'

interface QueryPanelProps {
  onSearch: () => void
  onAnswer: () => void
  question: string
  setQuestion: (q: string) => void
  answerType: 'number' | 'name' | 'boolean' | 'list' | 'text'
  setAnswerType: (t: 'number' | 'name' | 'boolean' | 'list' | 'text') => void
  useRerank: boolean
  setUseRerank: (v: boolean) => void
  topN: number
  setTopN: (n: number) => void
  maxTopN: number
  loading: boolean
}

export const QueryPanel: React.FC<QueryPanelProps> = ({
  onSearch,
  onAnswer,
  question,
  setQuestion,
  answerType,
  setAnswerType,
  useRerank,
  setUseRerank,
  topN,
  setTopN,
  maxTopN,
  loading
}) => {
  return (
    <div className="flex-1 flex flex-col gap-8">
      {/* 问题输入 */}
      <div className="space-y-4">
        <div className="flex items-center gap-2 text-primary">
          <span>❓</span>
          <label className="font-label-md text-label-md font-semibold">输入问题</label>
        </div>
        <div className="relative group">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="请输入您想要查询的问题..."
            className="w-full bg-surface-container-lowest border border-white/10 rounded-xl p-4 font-body-md text-body-md focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none transition-all resize-none min-h-[120px] text-on-surface"
          />
          <div className="absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-primary/50 to-transparent opacity-0 group-focus-within:opacity-100 transition-opacity"></div>
        </div>
      </div>

      {/* 问题类型 */}
      <div className="space-y-4">
        <div className="flex items-center gap-2 text-tertiary">
          <span>📝</span>
          <label className="font-label-md text-label-md font-semibold">问题类型</label>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {[
            { value: 'boolean' as const, label: 'boolean' },
            { value: 'number' as const, label: 'number' },
            { value: 'name' as const, label: 'name' },
            { value: 'list' as const, label: 'list' },
            { value: 'text' as const, label: 'text' }
          ].map((type) => (
            <label
              key={type.value}
              className={`flex items-center gap-3 p-3 rounded-xl cursor-pointer transition-all group ${
                answerType === type.value
                  ? 'bg-primary/10 border border-primary/30 active-tab-glow'
                  : 'bg-surface-container-low border border-white/5 hover:bg-surface-container'
              }`}
            >
              <input
                type="radio"
                name="answerType"
                value={type.value}
                checked={answerType === type.value}
                onChange={(e) => setAnswerType(e.target.value as 'number' | 'name' | 'boolean' | 'list' | 'text')}
                className="text-primary"
              />
              <span className={`font-label-md text-label-md ${
                answerType === type.value ? 'text-primary font-bold' : 'text-on-surface-variant group-hover:text-on-surface'
              }`}>
                {type.label}
              </span>
            </label>
          ))}
        </div>
      </div>

      {/* LLM重排序 */}
      <div className="p-5 bg-gradient-to-br from-secondary/10 to-transparent rounded-2xl border border-secondary/20">
        <p className="font-label-md text-label-md mb-4 text-secondary/80">对检索结果进行智能重排序</p>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-6 h-6 bg-secondary rounded-full flex items-center justify-center">
              <span className="text-xs text-on-secondary">✨</span>
            </div>
            <span className="font-label-md text-label-md font-bold text-on-surface">启用LLM重排序</span>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={useRerank}
              onChange={(e) => setUseRerank(e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-surface-container-highest rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-secondary"></div>
          </label>
        </div>
      </div>

      {/* 统计和按钮 */}
      <div className="mt-auto pt-6 border-t border-white/5 flex flex-col gap-4">
        <div className="flex items-center justify-between p-4 bg-surface-container-low rounded-xl border border-white/5">
          <div className="flex flex-col">
            <span className="text-[10px] text-on-surface-variant uppercase tracking-widest">检索文档数</span>
            <span className="font-headline-md text-headline-md text-primary">{topN}</span>
          </div>
          <div className="flex-1 ml-4">
            <input
              type="range"
              min="1"
              max={maxTopN}
              value={topN}
              onChange={(e) => setTopN(parseInt(e.target.value))}
              className="w-full"
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <button
            onClick={onSearch}
            disabled={loading}
            className="flex items-center justify-center gap-2 p-4 rounded-xl border border-primary/30 text-primary hover:bg-primary/5 active:scale-95 transition-all disabled:opacity-50"
          >
            <span>🔍</span>
            <span className="font-label-md text-label-md">搜索文档</span>
          </button>
          <button
            onClick={onAnswer}
            disabled={loading}
            className="flex items-center justify-center gap-2 p-4 rounded-xl bg-gradient-to-r from-primary-container to-secondary-container text-white shadow-lg shadow-primary-container/20 hover:opacity-90 active:scale-95 transition-all disabled:opacity-50"
          >
            <span>🤖</span>
            <span className="font-label-md text-label-md">生成答案</span>
          </button>
        </div>
      </div>
    </div>
  )
}
