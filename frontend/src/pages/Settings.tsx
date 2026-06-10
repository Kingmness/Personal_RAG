import React, { useState, useEffect } from 'react'
import { apiClient } from '../api/client'
import { ConfigItem } from '../types'

export const Settings: React.FC = () => {
    const [config, setConfig] = useState<Record<string, ConfigItem>>({})
    const [loading, setLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [restarting, setRestarting] = useState(false)
    const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null)
    const [logLevel, setLogLevel] = useState<string>('INFO')
    const [logLevelLoading, setLogLevelLoading] = useState(false)

    const fetchConfig = async () => {
        setLoading(true)
        try {
            const res = await apiClient.getConfig()
            setConfig(res.config)
        } catch (err) {
            console.error('获取配置失败:', err)
            setMessage({ text: '获取配置失败', type: 'error' })
        } finally {
            setLoading(false)
        }
    }

    const fetchLogLevel = async () => {
        try {
            const res = await apiClient.getLogLevel()
            setLogLevel(res.level)
        } catch (err) {
            console.error('获取日志级别失败:', err)
        }
    }

    useEffect(() => {
        fetchConfig()
        fetchLogLevel()
    }, [])

    const handleChange = (key: string, value: any) => {
        setConfig(prev => ({
            ...prev,
            [key]: { ...prev[key], current: value }
        }))
    }

    const handleSave = async () => {
        setSaving(true)
        setMessage(null)
        try {
            const configToSave: Record<string, any> = {}
            for (const [key, item] of Object.entries(config)) {
                configToSave[key] = item.current
            }
            await apiClient.saveConfig({ config: configToSave })
            setMessage({ text: '配置保存成功！', type: 'success' })
            setTimeout(() => setMessage(null), 3000)
        } catch (err) {
            console.error('保存配置失败:', err)
            setMessage({ text: '保存配置失败', type: 'error' })
        } finally {
            setSaving(false)
        }
    }

    const handleReset = async () => {
        if (!confirm('确定要恢复默认配置吗？')) return
        setSaving(true)
        setMessage(null)
        try {
            await apiClient.resetConfig()
            await fetchConfig()
            setMessage({ text: '配置已恢复默认！', type: 'success' })
            setTimeout(() => setMessage(null), 3000)
        } catch (err) {
            console.error('重置配置失败:', err)
            setMessage({ text: '重置配置失败', type: 'error' })
        } finally {
            setSaving(false)
        }
    }

    const handleRestart = async () => {
        if (!confirm('确定要重启服务吗？这可能需要几秒钟。')) return
        setRestarting(true)
        setMessage(null)
        try {
            await apiClient.restartService()
            setMessage({ text: '重启命令已发送，请等待服务重启...', type: 'success' })
            // 3秒后重新加载页面
            setTimeout(() => {
                window.location.reload()
            }, 3000)
        } catch (err) {
            console.error('重启失败:', err)
            setMessage({ text: '重启失败', type: 'error' })
            setRestarting(false)
        }
    }

    const renderConfigItem = (key: string, item: ConfigItem) => {
        return (
            <div key={key} className="glass-panel rounded-xl p-5 mb-4">
                <div className="flex items-start justify-between mb-3">
                    <div>
                        <label className="text-on-surface font-medium">{item.label}</label>
                        {item.description && (
                            <p className="text-on-surface-variant text-sm mt-1">{item.description}</p>
                        )}
                    </div>
                    {item.current !== item.default && (
                        <span className="text-xs bg-yellow-500/20 text-yellow-300 px-2 py-1 rounded">已修改</span>
                    )}
                </div>

                {item.type === 'int' || item.type === 'float' ? (
                    <input
                        type="number"
                        value={Number(item.current)}
                        min={item.min}
                        max={item.max}
                        step={item.type === 'float' ? 0.01 : 1}
                        onChange={(e) => handleChange(key, item.type === 'float' ? parseFloat(e.target.value) : parseInt(e.target.value))}
                        className="w-full px-4 py-2 bg-surface/50 border border-white/10 rounded-lg text-on-surface focus:outline-none focus:border-primary transition-colors"
                    />
                ) : item.type === 'bool' ? (
                    <label className="flex items-center gap-3 cursor-pointer">
                        <input
                            type="checkbox"
                            checked={Boolean(item.current)}
                            onChange={(e) => handleChange(key, e.target.checked)}
                            className="w-5 h-5 rounded border-white/20 bg-surface/50 text-primary focus:ring-primary"
                        />
                        <span className="text-on-surface">{item.current ? '已启用' : '已禁用'}</span>
                    </label>
                ) : (
                    <input
                        type="text"
                        value={String(item.current)}
                        onChange={(e) => handleChange(key, e.target.value)}
                        className="w-full px-4 py-2 bg-surface/50 border border-white/10 rounded-lg text-on-surface focus:outline-none focus:border-primary transition-colors"
                    />
                )}
            </div>
        )
    }

    // 分组配置项
    const chunkConfigKeys = ['chunk_size', 'chunk_overlap']
    const retrieveConfigKeys = ['route_top_k', 'faiss_top_n', 'bm25_top_n', 'hybrid_top_n', 'faiss_weight', 'bm25_weight']
    const keywordConfigKeys = ['keyword_filter_enabled', 'keyword_bonus_per_match', 'keyword_use_llm', 'keyword_sample_chunks']
    const rerankConfigKeys = ['rerank_batch_size', 'rerank_top_n', 'llm_weight']
    const systemConfigKeys = ['max_backups']

    return (
        <div className="p-6 max-w-4xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h2 className="text-2xl font-bold text-on-surface mb-1">系统设置</h2>
                    <p className="text-on-surface-variant text-sm">
                        调整检索和重排参数，修改后需重启服务生效
                    </p>
                </div>
                <div className="flex gap-3">
                    <button
                        onClick={fetchConfig}
                        className="px-4 py-2 bg-surface/50 text-on-surface rounded-lg hover:bg-surface transition-colors flex items-center gap-2"
                    >
                        <span>🔄</span>
                        刷新
                    </button>
                    <button
                        onClick={handleReset}
                        disabled={saving || loading}
                        className="px-4 py-2 bg-surface/50 text-on-surface rounded-lg hover:bg-surface transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        恢复默认
                    </button>
                    <button
                        onClick={handleSave}
                        disabled={saving || loading}
                        className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    >
                        {saving ? (
                            <div className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent"></div>
                        ) : (
                            <span>💾</span>
                        )}
                        保存配置
                    </button>
                </div>
            </div>

            {message && (
                <div
                    className={`mb-6 p-4 rounded-lg ${message.type === 'success' ? 'bg-green-500/20 border border-green-500/30 text-green-300' : 'bg-red-500/20 border border-red-500/30 text-red-300'}`}
                >
                    {message.text}
                </div>
            )}

            {loading ? (
                <div className="flex justify-center items-center py-12">
                    <div className="animate-spin rounded-full h-12 w-12 border-4 border-primary border-t-transparent"></div>
                </div>
            ) : (
                <>
                    {/* 分块配置 */}
                    <div className="mb-8">
                        <h3 className="text-lg font-semibold text-on-surface mb-4 flex items-center gap-2">
                            <span>📄</span>
                            文档分块
                        </h3>
                        {chunkConfigKeys.map(key => config[key] && renderConfigItem(key, config[key]))}
                    </div>

                    {/* 检索配置 */}
                    <div className="mb-8">
                        <h3 className="text-lg font-semibold text-on-surface mb-4 flex items-center gap-2">
                            <span>🔍</span>
                            混合检索
                        </h3>
                        {retrieveConfigKeys.map(key => config[key] && renderConfigItem(key, config[key]))}
                    </div>

                    {/* 关键词过滤 */}
                    <div className="mb-8">
                        <h3 className="text-lg font-semibold text-on-surface mb-4 flex items-center gap-2">
                            <span>🏷️</span>
                            关键词过滤
                        </h3>
                        {keywordConfigKeys.map(key => config[key] && renderConfigItem(key, config[key]))}
                    </div>

                    {/* 重排配置 */}
                    <div className="mb-8">
                        <h3 className="text-lg font-semibold text-on-surface mb-4 flex items-center gap-2">
                            <span>⚙️</span>
                            LLM 重排
                        </h3>
                        {rerankConfigKeys.map(key => config[key] && renderConfigItem(key, config[key]))}
                    </div>

                    {/* 系统配置 */}
                    <div className="mb-8">
                        <h3 className="text-lg font-semibold text-on-surface mb-4 flex items-center gap-2">
                            <span>📁</span>
                            系统配置
                        </h3>
                        {systemConfigKeys.map(key => config[key] && renderConfigItem(key, config[key]))}
                    </div>

                    {/* 日志级别 */}
                    <div className="mb-8">
                        <h3 className="text-lg font-semibold text-on-surface mb-4 flex items-center gap-2">
                            <span>📝</span>
                            日志级别
                        </h3>
                        <div className="glass-panel rounded-xl p-5">
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-on-surface font-medium">当前级别: <span className="text-primary font-bold">{logLevel}</span></p>
                                    <p className="text-on-surface-variant text-sm mt-1">调整日志输出详细程度，DEBUG 最详细，ERROR 最精简</p>
                                </div>
                                <div className="flex gap-2">
                                    {['DEBUG', 'INFO', 'WARNING', 'ERROR'].map(level => (
                                        <button
                                            key={level}
                                            onClick={async () => {
                                                setLogLevelLoading(true)
                                                try {
                                                    const res = await apiClient.setLogLevel(level)
                                                    setLogLevel(res.level)
                                                    setMessage({ text: `日志级别已调整为 ${res.level}`, type: 'success' })
                                                    setTimeout(() => setMessage(null), 3000)
                                                } catch (err) {
                                                    console.error('设置日志级别失败:', err)
                                                    setMessage({ text: '设置日志级别失败', type: 'error' })
                                                } finally {
                                                    setLogLevelLoading(false)
                                                }
                                            }}
                                            disabled={logLevelLoading || logLevel === level}
                                            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                                                logLevel === level
                                                    ? 'bg-primary text-white'
                                                    : 'bg-surface/50 text-on-surface hover:bg-surface disabled:opacity-50'
                                            }`}
                                        >
                                            {level}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* 重启服务 */}
                    <div className="glass-panel rounded-xl p-6 border border-yellow-500/20">
                        <div className="flex items-center justify-between">
                            <div>
                                <h3 className="text-lg font-semibold text-on-surface mb-2 flex items-center gap-2">
                                    <span>🔄</span>
                                    重启服务
                                </h3>
                                <p className="text-on-surface-variant text-sm">
                                    配置修改后需要重启服务才能生效
                                </p>
                            </div>
                            <button
                                onClick={handleRestart}
                                disabled={restarting}
                                className="px-6 py-3 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                            >
                                {restarting ? (
                                    <div className="animate-spin rounded-full h-5 w-5 border-2 border-white border-t-transparent"></div>
                                ) : (
                                    <span>🔄</span>
                                )}
                                {restarting ? '正在重启...' : '重启服务'}
                            </button>
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}
