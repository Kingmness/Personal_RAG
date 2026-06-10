/**
 * 前端日志系统
 * 将关键事件上报到后端，写入同一日志文件，实现前后端日志统一排查
 */

// 全局 trace_id，从 API 响应头中获取
let _currentTraceId = '-'

export function setTraceId(tid: string) {
    _currentTraceId = tid
}

export function getTraceId(): string {
    return _currentTraceId
}

/** 生成新的 trace_id（用于前端主动发起的操作） */
export function generateTraceId(): string {
    const tid = Math.random().toString(36).substring(2, 14)
    _currentTraceId = tid
    return tid
}

interface LogPayload {
    level: 'INFO' | 'WARNING' | 'ERROR'
    message: string
    trace_id?: string
    url?: string
    extra?: Record<string, unknown>
}

/** 上报日志到后端（静默，不抛异常） */
async function _report(payload: LogPayload) {
    try {
        await fetch('/api/frontend-log', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ...payload,
                trace_id: payload.trace_id || _currentTraceId,
                url: payload.url || window.location.href,
            }),
        })
    } catch {
        // 上报失败静默忽略，避免循环
    }
}

/** 记录 INFO 级别日志 */
export function info(message: string, extra?: Record<string, unknown>) {
    console.log(`[INFO] [${_currentTraceId}] ${message}`, extra || '')
    _report({ level: 'INFO', message, extra })
}

/** 记录 WARNING 级别日志 */
export function warn(message: string, extra?: Record<string, unknown>) {
    console.warn(`[WARN] [${_currentTraceId}] ${message}`, extra || '')
    _report({ level: 'WARNING', message, extra })
}

/** 记录 ERROR 级别日志（自动上报） */
export function error(message: string, extra?: Record<string, unknown>) {
    console.error(`[ERROR] [${_currentTraceId}] ${message}`, extra || '')
    _report({ level: 'ERROR', message, extra })
}

export const logger = { info, warn, error, setTraceId, getTraceId, generateTraceId }
