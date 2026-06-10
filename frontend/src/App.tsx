import React, { useState, useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { QueryPanel } from './components/QueryPanel'
import { ResultList } from './components/ResultList'
import { Documents } from './pages/Documents'
import { History } from './pages/History'
import { Settings } from './pages/Settings'
import { apiClient } from './api/client'
import { Chunk, AnswerResponse } from './types'
import { logger, getTraceId } from './utils/logger'

const queryClient = new QueryClient()

export interface StepInfo {
    step: number
    name: string
    status: 'start' | 'done'
    elapsed?: number
    count?: number
    contextLen?: number
}

function App() {
    const [view, setView] = useState<'qa' | 'docs' | 'history' | 'settings'>('qa')
    const [question, setQuestion] = useState('2024年的营收是多少？')
    const [answerType, setAnswerType] = useState<'number' | 'name' | 'boolean' | 'list' | 'text'>('number')
    const [useRerank, setUseRerank] = useState(true)
    const [topN, setTopN] = useState(5)
    const [loading, setLoading] = useState(false)
    const [chunks, setChunks] = useState<Chunk[]>([])
    const [answer, setAnswer] = useState<AnswerResponse | null>(null)
    const [elapsed, setElapsed] = useState(0)
    const [docCount, setDocCount] = useState(0)
    const [streamingText, setStreamingText] = useState('')
    const [steps, setSteps] = useState<StepInfo[]>([])
    const [pendingHistory, setPendingHistory] = useState<{
        question: string
        answerType: string
        sources: string[]
        elapsed: number
    } | null>(null)
    const [backendOnline, setBackendOnline] = useState<boolean | null>(null)

    // 获取文档总数
    const fetchDocCount = async () => {
        try {
            const docs = await apiClient.getDocuments()
            const count = docs.length
            setDocCount(count)
            // 确保 topN 不超过文档总数
            if (topN > count && count > 0) {
                setTopN(count)
            }
        } catch (err) {
            console.error('获取文档数量失败:', err)
        }
    }

    useEffect(() => {
        fetchDocCount()
    }, [view])

    // 定时检测后端服务状态
    useEffect(() => {
        const checkHealth = async () => {
            try {
                const res = await fetch('/health')
                const data = await res.json()
                setBackendOnline(data.status === 'ok')
            } catch {
                setBackendOnline(false)
            }
        }
        checkHealth()
        const timer = setInterval(checkHealth, 10000)
        return () => clearInterval(timer)
    }, [])

    const handleSearch = async () => {
        if (!question.trim()) return
        setLoading(true)
        logger.info('用户发起搜索', { question, topN })
        try {
            const result = await queryClient.fetchQuery({
                queryKey: ['search', question, topN],
                queryFn: () => apiClient.retrieve(question, '', topN)
            })
            setChunks(result.chunks)
            setElapsed(result.elapsed)
            setAnswer(null)
            logger.info('搜索完成', { trace_id: getTraceId(), chunkCount: result.chunks.length, elapsed: result.elapsed })
        } catch (err) {
            logger.error('搜索失败', { question, error: String(err) })
        } finally {
            setLoading(false)
        }
    }

    const handleAnswer = async () => {
        if (!question.trim()) return
        setLoading(true)
        setAnswer(null)
        setStreamingText('')
        setSteps([])
        setElapsed(0)
        setPendingHistory(null)
        logger.info('用户发起问答', { question, answerType, useRerank, topN })

        let savedAnswer: any = null
        let savedStreamingText = ''

        try {
            await apiClient.answerStream(
                {
                    question,
                    type: answerType,
                    company: '',
                    use_rerank: useRerank,
                    top_n: topN
                },
                (event) => {
                    if (event.type === 'step') {
                        setSteps(prev => {
                            const existing = prev.findIndex(s => s.step === event.step)
                            if (existing >= 0) {
                                const updated = [...prev]
                                updated[existing] = {
                                    step: event.step,
                                    name: event.name,
                                    status: event.status,
                                    elapsed: event.elapsed,
                                    count: event.count,
                                    contextLen: event.context_len,
                                }
                                return updated
                            }
                            return [...prev, {
                                step: event.step,
                                name: event.name,
                                status: event.status,
                                elapsed: event.elapsed,
                                count: event.count,
                                contextLen: event.context_len,
                            }]
                        })
                    } else if (event.type === 'token') {
                        savedStreamingText += event.content
                        setStreamingText(savedStreamingText)
                    } else if (event.type === 'result') {
                        const data = event.data
                        const sources = [...new Set((data.context_docs || []).map((d: any): string => d.source))]
                        const elapsed = data.elapsed || 0
                        savedAnswer = {
                            answer: String(data.final_answer || ''),
                            pages: data.relevant_pages || [],
                            sources: sources,
                            chunks: (data.context_docs || []).map((d: any) => ({
                                source: d.source,
                                page: d.page,
                                text: d.text,
                                score: d.score,
                                relevance_score: d.relevance_score,
                                reasoning: d.reasoning,
                                combined_score: d.combined_score,
                            })),
                            elapsed: elapsed,
                        }
                        setAnswer(savedAnswer)
                        setChunks(savedAnswer.chunks)
                        setElapsed(elapsed)
                        logger.info('问答完成', { trace_id: getTraceId(), elapsed, sourceCount: sources.length })
                    } else if (event.type === 'error') {
                        logger.error('流式错误', { trace_id: getTraceId(), message: event.message })
                        setStreamingText(event.message || '问答服务暂时不可用')
                        setLoading(false)
                    }
                }
            )

            // 保存历史记录 - 优先使用 answer，否则用 streamingText
            const historyAnswer = savedAnswer?.answer || savedStreamingText
            if (historyAnswer) {
                try {
                    await apiClient.saveHistory({
                        question,
                        answer_type: answerType,
                        answer: historyAnswer,
                        sources: savedAnswer?.sources || [],
                        elapsed: savedAnswer?.elapsed || 0
                    })
                } catch (err) {
                    logger.error('保存历史记录失败', { error: String(err) })
                }
            }
        } catch (err) {
            logger.error('生成答案失败', { question, error: String(err) })
        } finally {
            setLoading(false)
        }
    }

    const handleReuseQuestion = (reuseQuestion: string, reuseAnswerType: string) => {
        setQuestion(reuseQuestion)
        setAnswerType(reuseAnswerType as any)
        setView('qa')
    }

    return (
        <QueryClientProvider client={queryClient}>
            <div className="min-h-screen bg-background font-body-md text-body-md selection:bg-primary/30">
                {/* 背景装饰 */}
                <div className="fixed bottom-0 right-0 w-[500px] h-[500px] bg-primary/5 rounded-full blur-[120px] -z-10 pointer-events-none"></div>
                <div className="fixed top-20 right-40 w-[300px] h-[300px] bg-secondary/5 rounded-full blur-[100px] -z-10 pointer-events-none"></div>

                {/* 侧边栏 */}
                <aside className="bg-surface-container/50 dark:bg-surface-container/50 h-screen w-64 fixed left-0 top-0 backdrop-blur-xl border-r border-white/10 shadow-2xl flex flex-col h-full py-margin-desktop z-50">
                    <div className="px-6 mb-10">
                        <h1 className="font-headline-md text-headline-md text-primary tracking-tight font-bold">智汇空间</h1>
                        <p className="text-on-surface-variant font-label-md text-label-md opacity-60">Silent Intelligence</p>
                    </div>
                    <nav className="flex-1 space-y-1 px-3">
                        <button
                            onClick={() => setView('qa')}
                            className={`w-full text-left flex items-center px-4 py-3 rounded-xl transition-all duration-300 ease-in-out active:scale-95 ${
                                view === 'qa'
                                    ? 'text-primary bg-primary/10 border-r-2 border-primary active-tab-glow'
                                    : 'text-on-surface-variant hover:text-on-surface hover:bg-white/5'
                            }`}
                        >
                            <span className="mr-3">📚</span>
                            <span className="font-label-md text-label-md">智能问答</span>
                        </button>
                        <button
                            onClick={() => setView('docs')}
                            className={`w-full text-left flex items-center px-4 py-3 rounded-xl transition-all duration-300 ease-in-out active:scale-95 ${
                                view === 'docs'
                                    ? 'text-primary bg-primary/10 border-r-2 border-primary active-tab-glow'
                                    : 'text-on-surface-variant hover:text-on-surface hover:bg-white/5'
                            }`}
                        >
                            <span className="mr-3">📄</span>
                            <span className="font-label-md text-label-md">文档管理</span>
                        </button>
                        <button
                            onClick={() => setView('history')}
                            className={`w-full text-left flex items-center px-4 py-3 rounded-xl transition-all duration-300 ease-in-out active:scale-95 ${
                                view === 'history'
                                    ? 'text-primary bg-primary/10 border-r-2 border-primary active-tab-glow'
                                    : 'text-on-surface-variant hover:text-on-surface hover:bg-white/5'
                            }`}
                        >
                            <span className="mr-3">📋</span>
                            <span className="font-label-md text-label-md">查询历史</span>
                        </button>
                        <button
                            onClick={() => setView('settings')}
                            className={`w-full text-left flex items-center px-4 py-3 rounded-xl transition-all duration-300 ease-in-out active:scale-95 ${
                                view === 'settings'
                                    ? 'text-primary bg-primary/10 border-r-2 border-primary active-tab-glow'
                                    : 'text-on-surface-variant hover:text-on-surface hover:bg-white/5'
                            }`}
                        >
                            <span className="mr-3">⚙️</span>
                            <span className="font-label-md text-label-md">系统设置</span>
                        </button>
                    </nav>
                    {/* 服务状态指示器 */}
                    <div className="px-4 pt-4 border-t border-white/10 mt-4">
                        <div className="flex items-center gap-3 px-3 py-2.5 rounded-xl bg-surface/30">
                            <span className={`inline-block w-2.5 h-2.5 rounded-full ${
                                backendOnline === null
                                    ? 'bg-gray-400 animate-pulse'
                                    : backendOnline
                                        ? 'bg-green-400 shadow-[0_0_6px_rgba(74,222,128,0.6)]'
                                        : 'bg-red-400 shadow-[0_0_6px_rgba(248,113,113,0.6)] animate-pulse'
                            }`}></span>
                            <div className="flex-1 min-w-0">
                                <p className="text-xs text-on-surface-variant truncate">
                                    {backendOnline === null
                                        ? '检测中...'
                                        : backendOnline
                                            ? '后端服务在线'
                                            : '后端服务离线'
                                    }
                                </p>
                                <p className="text-[10px] text-on-surface-variant/50">
                                    {backendOnline ? '端口 :4000' : '请检查服务是否启动'}
                                </p>
                            </div>
                        </div>
                    </div>
                </aside>

                {/* 顶部导航栏 */}
                <header className="fixed top-0 right-0 w-[calc(100%-256px)] backdrop-blur-md bg-surface/30 flex justify-between items-center px-gutter h-16 ml-64 z-40 border-b border-white/5">
                    <div className="flex items-center gap-4">
                        <div className="font-headline-md text-headline-md font-bold text-on-surface">
                            {view === 'qa' ? '知识检索系统' : view === 'docs' ? '文档管理系统' : view === 'history' ? '查询历史' : '系统设置'}
                        </div>
                        <div className="h-4 w-px bg-white/10 mx-2"></div>
                        <div
                            className="px-4 py-1.5 rounded-lg font-label-md text-label-md text-primary border-b-2 border-primary cursor-default"
                            title="当前选中页面（跟随左侧菜单）"
                        >
                            {view === 'qa' ? '检索工作区' : view === 'docs' ? '文档管理' : view === 'history' ? '查询历史' : '系统设置'}
                        </div>
                    </div>
                </header>

                {/* 主内容区 */}
                <main className="ml-64 pt-16 flex h-screen overflow-hidden">
                    {view === 'qa' ? (
                        <>
                            {/* 左侧查询面板 */}
                            <section className="w-96 glass-panel border-r border-white/5 p-8 flex flex-col gap-8 custom-scrollbar overflow-y-auto">
                                <div className="flex items-center gap-3">
                                    <span className="text-2xl">📚</span>
                                    <h2 className="font-headline-md text-headline-md">查询设置</h2>
                                </div>
                                <QueryPanel
                                    onSearch={handleSearch}
                                    onAnswer={handleAnswer}
                                    question={question}
                                    setQuestion={setQuestion}
                                    answerType={answerType}
                                    setAnswerType={setAnswerType}
                                    useRerank={useRerank}
                                    setUseRerank={setUseRerank}
                                    topN={topN}
                                    setTopN={setTopN}
                                    maxTopN={docCount > 0 ? docCount : 10}
                                    loading={loading}
                                />
                            </section>

                            {/* 右侧结果区 */}
                            <section className="flex-1 bg-background p-margin-desktop overflow-y-auto custom-scrollbar">
                                <div className="max-w-max-width-content mx-auto">
                                    <ResultList
                                        chunks={chunks}
                                        answer={answer}
                                        elapsed={elapsed}
                                        question={question}
                                        loading={loading}
                                        streamingText={streamingText}
                                        steps={steps}
                                    />
                                </div>
                            </section>
                        </>
                    ) : view === 'docs' ? (
                        <section className="flex-1 bg-background p-margin-desktop overflow-y-auto custom-scrollbar">
                            <div className="max-w-[1000px] mx-auto">
                                <Documents onDocumentChange={fetchDocCount} />
                            </div>
                        </section>
                    ) : view === 'history' ? (
                        <section className="flex-1 bg-background overflow-y-auto custom-scrollbar">
                            <History onReuseQuestion={handleReuseQuestion} />
                        </section>
                    ) : (
                        <section className="flex-1 bg-background p-margin-desktop overflow-y-auto custom-scrollbar">
                            <div className="max-w-[800px] mx-auto">
                                <Settings />
                            </div>
                        </section>
                    )}
                </main>
            </div>
        </QueryClientProvider>
    )
}

export default App
