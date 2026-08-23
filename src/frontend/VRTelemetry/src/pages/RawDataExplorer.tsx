import React, { useMemo } from 'react';
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
      cell: info => <span className="font-mono text-xs">{info.getValue()}</span>,
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
        <span className={info.getValue() > 0 ? 'text-research-green' : 'text-red-500'}>
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

  return (
    <div className="max-w-6xl mx-auto space-y-6 flex flex-col h-[calc(100vh-140px)]">
      <div className="flex justify-between items-end">
        <div>
          <h1 className="text-2xl font-semibold text-research-graphite">Engineering Diagnostics</h1>
          <p className="text-sm text-research-muted mt-1">Direct inspection of the underlying telemetry schema.</p>
        </div>
      </div>

      <div className="glass-panel overflow-hidden flex flex-col flex-1">
        <div className="overflow-auto flex-1 p-0">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-research-muted uppercase bg-slate-50/50 sticky top-0 backdrop-blur-md border-b border-research-border">
              {table.getHeaderGroups().map(headerGroup => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map(header => (
                    <th key={header.id} className="px-4 py-3 font-medium tracking-wider">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody className="divide-y divide-research-border">
              {table.getRowModel().rows.map(row => (
                <tr key={row.id} className="hover:bg-slate-50/50 transition-colors">
                  {row.getVisibleCells().map(cell => (
                    <td key={cell.id} className="px-4 py-2 text-research-graphite">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        
        {/* Pagination Controls */}
        <div className="flex items-center justify-between px-4 py-3 border-t border-research-border bg-white/40">
          <div className="text-sm text-research-muted">
            Showing Page <span className="font-medium text-research-graphite">{table.getState().pagination.pageIndex + 1}</span> of{' '}
            <span className="font-medium text-research-graphite">{table.getPageCount()}</span>
          </div>
          <div className="flex gap-2">
            <button
              className="glass-button px-3 py-1 text-xs"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
            >
              Previous
            </button>
            <button
              className="glass-button px-3 py-1 text-xs"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};