import React, { useState } from 'react'
import { UploadArea } from '../components/UploadArea'
import { ProcessingButtons } from '../components/ProcessingButtons'
import { DocumentList } from '../components/DocumentList'

interface DocumentsProps {
  onDocumentChange?: () => void
}

export const Documents: React.FC<DocumentsProps> = ({ onDocumentChange }) => {
  const [refreshTrigger, setRefreshTrigger] = useState(0)

  const handleUploadComplete = () => {
    setRefreshTrigger((t) => t + 1)
    onDocumentChange?.()
  }

  const handleProcessingComplete = () => {
    setRefreshTrigger((t) => t + 1)
    onDocumentChange?.()
  }

  return (
    <div className="max-w-[1000px] mx-auto space-y-8">
      <UploadArea onUploadComplete={handleUploadComplete} />
      <ProcessingButtons onProcessingComplete={handleProcessingComplete} />
      <DocumentList refreshTrigger={refreshTrigger} onDocumentChange={onDocumentChange} />
    </div>
  )
}
