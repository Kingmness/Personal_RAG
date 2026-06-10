import React, { useState, useEffect } from 'react'
import { apiClient } from '../api/client'
import { QueryHistory } from '../types'

interface HistoryProps {
    onReuseQuestion: (question: string, answerType: string) => void
}

export const History: React.FC<HistoryProps> = ({ onReuseQuestion }) => {
    const [records, setRecords] = useState<QueryHistory[]>([])
    const [loading, setLoading] = useState(false)
    const [showConfirm, setShowConfirm] = useState(false)

    const fetchHistory = async () => {
        setLoading(true)
        try {
            const res = await apiClient.getHistory()
            setRecords(res.records)
        } catch (err) {
            console.error('获取历史记录失败:', err)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchHistory()
    }, [])

    const handleDelete = async (recordId: number) => {
        if (!confirm('确定要删除这条记录吗？')) return
        try {
            await apiClient.deleteHistory(recordId)
            setRecords(prev => prev.filter(r => r.id !== recordId))
        } catch (err) {
            console.error('删除失败:', err)
        }
    }

    const handleClearAll = async () => {
        if (!confirm('确定要清空所有历史记录吗？此操作不可恢复！')) return
        try {
            await apiClient.clearAllHistory()
            setRecords([])
            setShowConfirm(false)
        } catch (err) {
            console.error('清空失败:', err)
        }
    }

    const getAnswerTypeLabel = (type: string): string => {
        const labels: Record<string, string> = {
            number: '数值',
            name: '名称',
            boolean: '是/否',
            list: '列表',
            text: '文本'
        }
        return labels[type] || type
    }

    const getAnswerTypeColor = (type: string): string => {
        const colors: Record<string, string> = {
            number: 'bg-blue-500/20 text-blue-300',
            name: 'bg-purple-500/20 text-purple-300',
            boolean: 'bg-green-500/20 text-green-300',
            list: 'bg-orange-500/20 text-orange-300',
            text: 'bg-gray-500/20 text-gray-300'
        }
        return colors[type] || 'bg-gray-500/20 text-gray-300'
    }

    return (
        <div className="p-6 max-w-4xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h2 className="text-2xl font-bold text-on-surface mb-1">查询历史</h2>
                    <p className="text-on-surface-variant text-sm">
                        记录保留 3 天，共 {records.length} 条记录
                    </p>
                </div>
                <div className="flex gap-3">
                    <button
                        onClick={fetchHistory}
                        className="px-4 py-2 bg-surface/50 text-on-surface rounded-lg hover:bg-surface transition-colors flex items-center gap-2"
                    >
                        <span>🔄</span>
                        刷新
                    </button>
                    {records.length > 0 && (
                        <button
                            onClick={() => setShowConfirm(true)}
                            className="px-4 py-2 bg-red-500/20 text-red-300 rounded-lg hover:bg-red-500/30 transition-colors"
                        >
                            清空所有
                        </button>
                    )}
                </div>
            </div>

            {loading ? (
                <div className="flex justify-center items-center py-12">
                    <div className="animate-spin rounded-full h-12 w-12 border-4 border-primary border-t-transparent"></div>
                </div>
            ) : records.length === 0 ? (
                <div className="text-center py-16 glass-panel rounded-xl">
                    <div className="text-6xl mb-4">📝</div>
                    <h3 className="text-xl font-semibold text-on-surface mb-2">暂无查询记录</h3>
                    <p className="text-on-surface-variant">开始查询后，记录将显示在这里</p>
                </div>
            ) : (
                <div className="space-y-4">
                    {records.map(record => (
                        <div key={record.id} className="glass-panel rounded-xl p-5">
                            <div className="flex items-start justify-between mb-3">
                                <div className="flex-1">
                                    <div className="flex items-center gap-3 mb-2">
                                        <span className={`px-2 py-1 rounded text-xs font-medium ${getAnswerTypeColor(record.answer_type)}`}>
                                            {getAnswerTypeLabel(record.answer_type)}
                                        </span>
                                        <span className="text-on-surface-variant text-sm">
                                            {record.created_at_formatted}
                                        </span>
                                        <span className="text-on-surface-variant text-sm">
                                            · {record.elapsed.toFixed(2)}s
                                        </span>
                                    </div>
                                    <p className="text-on-surface font-medium">
                                        {record.question}
                                    </p>
                                </div>
                                <div className="flex gap-2 ml-4">
                                    <button
                                        onClick={() => onReuseQuestion(record.question, record.answer_type)}
                                        className="p-2 text-primary hover:bg-primary/10 rounded-lg transition-colors"
                                        title="重新查询"
                                    >
                                        🔍
                                    </button>
                                    <button
                                        onClick={() => handleDelete(record.id)}
                                        className="p-2 text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                                        title="删除"
                                    >
                                        🗑️
                                    </button>
                                </div>
                            </div>

                            <div className="bg-surface/30 rounded-lg p-4 mb-3">
                                <p className="text-on-surface whitespace-pre-wrap">{record.answer}</p>
                            </div>

                            {record.sources && record.sources.length > 0 && (
                                <div className="flex flex-wrap gap-2">
                                    {record.sources.map((source, idx) => (
                                        <span
                                            key={idx}
                                            className="px-3 py-1 bg-surface/50 text-on-surface-variant text-xs rounded-full"
                                        >
                                            📄 {source}
                                        </span>
                                    ))}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}

            {showConfirm && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
                    <div className="glass-panel rounded-xl p-6 max-w-md w-full mx-4">
                        <h3 className="text-xl font-semibold text-on-surface mb-3">确认清空</h3>
                        <p className="text-on-surface-variant mb-6">
                            确定要清空所有历史记录吗？此操作不可恢复！
                        </p>
                        <div className="flex justify-end gap-3">
                            <button
                                onClick={() => setShowConfirm(false)}
                                className="px-4 py-2 bg-surface/50 text-on-surface rounded-lg hover:bg-surface transition-colors"
                            >
                                取消
                            </button>
                            <button
                                onClick={handleClearAll}
                                className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors"
                            >
                                确认清空
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
