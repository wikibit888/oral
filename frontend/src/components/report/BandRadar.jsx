import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
} from 'recharts'
import { toRadarData } from '../../lib/report.js'

// IELTS-only 4-dimension band radar (0–9 scale). Scenario reports never reach
// here (App hides the band block when dimensions is null).
export default function BandRadar({ dimensions }) {
  const data = toRadarData(dimensions)
  return (
    <ResponsiveContainer width="100%" height={280}>
      <RadarChart data={data} outerRadius="72%">
        <PolarGrid />
        <PolarAngleAxis dataKey="dimension" tick={{ fontSize: 13 }} />
        <PolarRadiusAxis domain={[0, 9]} tickCount={4} tick={{ fontSize: 11 }} />
        {/* recharts 不吃 CSS 变量，与 index.css --accent/-bright 手动同步 */}
        <Radar
          dataKey="band"
          stroke="#0d9c6e"
          fill="#3ecf8e"
          fillOpacity={0.3}
          dot
        />
      </RadarChart>
    </ResponsiveContainer>
  )
}
