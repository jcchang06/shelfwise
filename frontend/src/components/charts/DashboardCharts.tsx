/**
 * The dashboard's four T-5 charts. Lazy-loaded by DashboardPage so Chart.js (~60-70 KB
 * gzipped) is only downloaded on the dashboard.
 *
 * Mark specs (dataviz skill): bars <= 24px thick with a 4px rounded data end and a square
 * baseline; a 2px surface-colored gap between stacked segments; hairline gridlines; one
 * tooltip listing every series; a legend whenever there are two series. Colors are the
 * validated series tokens; DNF also differs in lightness, and the legend and table name it.
 */

import {
  BarController,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Tooltip,
  type ChartOptions,
  type ScriptableContext,
} from 'chart.js';
import { Bar } from 'react-chartjs-2';

import type { Stats } from '../../api/stats';
import { ChartFigure } from './ChartFigure';
import { useChartTheme, type ChartTheme } from './chartTheme';
import {
  booksPerYearSummary,
  DATE_UNKNOWN,
  genreSummary,
  monthName,
  pagesSummary,
  ratingsSummary,
} from './summaries';

// Register only what bar charts need (keeps the chunk small).
ChartJS.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend);

const BAR_MAX = 24;

/** Round only the outer (data) end of a stack: the topmost non-zero segment per bar. */
function topRadius(ctx: ScriptableContext<'bar'>): number {
  const { datasetIndex, dataIndex, chart } = ctx;
  const later = chart.data.datasets.slice(datasetIndex + 1);
  const value = Number(chart.data.datasets[datasetIndex].data[dataIndex] ?? 0);
  const isTop = value > 0 && later.every((d) => Number(d.data[dataIndex] ?? 0) === 0);
  return isTop ? 4 : 0;
}

function baseOptions(
  theme: ChartTheme,
  {
    legend,
    horizontal = false,
    stacked = false,
  }: {
    legend: boolean;
    horizontal?: boolean;
    stacked?: boolean;
  },
): ChartOptions<'bar'> {
  const valueAxis = {
    beginAtZero: true,
    stacked,
    border: { display: false },
    grid: { color: theme.grid, lineWidth: 1 },
    ticks: { color: theme.text, precision: 0 },
  };
  const categoryAxis = {
    stacked,
    border: { color: theme.grid },
    grid: { display: false },
    ticks: { color: theme.text },
  };
  return {
    responsive: true,
    maintainAspectRatio: false, // the figure sets the height; axes fit inside it
    indexAxis: horizontal ? 'y' : 'x',
    interaction: { mode: 'index', intersect: false }, // one tooltip, every series
    plugins: {
      legend: {
        display: legend,
        position: 'top',
        align: 'start',
        labels: { color: theme.text, boxWidth: 10, boxHeight: 10, usePointStyle: true },
      },
      tooltip: { enabled: true },
    },
    scales: horizontal ? { x: valueAxis, y: categoryAxis } : { x: categoryAxis, y: valueAxis },
  };
}

function finishedAndDnf(
  theme: ChartTheme,
  finished: number[],
  dnf: number[],
  stacked: boolean,
  horizontal = false,
) {
  const common = {
    maxBarThickness: BAR_MAX,
    borderSkipped: 'start' as const,
  };
  return [
    {
      ...common,
      label: 'Finished',
      data: finished,
      backgroundColor: theme.series1,
      borderRadius: stacked ? topRadius : 4,
      // In a stack, a surface-colored edge makes the 2px gap above this segment.
      ...(stacked
        ? { borderWidth: horizontal ? { right: 2 } : { top: 2 }, borderColor: theme.surface }
        : {}),
    },
    {
      ...common,
      label: 'Did not finish',
      data: dnf,
      backgroundColor: theme.series2,
      borderRadius: stacked ? topRadius : 4,
    },
  ];
}

