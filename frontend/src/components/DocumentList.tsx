import React, { useEffect, useState } from 'react'
import { Document } from '../types'
import { apiClient } from '../api/client'

interface DocumentListProps {
  refreshTrigger: number
  onDocumentChange?: () => void
}

interface DocStatus {
  pdf_exists: boolean
  parsed_exists: boolean
  chunked_exists: boolean
  bm25_index_exists: boolean
  faiss_index_exists: boolean
  metadata_registered: boolean
  company_name?: string
  report_type?: string
  report_year?: string
}

export const DocumentList: React.FC<DocumentListProps> = ({ refreshTrigger, onDocumentChange }) => {
  const [documents, setDocuments] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const [processingDoc, setProcessingDoc] = useState<string | null>(null)
  const [statusCache, setStatusCache] = useState<Record<string, DocStatus>>({})

  const fetchDocuments = async () => {
    try {
      const data = await apiClient.getDocuments()
      setDocuments(data)
      for (const doc of data) {
        fetchDocStatus(doc.file_name)
      }
    } catch (err) {
      console.error('获取文档列表失败:', err)
    } finally {
      setLoading(false)
    }
  }

  const fetchDocStatus = async (fileName: string) => {
    try {
      const status = await apiClient.getDocumentStatus(fileName)
      setStatusCache(prev => ({ ...prev, [fileName]: status }))
    } catch (err) {
      console.error(`获取文档状态失败: ${fileName}`, err)
    }
  }

  const handleSingleAction = async (fileName: string, action: 'parse' | 'chunk' | 'index' | 'metadata') => {
    setProcessingDoc(fileName)
    try {
      const data = await apiClient.singleAction(action, fileName)
      alert(data.message || '操作完成')
      fetchDocStatus(fileName)
      if (action === 'metadata') {
        fetchDocuments()
        onDocumentChange?.()
      }
    } catch (err: any) {
      alert(err.message || '操作失败，请检查后端服务是否正常运行')
    } finally {
      setProcessingDoc(null)
    }
  }

  const getStatusBadge = (status: boolean, label: string) => (
    <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium mr-1 ${status ? 'bg-tertiary/10 text-tertiary border border-tertiary/20' : 'bg-surface-container-highest text-on-surface-variant border border-white/10'}`}>
      {status ? '✓' : '✗'} {label}
    </span>
  )

  useEffect(() => {
    fetchDocuments()
  }, [refreshTrigger])

  if (loading) {
    return (
      <div className="glass-panel rounded-2xl p-8">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <span className="text-primary text-2xl">📄</span>
            <h2 className="font-headline-lg text-headline-lg text-on-surface">独立文档处理</h2>
          </div>
        </div>
        <div className="text-center py-16 text-on-surface-variant">加载中...</div>
      </div>
    )
  }

  return (
    <div className="glass-panel rounded-2xl p-8">
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-2">
          <span className="text-primary text-2xl">📄</span>
          <h2 className="font-headline-lg text-headline-lg text-on-surface">独立文档处理</h2>
        </div>
        <button
          onClick={fetchDocuments}
          className="flex items-center gap-2 px-4 py-2 rounded-full bg-surface-container-high border border-white/10 text-on-surface-variant hover:bg-surface-bright hover:text-on-surface transition-all font-label-md text-label-md"
        >
          <span>🔄</span>
          刷新
        </button>
      </div>
      {documents.length === 0 ? (
        <div className="text-center py-16 text-on-surface-variant">
          暂无文档，请上传 PDF 文件
        </div>
      ) : (
        <div className="space-y-4">
          {documents.map((doc, idx) => {
            const status = statusCache[doc.file_name]
            return (
              <div key={idx} className="glass-panel bg-surface-container/30 rounded-xl p-5 border border-white/5 flex items-center justify-between group hover:bg-surface-container/50 transition-all">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-3">
                    <span className="text-on-surface-variant text-xl">📄</span>
                    <h3 className="font-body-lg font-semibold text-on-surface">{doc.file_name}</h3>
                  </div>
                  <div className="flex flex-wrap gap-2 mb-3">
                    {status && (
                      <>
                        {getStatusBadge(status.parsed_exists, '解析')}
                        {getStatusBadge(status.chunked_exists, '分块')}
                        {getStatusBadge(status.bm25_index_exists || status.faiss_index_exists, '索引')}
                        {getStatusBadge(status.metadata_registered, '元信息')}
                      </>
                    )}
                  </div>
                  <div className="text-sm text-on-surface-variant font-label-md">
                    {doc.registered ? (
                      `${doc.company_name} · ${doc.report_type} · ${doc.report_year}`
                    ) : (
                      <span className="text-orange-400">⚠️ 未注册元信息，点击「元信息」按钮注册</span>
                    )}
                  </div>
                </div>
                <div className="flex flex-col gap-2 ml-4 min-w-[120px]">
                  <button
                    onClick={() => handleSingleAction(doc.file_name, 'parse')}
                    disabled={processingDoc === doc.file_name || (status && status.parsed_exists)}
                    className="flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-primary/10 text-primary text-xs font-semibold border border-primary/20 hover:bg-primary/20 transition-all disabled:opacity-50"
                  >
                    <span>📖</span> 解析
                  </button>
                  <button
                    onClick={() => handleSingleAction(doc.file_name, 'chunk')}
                    disabled={processingDoc === doc.file_name || !(status && status.parsed_exists)}
                    className="flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-tertiary/10 text-tertiary text-xs font-semibold border border-tertiary/20 hover:bg-tertiary/20 transition-all disabled:opacity-50"
                  >
                    <span>✂️</span> 分块
                  </button>
                  <button
                    onClick={() => handleSingleAction(doc.file_name, 'index')}
                    disabled={processingDoc === doc.file_name || !(status && status.chunked_exists)}
                    className="flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-secondary/10 text-secondary text-xs font-semibold border border-secondary/20 hover:bg-secondary/20 transition-all disabled:opacity-50"
                  >
                    <span>🔍</span> 索引
                  </button>
                  <button
                    onClick={() => handleSingleAction(doc.file_name, 'metadata')}
                    disabled={processingDoc === doc.file_name}
                    className="flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-orange-500/10 text-orange-400 text-xs font-semibold border border-orange-500/20 hover:bg-orange-500/20 transition-all disabled:opacity-50"
                  >
                    <span>📋</span> 元信息
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
