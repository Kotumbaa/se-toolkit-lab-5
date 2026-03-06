import { useState, useEffect } from 'react'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  ChartOptions as ChartJSOptions,
} from 'chart.js'
import { Bar, Line } from 'react-chartjs-2'
import './Dashboard.css'

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
)

const STORAGE_KEY = 'api_key'

// API response types
interface ScoreBucket {
  bucket: string
  count: number
}

interface TimelineEntry {
  date: string
  submissions: number
}

interface PassRateEntry {
  task: string
  avg_score: number
  attempts: number
}

interface Lab {
  id: string
  title: string
}

// Chart data types for react-chartjs-2
interface ChartData {
  labels: string[]
  datasets: {
    label: string
    data: number[]
    backgroundColor?: string | string[]
    borderColor?: string
    fill?: boolean
    tension?: number
  }[]
}

const AVAILABLE_LABS: Lab[] = [
  { id: 'lab-01', title: 'Lab 01' },
  { id: 'lab-02', title: 'Lab 02' },
  { id: 'lab-03', title: 'Lab 03' },
  { id: 'lab-04', title: 'Lab 04' },
  { id: 'lab-05', title: 'Lab 05' },
]

function Dashboard() {
  const [token, setToken] = useState(() => localStorage.getItem(STORAGE_KEY) ?? '')
  const [draft, setDraft] = useState('')
  const [selectedLab, setSelectedLab] = useState<string>('lab-04')

  const [scores, setScores] = useState<ScoreBucket[]>([])
  const [timeline, setTimeline] = useState<TimelineEntry[]>([])
  const [passRates, setPassRates] = useState<PassRateEntry[]>([])

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    fetchDashboardData(selectedLab)
  }, [token, selectedLab])

  async function fetchDashboardData(lab: string) {
    setLoading(true)
    setError(null)

    try {
      const [scoresRes, timelineRes, passRatesRes] = await Promise.all([
        fetch(`/analytics/scores?lab=${lab}`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch(`/analytics/timeline?lab=${lab}`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch(`/analytics/pass-rates?lab=${lab}`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
      ])

      if (!scoresRes.ok) {
        throw new Error(`Scores: HTTP ${scoresRes.status}`)
      }
      if (!timelineRes.ok) {
        throw new Error(`Timeline: HTTP ${timelineRes.status}`)
      }
      if (!passRatesRes.ok) {
        throw new Error(`Pass Rates: HTTP ${passRatesRes.status}`)
      }

      const scoresData: ScoreBucket[] = await scoresRes.json()
      const timelineData: TimelineEntry[] = await timelineRes.json()
      const passRatesData: PassRateEntry[] = await passRatesRes.json()

      setScores(scoresData)
      setTimeline(timelineData)
      setPassRates(passRatesData)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  function handleConnect(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = draft.trim()
    if (!trimmed) return
    localStorage.setItem(STORAGE_KEY, trimmed)
    setToken(trimmed)
  }

  function handleDisconnect() {
    localStorage.removeItem(STORAGE_KEY)
    setToken('')
    setDraft('')
  }

  function handleLabChange(e: React.ChangeEvent<HTMLSelectElement>) {
    setSelectedLab(e.target.value)
  }

  // Build bar chart data for score buckets
  const barChartData: ChartData = {
    labels: scores.map((s) => s.bucket),
    datasets: [
      {
        label: 'Number of Submissions',
        data: scores.map((s) => s.count),
        backgroundColor: 'rgba(54, 162, 235, 0.6)',
        borderColor: 'rgba(54, 162, 235, 1)',
      },
    ],
  }

  const barChartOptions: ChartJSOptions<'bar'> = {
    responsive: true,
    plugins: {
      legend: {
        position: 'top',
      },
      title: {
        display: true,
        text: 'Score Distribution',
      },
    },
    scales: {
      y: {
        beginAtZero: true,
        title: {
          display: true,
          text: 'Count',
        },
      },
      x: {
        title: {
          display: true,
          text: 'Score Range',
        },
      },
    },
  }

  // Build line chart data for timeline
  const lineChartData: ChartData = {
    labels: timeline.map((t) => t.date),
    datasets: [
      {
        label: 'Submissions',
        data: timeline.map((t) => t.submissions),
        borderColor: 'rgba(75, 192, 192, 1)',
        backgroundColor: 'rgba(75, 192, 192, 0.2)',
        fill: true,
        tension: 0.3,
      },
    ],
  }

  const lineChartOptions: ChartJSOptions<'line'> = {
    responsive: true,
    plugins: {
      legend: {
        position: 'top',
      },
      title: {
        display: true,
        text: 'Submissions Over Time',
      },
    },
    scales: {
      y: {
        beginAtZero: true,
        title: {
          display: true,
          text: 'Submissions',
        },
      },
    },
  }

  if (!token) {
    return (
      <form className="token-form" onSubmit={handleConnect}>
        <h1>API Key</h1>
        <p>Enter your API key to connect.</p>
        <input
          type="password"
          placeholder="Token"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit">Connect</button>
      </form>
    )
  }

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1>Dashboard</h1>
        <div className="header-controls">
          <select value={selectedLab} onChange={handleLabChange}>
            {AVAILABLE_LABS.map((lab) => (
              <option key={lab.id} value={lab.id}>
                {lab.title}
              </option>
            ))}
          </select>
          <button className="btn-disconnect" onClick={handleDisconnect}>
            Disconnect
          </button>
        </div>
      </header>

      {loading && <p className="loading">Loading...</p>}
      {error && <p className="error">Error: {error}</p>}

      {!loading && !error && (
        <div className="dashboard-content">
          <div className="chart-container">
            <h2>Score Distribution</h2>
            {scores.length > 0 ? (
              <Bar data={barChartData} options={barChartOptions} />
            ) : (
              <p className="no-data">No score data available</p>
            )}
          </div>

          <div className="chart-container">
            <h2>Submissions Timeline</h2>
            {timeline.length > 0 ? (
              <Line data={lineChartData} options={lineChartOptions} />
            ) : (
              <p className="no-data">No timeline data available</p>
            )}
          </div>

          <div className="table-container">
            <h2>Pass Rates per Task</h2>
            {passRates.length > 0 ? (
              <table>
                <thead>
                  <tr>
                    <th>Task</th>
                    <th>Avg Score</th>
                    <th>Attempts</th>
                  </tr>
                </thead>
                <tbody>
                  {passRates.map((entry) => (
                    <tr key={entry.task}>
                      <td>{entry.task}</td>
                      <td>{entry.avg_score}</td>
                      <td>{entry.attempts}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="no-data">No pass rate data available</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default Dashboard
