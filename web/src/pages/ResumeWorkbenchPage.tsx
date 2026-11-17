import { Navigate, useLocation } from 'react-router-dom'
import { resumeStudioPath } from './career/paths'

export default function ResumeWorkbenchPage() {
  const location = useLocation()
  return <Navigate replace to={{ pathname: resumeStudioPath, search: location.search, hash: location.hash }} />
}