export function PagesPerMonthChart({ stats }: { stats: Stats }) {
  const theme = useChartTheme();
  const rows = stats.pages_per_month;
  const read = rows.map((r) => r.pages - r.dnf_pages);
  const dnf = rows.map((r) => r.dnf_pages);
  const empty = rows.every((r) => r.pages === 0);
  const data = {
    labels: rows.map((r) => monthName(r.month).slice(0, 3)),
    datasets: finishedAndDnf(theme, read, dnf, true).map((d, i) =>
      i === 0 ? { ...d, label: 'Read' } : d,
    ),
  };
  return (
    <ChartFigure
      title="Pages per month"
      summary={pagesSummary(stats.year, rows)}
      empty={empty}
      table={{
        columns: ['Month', 'Pages', 'From DNF books'],
        rows: rows.map((r) => [monthName(r.month), r.pages, r.dnf_pages]),
      }}
    >
      <Bar data={data} options={baseOptions(theme, { legend: true, stacked: true })} />
    </ChartFigure>
  );
}

export function BooksPerYearChart({ stats }: { stats: Stats }) {
  const theme = useChartTheme();
  const rows = stats.books_per_year;
  const label = (year: number | null) => (year === null ? DATE_UNKNOWN : String(year));
  const empty = rows.every((r) => r.finished + r.dnf === 0);
  const data = {
    labels: rows.map((r) => label(r.year)),
    datasets: finishedAndDnf(
      theme,
      rows.map((r) => r.finished),
      rows.map((r) => r.dnf),
      false,
    ),
  };
  return (
    <ChartFigure
      title="Books per year"
      summary={booksPerYearSummary(rows)}
      empty={empty}
      table={{
        columns: ['Year', 'Finished', 'Did not finish'],
        rows: rows.map((r) => [label(r.year), r.finished, r.dnf]),
      }}
    >
      <Bar data={data} options={baseOptions(theme, { legend: true })} />
    </ChartFigure>
  );
}

export function GenreMixChart({ stats }: { stats: Stats }) {
  const theme = useChartTheme();
  const rows = stats.genre_mix;
  const data = {
    labels: rows.map((r) => r.genre),
    datasets: finishedAndDnf(
      theme,
      rows.map((r) => r.finished),
      rows.map((r) => r.dnf),
      true,
      true, // horizontal: the gap goes on the right edge
    ),
  };
  return (
    <ChartFigure
      title="Genre mix"
      summary={genreSummary(stats.year, rows)}
      empty={rows.length === 0}
      height={Math.max(160, rows.length * 34 + 70)}
      table={{
        columns: ['Genre', 'Finished', 'Did not finish'],
        rows: rows.map((r) => [r.genre, r.finished, r.dnf]),
      }}
    >
      <Bar
        data={data}
        options={baseOptions(theme, { legend: true, horizontal: true, stacked: true })}
      />
    </ChartFigure>
  );
}

export function RatingsChart({ stats }: { stats: Stats }) {
  const theme = useChartTheme();
  const rows = stats.rating_distribution;
  const average = stats.totals.average_rating;
  const rated = rows.reduce((sum, r) => sum + r.books, 0);
  const data = {
    labels: rows.map((r) => `${r.stars}★`),
    datasets: [
      {
        label: 'Books',
        data: rows.map((r) => r.books),
        backgroundColor: theme.series1,
        maxBarThickness: BAR_MAX,
        borderRadius: 4,
        borderSkipped: 'start' as const,
      },
    ],
  };
  return (
    <ChartFigure
      title={average !== null ? `Ratings (average ${average.toFixed(1)})` : 'Ratings'}
      summary={ratingsSummary(stats.year, rows, average)}
      empty={rated === 0}
      table={{
        columns: ['Stars', 'Books'],
        rows: rows.map((r) => [`${r.stars} ${r.stars === 1 ? 'star' : 'stars'}`, r.books]),
      }}
    >
      {/* One series: the title names it, so no legend box (dataviz rule). */}
      <Bar data={data} options={baseOptions(theme, { legend: false })} />
    </ChartFigure>
  );
}

/** Default export for React.lazy. */
export default function DashboardCharts({ stats }: { stats: Stats }) {
  return (
    <div className="chart-grid">
      <PagesPerMonthChart stats={stats} />
      <BooksPerYearChart stats={stats} />
      <GenreMixChart stats={stats} />
      <RatingsChart stats={stats} />
    </div>
  );
}
