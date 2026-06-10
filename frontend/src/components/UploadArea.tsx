import React, { useState, useRef } from 'react'
import { apiClient } from '../api/client'
import { logger } from '../utils/logger'

interface UploadAreaProps {
  onUploadComplete: () => void
}

export const UploadArea: React.FC<UploadAreaProps> = ({ onUploadComplete }) => {
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = () => {
    setIsDragging(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const files = Array.from(e.dataTransfer.files)
    handleFiles(files)
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    handleFiles(files)
  }

  const handleFiles = async (files: File[]) => {
    const pdfFiles = files.filter(file =>
      file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
    )
    if (pdfFiles.length === 0) {
      alert('请选择 PDF 文件')
      return
    }

    for (const file of pdfFiles) {
      await uploadFile(file)
    }
  }

  const uploadFile = async (file: File) => {
    setUploading(true)
    setMessage(null)
    logger.info('上传文件', { fileName: file.name, fileSize: file.size })
    try {
      const data = await apiClient.uploadFile(file)
      setMessage(data.message || '上传成功')
      logger.info('上传成功', { fileName: file.name })
      setTimeout(() => {
        onUploadComplete()
      }, 1000)
    } catch (err: any) {
      logger.error('上传失败', { fileName: file.name, error: String(err) })
      setMessage('上传失败，请重试')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="glass-panel rounded-2xl p-8 transition-transform duration-500 hover:scale-[1.002]">
      <div className="flex items-center gap-2 mb-6">
        <span className="text-primary text-2xl">☁️</span>
        <h2 className="font-headline-lg text-headline-lg text-on-surface">上传文档</h2>
      </div>
      {message && (
        <div className={`mb-6 p-4 rounded-xl ${message.includes('失败') ? 'bg-error/10 text-error border border-error/20' : 'bg-tertiary/10 text-tertiary border border-tertiary/20'}`}>
          {message}
        </div>
      )}
      <div
        className={`relative group cursor-pointer border-2 border-dashed rounded-xl p-16 flex flex-col items-center justify-center transition-all ${
          isDragging
            ? 'border-primary bg-primary/10'
            : 'border-white/10 hover:border-primary/50 hover:bg-primary/5'
        }`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf"
          multiple
          onChange={handleFileSelect}
          className="absolute inset-0 opacity-0 cursor-pointer"
        />
        <div className="w-16 h-16 bg-surface-container-high rounded-2xl flex items-center justify-center mb-4 transition-transform group-hover:-translate-y-1">
          <span className="text-4xl text-on-surface-variant">📂</span>
        </div>
        <p className="font-body-lg text-body-lg text-on-surface mb-1">
          {uploading ? '正在上传...' : '拖拽 PDF 文件到这里，或点击选择'}
        </p>
        <p className="text-on-surface-variant opacity-60 font-label-md text-label-md">支持批量上传</p>
      </div>
    </div>
  )
}
