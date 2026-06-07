import { Link } from 'react-router-dom'
import Placeholder from '../components/Placeholder.jsx'

export default function NotFound() {
  return (
    <Placeholder task="404" title="页面不存在">
      <p>
        <Link to="/">← 回首页</Link>
      </p>
    </Placeholder>
  )
}
