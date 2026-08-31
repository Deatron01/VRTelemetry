import { useMemo } from 'react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
  getPaginationRowModel,
} from '@tanstack/react-table';
import type { TelemetryFrame } from '../types/telemetry';

export const RawDataExplorer = () => {
  const frames = useTelemetryStore(state => state.frames);

  const columnHelper = createColumnHelper<TelemetryFrame>();

  const columns = useMemo(() => [
    columnHelper.accessor('frame_index', {
      header: 'Frame Index',
      cell: info => info.getValue(),
    }),
    columnHelper.accessor('timestamp_ns', {
      header: 'Timestamp (ns)',
      cell: info => <span className="mono text-[11px]">{info.getValue()}</span>,
    }),
    columnHelper.accessor('hmd_pos_x', {
      header: 'HMD Pos X',
      cell: info => info.getValue().toFixed(4),
    }),
    columnHelper.accessor('hmd_pos_y', {
      header: 'HMD Pos Y',
      cell: info => info.getValue().toFixed(4),
    }),
    columnHelper.accessor('hmd_pos_z', {
      header: 'HMD Pos Z',
      cell: info => info.getValue().toFixed(4),
    }),
    columnHelper.accessor('hmd_tracking_valid', {
      header: 'HMD Valid',
      cell: info => (
        <span className="mono text-[11px]" style={{ color: info.getValue() > 0 ? 'var(--s6)' : 'var(--s2)' }}>
          {info.getValue() > 0 ? 'TRUE' : 'FALSE'}
        </span>
      ),
    }),
    columnHelper.accessor('heart_rate_bpm', {
      header: 'HR (BPM)',
      cell: info => info.getValue().toFixed(1),
    }),
  ], [columnHelper]);

  const table = useReactTable({
    data: frames,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: {
      pagination: {
        pageSize: 50,
      },
    },
  });

  if (!frames.length) return null;

  const pagination = table.getState().pagination;
  const firstRow = pagination.pageIndex * pagination.pageSize + 1;
  const lastRow = Math.min(firstRow + pagination.pageSize - 1, frames.length);

  return (
    <div className="mx-auto flex h-full max-w-[1360px] flex-col gap-4">
      <div>
        <h1 className="page-title">Raw Telemetry</h1>
        <p className="page-sub">Direct inspection of the underlying telemetry schema, frame by frame.</p>
      </div>

      <div className="clay flex min-h-0 flex-1 flex-col gap-3 p-3.5">
        <div className="section-head mb-0">
          <h2 className="section-title">Frame table</h2>
          <div className="section-rule" />
          <span className="section-note">
            {frames.length.toLocaleString()} frames · showing {firstRow.toLocaleString()}–{lastRow.toLocaleString()}
          </span>
        </div>

        <div className="well min-h-0 flex-1 overflow-auto" style={{ borderRadius: 12 }}>
          <table className="data-table">
            <thead>
              {table.getHeaderGroups().map(headerGroup => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map(header => (
                    <th key={header.id}>
                      {flexRender(header.column.columnDef.header, header.getContext())}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map(row => (
                <tr key={row.id}>
                  {row.getVisibleCells().map(cell => (
                    <td key={cell.id} className="num">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between gap-3">
          <div className="text-[12px] text-ink-3">
            Page <span className="mono" style={{ color: 'var(--ink)' }}>{pagination.pageIndex + 1}</span> of{' '}
            <span className="mono" style={{ color: 'var(--ink)' }}>{table.getPageCount()}</span>
          </div>
          <div className="flex gap-2">
            <button className="btn-clay" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>
              Previous
            </button>
            <button className="btn-clay" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
