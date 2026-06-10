import {
    AnswerRequest,
    AnswerResponse,
    Document,
    RetrieveResponse,
    UploadResponse,
    HistoryResponse,
    SaveHistoryRequest,
    SaveHistoryResponse,
    QueryHistory,
    ConfigResponse,
    SaveConfigRequest,
    SaveConfigResponse,
    ResetConfigResponse,
    RestartResponse,
    LogLevelResponse,
} from '../types'
import { setTraceId, generateTraceId } from '../utils/logger'

interface ActionResponse {
    message?: string
    error?: string
    detail?: string
}

interface DocStatus {
    file_name: string
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

export class ApiClient {
    private baseUrl = '/api'

    /** 封装 fetch，自动从响应头读取 X-Trace-ID */
    private async _fetch(url: string, options?: RequestInit): Promise<Response> {
        const res = await fetch(url, options)
        const tid = res.headers.get('X-Trace-ID')
        if (tid) setTraceId(tid)
        return res
    }

    async getCompanies(): Promise<string[]> {
        const res = await this._fetch(`${this.baseUrl}/companies`)
        if (!res.ok) throw new Error('获取公司列表失败')
        return await res.json()
    }

    async getDocuments(company?: string): Promise<Document[]> {
        const params = new URLSearchParams()
        if (company) params.set('company', company)
        const query = params.toString() ? `?${params.toString()}` : ''
        const res = await this._fetch(`${this.baseUrl}/documents${query}`)
        if (!res.ok) throw new Error('获取文档列表失败')
        return await res.json()
    }

    async uploadFile(file: File): Promise<ActionResponse> {
        const formData = new FormData()
        formData.append('file', file)
        const res = await this._fetch(`${this.baseUrl}/upload`, {
            method: 'POST',
            body: formData
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || '上传失败')
        return data
    }

    async getDocumentStatus(fileName: string): Promise<DocStatus> {
        const res = await this._fetch(`${this.baseUrl}/document/status?file_name=${encodeURIComponent(fileName)}`)
        if (!res.ok) throw new Error('获取文档状态失败')
        return await res.json()
    }

    async deleteDocument(fileName: string): Promise<ActionResponse> {
        const res = await this._fetch(`${this.baseUrl}/document/${encodeURIComponent(fileName)}`, {
            method: 'DELETE'
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || '删除失败')
        return data
    }

    async batchAction(action: 'parse' | 'chunk' | 'index' | 'metadata'): Promise<ActionResponse> {
        const res = await this._fetch(`${this.baseUrl}/${action}`, {
            method: 'POST'
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || '操作失败')
        return data
    }

    async singleAction(action: 'parse' | 'chunk' | 'index' | 'metadata', fileName: string): Promise<ActionResponse> {
        const res = await this._fetch(`${this.baseUrl}/${action}/single`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_name: fileName })
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || '操作失败')
        if (data.error) throw new Error(data.error)
        return data
    }

    async validate(): Promise<any> {
        const res = await this._fetch(`${this.baseUrl}/validate`)
        if (!res.ok) throw new Error('校验失败')
        return await res.json()
    }

    async retrieve(question: string, company: string, top_n: number = 5): Promise<RetrieveResponse> {
        const res = await this._fetch(`${this.baseUrl}/retrieve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, company, top_n })
        })
        if (!res.ok) throw new Error('检索失败')
        return await res.json()
    }

    async answer(request: AnswerRequest): Promise<AnswerResponse> {
        const res = await this._fetch(`${this.baseUrl}/answer`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(request)
        })
        if (!res.ok) throw new Error('生成答案失败')
        return await res.json()
    }

    async answerStream(
        request: AnswerRequest,
        onEvent: (event: any) => void
    ): Promise<void> {
        // 流式请求：先生成 trace_id，通过请求头传递给后端
        const tid = generateTraceId()
        const res = await this._fetch(`${this.baseUrl}/answer/stream`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Trace-ID': tid,
            },
            body: JSON.stringify(request)
        })
        if (!res.ok) throw new Error('生成答案失败')

        const reader = res.body!.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
            const { done, value } = await reader.read()
            if (done) break

            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')
            buffer = lines.pop() || ''

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const event = JSON.parse(line.slice(6))
                        onEvent(event)
                    } catch (e) {
                        // 忽略解析失败的行
                    }
                }
            }
        }
    }

    async getHistory(limit: number = 100, offset: number = 0): Promise<HistoryResponse> {
        const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
        const res = await this._fetch(`${this.baseUrl}/history?${params.toString()}`)
        if (!res.ok) throw new Error('获取历史记录失败')
        return await res.json()
    }

    async saveHistory(request: SaveHistoryRequest): Promise<SaveHistoryResponse> {
        const res = await this._fetch(`${this.baseUrl}/history`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(request)
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || '保存历史记录失败')
        return data
    }

    async deleteHistory(recordId: number): Promise<{ message: string }> {
        const res = await this._fetch(`${this.baseUrl}/history/${recordId}`, {
            method: 'DELETE'
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || '删除历史记录失败')
        return data
    }

    async clearAllHistory(): Promise<{ message: string }> {
        const res = await this._fetch(`${this.baseUrl}/history`, {
            method: 'DELETE'
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || '清空历史记录失败')
        return data
    }

    async cleanupOldHistory(days: number = 3): Promise<{ message: string }> {
        const res = await this._fetch(`${this.baseUrl}/history/cleanup?days=${days}`, {
            method: 'POST'
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || '清理旧记录失败')
        return data
    }

    async getConfig(): Promise<ConfigResponse> {
        const res = await this._fetch(`${this.baseUrl}/config`)
        if (!res.ok) throw new Error('获取配置失败')
        return await res.json()
    }

    async saveConfig(request: SaveConfigRequest): Promise<SaveConfigResponse> {
        const res = await this._fetch(`${this.baseUrl}/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(request)
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || '保存配置失败')
        return data
    }

    async resetConfig(): Promise<ResetConfigResponse> {
        const res = await this._fetch(`${this.baseUrl}/config/reset`, {
            method: 'POST'
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || '重置配置失败')
        return data
    }

    async restartService(): Promise<RestartResponse> {
        const res = await this._fetch(`${this.baseUrl}/restart`, {
            method: 'POST'
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || '重启失败')
        return data
    }

    async getLogLevel(): Promise<LogLevelResponse> {
        const res = await this._fetch(`${this.baseUrl}/log-level`)
        if (!res.ok) throw new Error('获取日志级别失败')
        return await res.json()
    }

    async setLogLevel(level: string): Promise<LogLevelResponse> {
        const res = await this._fetch(`${this.baseUrl}/log-level?level=${encodeURIComponent(level)}`, {
            method: 'POST'
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || '设置日志级别失败')
        return data
    }

    async getTraceLogs(traceId: string, limit: number = 200): Promise<{ trace_id: string; count: number; logs: string[] }> {
        const res = await this._fetch(`${this.baseUrl}/trace/${encodeURIComponent(traceId)}?limit=${limit}`)
        if (!res.ok) throw new Error('查询链路日志失败')
        return await res.json()
    }
}

export const apiClient = new ApiClient()
