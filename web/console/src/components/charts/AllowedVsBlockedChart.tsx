import {
  CategoryScale,
  Chart as ChartJS,
  Filler,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
  type ChartOptions,
} from 'chart.js'
import { Line } from 'react-chartjs-2'
import type { TimeseriesPoint } from '../../types/api'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip)

function gradient(ctx: CanvasRenderingContext2D, color: string) {
  const g = ctx.createLinearGradient(0, 0, 0, 280)
  g.addColorStop(0, color.replace('ALPHA', '0.28'))
  g.addColorStop(1, color.replace('ALPHA', '0'))
  return g
}

const options: ChartOptions<'line'> = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: {
      display: true,
      position: 'top',
      align: 'end',
      labels: {
        color: '#8DA2AE',
        boxWidth: 10,
        boxHeight: 10,
        usePointStyle: true,
        font: { family: 'IBM Plex Mono', size: 10 },
      },
    },
    tooltip: {
      backgroundColor: '#06101A',
      borderColor: 'rgba(255,255,255,0.1)',
      borderWidth: 1,
      titleColor: '#E6F1F5',
      bodyColor: '#8DA2AE',
      padding: 10,
      cornerRadius: 8,
      titleFont: { family: 'IBM Plex Mono' },
      bodyFont: { family: 'IBM Plex Mono' },
    },
  },
  scales: {
    x: {
      grid: { color: 'rgba(255,255,255,0.04)' },
      ticks: { color: '#51636E', font: { family: 'IBM Plex Mono', size: 10 } },
      border: { display: false },
    },
    y: {
      grid: { color: 'rgba(255,255,255,0.04)' },
      ticks: { color: '#51636E', font: { family: 'IBM Plex Mono', size: 10 } },
      border: { display: false },
    },
  },
}

export function AllowedVsBlockedChart({ series }: { series: TimeseriesPoint[] }) {
  const labels = series.map((p) =>
    new Date(p.t).toLocaleTimeString('en', { hour: '2-digit', hour12: false }).slice(0, 2),
  )

  return (
    <Line
      options={options}
      data={{
        labels,
        datasets: [
          {
            // Total request volume (allowed + blocked) — a thin, fill-less
            // envelope. Makes a collapse in overall traffic obvious at a glance
            // (e.g. the API-quota outage that silently dropped both series).
            label: 'Total',
            data: series.map((p) => p.allowed + p.blocked),
            borderColor: '#8DA2AE',
            borderDash: [4, 3],
            fill: false,
            tension: 0.4,
            borderWidth: 1.5,
            pointRadius: 0,
            pointHoverRadius: 4,
          },
          {
            label: 'Allowed',
            data: series.map((p) => p.allowed),
            borderColor: '#0FFFFF',
            backgroundColor: (c) =>
              gradient(c.chart.ctx, 'rgba(15,255,255,ALPHA)'),
            fill: true,
            tension: 0.4,
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 4,
          },
          {
            label: 'Blocked',
            data: series.map((p) => p.blocked),
            borderColor: '#FF0080',
            backgroundColor: (c) => gradient(c.chart.ctx, 'rgba(255,0,128,ALPHA)'),
            fill: true,
            tension: 0.4,
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 4,
          },
        ],
      }}
    />
  )
}
