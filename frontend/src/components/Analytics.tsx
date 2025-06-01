import { useQuery } from '@tanstack/react-query';
import { Line, Bar } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import api from '../services/api';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend
);

interface PerformanceMetrics {
  total_return: number;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  average_win: number;
  average_loss: number;
  profit_factor: number;
}

interface TopPerformer {
  symbol: string;
  return_percent: number;
  profit: number;
}

interface PerformancePoint {
  date: string;
  value: number;
}

interface Performance {
  history: PerformancePoint[];
}

export default function Analytics() {
  const { data: metrics, isLoading: metricsLoading } = useQuery<PerformanceMetrics>({
    queryKey: ['performance-metrics'],
    queryFn: () => api.get('/analytics/metrics').then((res) => res.data),
  });

  const { data: topPerformers, isLoading: performersLoading } = useQuery<TopPerformer[]>({
    queryKey: ['top-performers'],
    queryFn: () => api.get('/analytics/top-performers').then((res) => res.data),
  });

  const { data: performance, isLoading: performanceLoading } = useQuery<Performance>({
    queryKey: ['performance'],
    queryFn: () => api.get('/performance').then((res) => res.data),
  });

  if (metricsLoading || performersLoading || performanceLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
      </div>
    );
  }

  const performanceChartData = {
    labels: performance?.history.map((point) => point.date) || [],
    datasets: [
      {
        label: 'Portfolio Value',
        data: performance?.history.map((point) => point.value) || [],
        borderColor: 'rgb(59, 130, 246)',
        backgroundColor: 'rgba(59, 130, 246, 0.5)',
        tension: 0.4,
      },
    ],
  };

  const topPerformersChartData = {
    labels: topPerformers?.map((performer) => performer.symbol) || [],
    datasets: [
      {
        label: 'Return %',
        data: topPerformers?.map((performer) => performer.return_percent) || [],
        backgroundColor: 'rgba(59, 130, 246, 0.5)',
      },
    ],
  };

  const chartOptions = {
    responsive: true,
    plugins: {
      legend: {
        position: 'top' as const,
      },
    },
    scales: {
      y: {
        beginAtZero: false,
      },
    },
  };

  return (
    <div className="space-y-6">
      {/* Performance Metrics */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <div className="bg-white overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <div className="h-12 w-12 rounded-md bg-primary-500 flex items-center justify-center">
                  <span className="text-white text-xl">📈</span>
                </div>
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-medium text-gray-500 truncate">
                    Total Return
                  </dt>
                  <dd className="text-lg font-semibold text-gray-900">
                    {metrics?.total_return.toFixed(2)}%
                  </dd>
                </dl>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <div className="h-12 w-12 rounded-md bg-green-500 flex items-center justify-center">
                  <span className="text-white text-xl">📊</span>
                </div>
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-medium text-gray-500 truncate">
                    Sharpe Ratio
                  </dt>
                  <dd className="text-lg font-semibold text-gray-900">
                    {metrics?.sharpe_ratio.toFixed(2)}
                  </dd>
                </dl>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <div className="h-12 w-12 rounded-md bg-red-500 flex items-center justify-center">
                  <span className="text-white text-xl">📉</span>
                </div>
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-medium text-gray-500 truncate">
                    Max Drawdown
                  </dt>
                  <dd className="text-lg font-semibold text-gray-900">
                    {metrics?.max_drawdown.toFixed(2)}%
                  </dd>
                </dl>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <div className="h-12 w-12 rounded-md bg-yellow-500 flex items-center justify-center">
                  <span className="text-white text-xl">🎯</span>
                </div>
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-medium text-gray-500 truncate">
                    Win Rate
                  </dt>
                  <dd className="text-lg font-semibold text-gray-900">
                    {metrics?.win_rate.toFixed(2)}%
                  </dd>
                </dl>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Performance Chart */}
      <div className="bg-white shadow rounded-lg p-6">
        <h3 className="text-lg font-medium leading-6 text-gray-900 mb-4">
          Portfolio Performance
        </h3>
        <Line data={performanceChartData} options={chartOptions} />
      </div>

      {/* Additional Metrics */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
        <div className="bg-white overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <div className="h-12 w-12 rounded-md bg-green-500 flex items-center justify-center">
                  <span className="text-white text-xl">💰</span>
                </div>
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-medium text-gray-500 truncate">
                    Average Win
                  </dt>
                  <dd className="text-lg font-semibold text-gray-900">
                    ${metrics?.average_win.toFixed(2)}
                  </dd>
                </dl>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <div className="h-12 w-12 rounded-md bg-red-500 flex items-center justify-center">
                  <span className="text-white text-xl">💸</span>
                </div>
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-medium text-gray-500 truncate">
                    Average Loss
                  </dt>
                  <dd className="text-lg font-semibold text-gray-900">
                    ${metrics?.average_loss.toFixed(2)}
                  </dd>
                </dl>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <div className="h-12 w-12 rounded-md bg-blue-500 flex items-center justify-center">
                  <span className="text-white text-xl">⚖️</span>
                </div>
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-medium text-gray-500 truncate">
                    Profit Factor
                  </dt>
                  <dd className="text-lg font-semibold text-gray-900">
                    {metrics?.profit_factor.toFixed(2)}
                  </dd>
                </dl>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Top Performers */}
      <div className="bg-white shadow rounded-lg p-6">
        <h3 className="text-lg font-medium leading-6 text-gray-900 mb-4">
          Top Performing Stocks
        </h3>
        <Bar data={topPerformersChartData} options={chartOptions} />
      </div>
    </div>
  );
} 