export interface Document {
    file_name: string
    company_name: string
    report_type: string
    report_year: string
    registered?: boolean
}

export interface Chunk {
    source: string
    page: number
    text: string
    score: number
    relevance_score?: number
    reasoning?: string
    combined_score?: number
}

export interface AnswerRequest {
    question: string
    type: 'number' | 'name' | 'boolean' | 'list' | 'text'
    company: string
    use_rerank: boolean
    top_n: number
}

export interface AnswerResponse {
    answer: string
    pages: number[]
    sources: string[]
    chunks: Chunk[]
    elapsed: number
}

export interface RetrieveResponse {
    chunks: Chunk[]
    elapsed: number
}

export interface UploadResponse {
    message: string
    file_name?: string
}

export interface QueryHistory {
    id: number
    question: string
    answer_type: string
    answer: string
    sources: string[]
    elapsed: number
    created_at: string
    created_at_formatted: string
}

export interface HistoryResponse {
    records: QueryHistory[]
}

export interface SaveHistoryRequest {
    question: string
    answer_type: string
    answer: string
    sources: string[]
    elapsed: number
}

export interface SaveHistoryResponse {
    id: number
    message: string
}

export interface ConfigItem {
    label: string
    type: 'int' | 'float' | 'bool' | 'str'
    current: number | boolean | string
    default: number | boolean | string
    min?: number
    max?: number
    description?: string
}

export interface ConfigResponse {
    config: Record<string, ConfigItem>
}

export interface SaveConfigRequest {
    config: Record<string, number | boolean | string>
}

export interface SaveConfigResponse {
    status: string
    saved: Record<string, any>
}

export interface ResetConfigResponse {
    status: string
    message: string
}

export interface RestartResponse {
    message: string
}

export interface LogLevelResponse {
    level: string
    message?: string
}
