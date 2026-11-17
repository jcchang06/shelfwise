import { useId, type ReactNode } from 'react';

interface ChartFigureProps {
  title: string;
  summary: string;
  /** Shown instead of the chart and table when there's nothing to plot. */
  empty?: boolean;
  /** Column headings and rows for the "Show the numbers" table. */
  table: { columns: string[]; rows: (string | number)[][] };
  height?: number;
  children: ReactNode;
}

/**
 * One dashboard chart: a titled <figure> whose caption is a written summary, the chart
 * (canvas labelled with that summary), and a table of the same numbers behind
 * "Show the numbers", so no value depends on seeing the chart or hovering it.
 */
export function ChartFigure({
  title,
  summary,
  empty,
  table,
  height = 240,
  children,
}: ChartFigureProps) {
  const id = useId();
  return (
    <figure className="chart-figure" aria-labelledby={`${id}-title`}>
      <h3 id={`${id}-title`} className="chart-title">
        {title}
      </h3>
      <figcaption className="chart-summary">{summary}</figcaption>
      {empty ? null : (
        <>
          <div className="chart-canvas" role="img" aria-label={summary} style={{ height }}>
            {children}
          </div>
          <details className="chart-table">
            <summary>Show the numbers</summary>
            <table>
              <thead>
                <tr>
                  {table.columns.map((column) => (
                    <th key={column} scope="col">
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row) => (
                  <tr key={String(row[0])}>
                    {row.map((cell, i) =>
                      i === 0 ? (
                        <th key={i} scope="row">
                          {cell}
                        </th>
                      ) : (
                        <td key={i}>
                          {typeof cell === 'number' ? cell.toLocaleString('en-US') : cell}
                        </td>
                      ),
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </figure>
  );
}
