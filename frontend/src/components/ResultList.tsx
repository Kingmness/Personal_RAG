import React from 'react'
import { AnswerResponse, Chunk } from '../types'
import { ChunkCard } from './ChunkCard'
import { StepInfo } from '../App'
import { getTraceId } from '../utils/logger'

interface ResultListProps {
  chunks: Chunk[]
  answer: AnswerResponse | null
  elapsed: number
  question: string
  loading: boolean
  streamingText: string
  steps: StepInfo[]
}

export const ResultList: React.FC<ResultListProps> = ({
  chunks,
  answer,
  elapsed,
  question,
  loading,
  streamingText,
  steps
}) => {
  const isStreaming = loading && streamingText.length > 0

  return (
    <div className="flex-1">
      {/* 标题区域 */}
      <div className="mb-12">
        <h2 className="font-headline-lg text-headline-lg mb-4 text-on-surface flex items-center gap-4">
          LLM 重排序后的检索结果
          <span className="px-3 py-1 rounded-full bg-tertiary/10 text-tertiary text-[10px] font-bold uppercase tracking-tighter border border-tertiary/20">
            Alpha v2.0
          </span>
        </h2>
        <p className="text-on-surface-variant font-body-md opacity-80 leading-relaxed mb-6">
          点击「详情」可查看 LLM 评分理由和各项分数。系统利用深度语言模型对初始检索片段进行二次评估，以确保上下文的相关性和事实准确性。
        </p>
        <div className="flex gap-4 p-4 rounded-2xl bg-surface-container-low/50 border border-white/5">
          <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
            <span className="text-primary">ℹ️</span>
          </div>
          <div>
            <p className="font-label-md text-label-md font-bold mb-1">当前查询</p>
            <p className="text-on-surface-variant text-sm font-label-md">问题：{question}</p>
          </div>
        </div>
      </div>

      {/* 步骤进度条 */}
      {(steps.length > 0 || loading) && (
        <div className="mb-8 p-5 bg-surface-container-low rounded-2xl border border-white/5">
          <h4 className="text-sm font-medium text-on-surface mb-4 font-label-md">执行进度</h4>
          <div className="flex flex-col gap-3">
            {[
              { step: 1, name: '检索' },
              { step: 2, name: '重排序' },
              { step: 3, name: '上下文构建' },
              { step: 4, name: 'LLM生成' },
            ].map(({ step, name }) => {
              const info = steps.find(s => s.step === step)
              const isActive = loading && info?.status === 'start' && !steps.find(s => s.step === step + 1)
              const isDone = info?.status === 'done'

              return (
                <div key={step} className="flex items-center gap-3">
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                    isDone ? 'bg-tertiary text-on-tertiary' :
                    isActive ? 'bg-primary text-on-primary animate-pulse' :
                    'bg-surface-container-highest text-on-surface-variant'
                  }`}>
                    {isDone ? '✓' : step}
                  </div>
                  <span className={`text-sm ${isDone ? 'text-on-surface' : isActive ? 'text-primary font-medium' : 'text-on-surface-variant'}`}>
                    Step{step}: {name}
                  </span>
                  {isDone && info?.elapsed != null && (
                    <span className="text-xs ml-auto font-code-sm text-on-surface-variant">
                      {info.elapsed.toFixed(2)}s
                      {info.count != null && ` | ${info.count}条`}
                      {info.contextLen != null && ` | ${info.contextLen}字符`}
                    </span>
                  )}
                  {isActive && (
                    <span className="text-xs text-primary ml-auto animate-pulse font-label-md">
                      执行中...
                    </span>
                  )}
                </div>
              )
            })}
          </div>
          {/* 总耗时 */}
          {!loading && steps.length > 0 && steps.every(s => s.status === 'done') && (
            <div className="mt-4 pt-4 border-t border-white/10 flex items-center justify-between">
              <span className="text-sm font-medium text-on-surface">总耗时</span>
              <span className="text-sm font-code-sm font-semibold text-primary">
                {steps.reduce((sum, s) => sum + (s.elapsed || 0), 0).toFixed(2)}s
              </span>
            </div>
          )}
        </div>
      )}

      {/* 流式输出区域 */}
      {isStreaming && !answer && (
        <div className="mb-10 p-6 bg-primary/10 rounded-2xl border border-primary/20">
          <h3 className="font-headline-md text-headline-md mb-4 text-on-surface">答案</h3>
          <div className="text-lg text-on-surface whitespace-pre-wrap break-words font-body-lg">
            {streamingText}
            <span className="inline-block w-0.5 h-6 bg-primary animate-pulse ml-0.5 align-text-bottom"></span>
          </div>
        </div>
      )}

      {/* 最终答案 */}
      {!loading && answer && (
        <div className="mb-10 p-6 bg-primary/10 rounded-2xl border border-primary/20">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-headline-md text-headline-md text-on-surface">答案</h3>
            <div className="flex items-center gap-3">
              {getTraceId() !== '-' && (
                <span className="text-xs font-code-sm text-on-surface-variant bg-surface-container-low px-3 py-1 rounded-full border border-white/10 cursor-pointer" title="点击复制 trace_id" onClick={() => { navigator.clipboard.writeText(getTraceId()) }}>
                  trace: {getTraceId()}
                </span>
              )}
              {elapsed > 0 && (
                <span className="text-xs font-code-sm text-primary bg-primary/20 px-4 py-1 rounded-full">
                  总耗时 {elapsed.toFixed(2)}s
                </span>
              )}
            </div>
          </div>
          <p className="text-lg text-on-surface whitespace-pre-wrap font-body-lg">{answer.answer}</p>
          {answer.pages.length > 0 && (
            <div className="mt-4 pt-4 border-t border-primary/20">
              <p className="text-sm text-on-surface-variant font-label-md">
                引用页码: {answer.pages.map(p => `第${p}页`).join(', ')}
              </p>
            </div>
          )}
          {answer.sources.length > 0 && (
            <div className="mt-2">
              <p className="text-sm text-on-surface-variant font-label-md">
                来源文档: {answer.sources.slice(0, 3).map(s => s.replace('.pdf', '')).join('; ')}
                {answer.sources.length > 3 && '...'}
              </p>
            </div>
          )}
        </div>
      )}

      {/* 加载中（无流式输出时显示） */}
      {loading && streamingText.length === 0 && (
        <div className="flex items-center justify-center py-20">
          <div className="relative w-64 h-64 flex items-center justify-center">
            <div className="absolute inset-0 bg-primary/5 rounded-full blur-3xl animate-pulse"></div>
            <div className="glass-panel rounded-3xl rotate-45 flex items-center justify-center border-primary/20 p-8">
              <span className="text-primary text-5xl -rotate-45">🔍</span>
            </div>
            <div className="absolute top-0 right-0 w-12 h-12 glass-panel rounded-full flex items-center justify-center animate-bounce border-secondary/30">
              <span className="text-secondary text-lg">✨</span>
            </div>
          </div>
        </div>
      )}

      {/* 空状态 */}
      {!loading && chunks.length === 0 && !answer && (
        <div className="flex flex-col items-center justify-center py-20 space-y-8">
          <div className="relative w-64 h-64 flex items-center justify-center">
            <div className="absolute inset-0 bg-primary/5 rounded-full blur-3xl animate-pulse"></div>
            <div className="glass-panel rounded-3xl rotate-45 flex items-center justify-center border-primary/20 p-8">
              <span className="text-primary text-5xl -rotate-45">🔍</span>
            </div>
            <div className="absolute top-0 right-0 w-12 h-12 glass-panel rounded-full flex items-center justify-center animate-bounce border-secondary/30">
              <span className="text-secondary text-lg">✨</span>
            </div>
          </div>
          <div className="text-center">
            <p className="font-headline-md text-headline-md text-on-surface mb-2">找到 0 个相关文档片段</p>
            <p className="text-on-surface-variant font-body-md">请尝试调整您的查询设置或增加检索文档数量，以获得更全面的结果。</p>
          </div>
          <div className="flex gap-4">
            <button className="px-8 py-3 rounded-full bg-white/5 hover:bg-white/10 border border-white/10 transition-colors font-label-md text-label-md text-on-surface-variant">
              查看原始文档
            </button>
            <button className="px-8 py-3 rounded-full bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary transition-colors font-label-md text-label-md">
              展开检索范围
            </button>
          </div>
        </div>
      )}

      {/* 检索结果列表 */}
      <div className="space-y-4">
        {chunks.map((chunk, index) => (
          <ChunkCard key={index} chunk={chunk} index={index} />
        ))}
      </div>
    </div>
  )
}
