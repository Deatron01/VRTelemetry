// src/frontend/VRTelemetry/src/components/InfoTooltip.tsx
//
// The app's single reusable contextual-help control: a small "more info"
// icon that opens a positioned panel explaining a metric, chart, menu item
// or setting. Every page should use this instead of a bespoke tooltip —
// see src/content/infoDefinitions.ts for the copy, and pass `id` to look a
// definition up there, or pass title/description/... directly for a
// one-off that isn't worth registering.
//
// Interaction: hover or focus opens it; click "pins" it open (so it survives
// the mouse leaving, e.g. on touch, where there is no hover); Escape closes
// it and returns focus to the trigger; clicking outside closes a pinned
// panel. Positioned via a portal to <body> so it is never clipped by an
// ancestor's overflow:hidden/auto (this app has several — data tables,
// .well panels, the 3D viewer), and it flips side and clamps to the
// viewport near screen edges.

import React, { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, Info } from 'lucide-react';
import { INFO_REGISTRY, type InfoContent, type Provenance } from '../content/infoDefinitions';

const PROVENANCE_LABEL: Record<Provenance, string> = {
  raw: 'RAW',
  device: 'DEVICE-REPORTED',
  measured: 'MEASURED',
  derived: 'DERIVED',
  estimated: 'ESTIMATED',
  reported: 'REPORTED',
  aggregated: 'AGGREGATED',
};

/** Reuses the app's existing six-channel tone scale (see index.css .tone-N). */
const PROVENANCE_TONE: Record<Provenance, number> = {
  raw: 3,
  device: 3,
  measured: 6,
  derived: 1,
  estimated: 4,
  reported: 5,
  aggregated: 1,
};

type Side = 'top' | 'bottom' | 'left' | 'right';

export interface InfoTooltipProps extends Partial<InfoContent> {
  /** Looks up copy in the centralized registry (src/content/infoDefinitions.ts). */
  id?: string;
  /** Preferred side to open on; flips automatically if there isn't room. Default 'top'. */
  side?: Side;
  /** Extra class on the trigger's wrapping <span>. */
  className?: string;
  /** Icon size in px. Default 13. */
  size?: number;
}

const GAP = 8;
const MARGIN = 8;

export const InfoTooltip: React.FC<InfoTooltipProps> = ({
  id, title, description, unit, provenance, source, limitations, side, className, size,
}) => {
  const registryEntry = id ? INFO_REGISTRY[id] : undefined;

  const content: InfoContent = {
    title: title ?? registryEntry?.title ?? '',
    description: description ?? registryEntry?.description ?? '',
    unit: unit ?? registryEntry?.unit,
    provenance: provenance ?? registryEntry?.provenance,
    source: source ?? registryEntry?.source,
    limitations: limitations ?? registryEntry?.limitations,
  };

  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const closeTimer = useRef<number | null>(null);

  const reactId = useId();
  const panelId = `info-panel-${reactId}`;
  const preferredSide: Side = side ?? 'top';

  const reposition = useCallback(() => {
    const trigger = triggerRef.current;
    const panel = panelRef.current;
    if (!trigger || !panel) return;

    const tr = trigger.getBoundingClientRect();
    const pw = panel.offsetWidth;
    const ph = panel.offsetHeight;
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    const spaceAbove = tr.top;
    const spaceBelow = vh - tr.bottom;
    const spaceLeft = tr.left;
    const spaceRight = vw - tr.right;

    let chosen: Side = preferredSide;
    if (chosen === 'top' && spaceAbove < ph + GAP && spaceBelow > spaceAbove) chosen = 'bottom';
    else if (chosen === 'bottom' && spaceBelow < ph + GAP && spaceAbove > spaceBelow) chosen = 'top';
    else if (chosen === 'left' && spaceLeft < pw + GAP && spaceRight > spaceLeft) chosen = 'right';
    else if (chosen === 'right' && spaceRight < pw + GAP && spaceLeft > spaceRight) chosen = 'left';

    let top: number;
    let left: number;
    if (chosen === 'top' || chosen === 'bottom') {
      top = chosen === 'top' ? tr.top - ph - GAP : tr.bottom + GAP;
      left = tr.left + tr.width / 2 - pw / 2;
    } else {
      left = chosen === 'left' ? tr.left - pw - GAP : tr.right + GAP;
      top = tr.top + tr.height / 2 - ph / 2;
    }

    left = Math.min(Math.max(left, MARGIN), Math.max(MARGIN, vw - pw - MARGIN));
    top = Math.min(Math.max(top, MARGIN), Math.max(MARGIN, vh - ph - MARGIN));

    setPos({ top, left });
  }, [preferredSide]);

  useLayoutEffect(() => {
    if (open) reposition();
  }, [open, reposition]);

  useEffect(() => {
    if (!open) return;
    const onScroll = () => reposition();
    const onResize = () => reposition();
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onResize);
    };
  }, [open, reposition]);

  // Clicking outside a *pinned* panel closes it (hover-only panels already
  // close on mouseleave).
  useEffect(() => {
    if (!open || !pinned) return;
    const onDocPointerDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (triggerRef.current?.contains(target)) return;
      if (panelRef.current?.contains(target)) return;
      setOpen(false);
      setPinned(false);
    };
    document.addEventListener('pointerdown', onDocPointerDown);
    return () => document.removeEventListener('pointerdown', onDocPointerDown);
  }, [open, pinned]);

  const clearCloseTimer = () => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  };

  const scheduleClose = useCallback(() => {
    clearCloseTimer();
    closeTimer.current = window.setTimeout(() => {
      setOpen(curOpen => (pinned ? curOpen : false));
    }, 120);
  }, [pinned]);

  useEffect(() => () => clearCloseTimer(), []);

  const handleMouseEnter = () => { clearCloseTimer(); setOpen(true); };
  const handleMouseLeave = () => { if (!pinned) scheduleClose(); };
  const handleFocus = () => { clearCloseTimer(); setOpen(true); };
  const handleBlur = (e: React.FocusEvent) => {
    const next = e.relatedTarget as Node | null;
    if (next && panelRef.current?.contains(next)) return;
    if (!pinned) setOpen(false);
  };
  const handleClick = () => {
    setPinned(prevPinned => {
      const nextPinned = !prevPinned;
      setOpen(nextPinned);
      return nextPinned;
    });
  };
  const handleTriggerKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape' && open) {
      e.stopPropagation();
      setOpen(false);
      setPinned(false);
      triggerRef.current?.focus();
    }
  };

  if (!content.title || !content.description) return null;

  const toneNum = content.provenance ? PROVENANCE_TONE[content.provenance] : undefined;

  return (
    <span className={`info-trigger-wrap${className ? ` ${className}` : ''}`}>
      <button
        ref={triggerRef}
        type="button"
        className="info-trigger"
        aria-label={`More information about ${content.title}`}
        aria-describedby={open ? panelId : undefined}
        aria-expanded={open}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        onFocus={handleFocus}
        onBlur={handleBlur}
        onClick={handleClick}
        onKeyDown={handleTriggerKeyDown}
      >
        <Info size={size ?? 13} aria-hidden="true" />
      </button>
      {open && createPortal(
        <div
          ref={panelRef}
          id={panelId}
          role="tooltip"
          className="info-panel"
          style={pos
            ? { top: pos.top, left: pos.left, visibility: 'visible' }
            : { top: 0, left: 0, visibility: 'hidden' }}
          onMouseEnter={clearCloseTimer}
          onMouseLeave={handleMouseLeave}
        >
          <div className="info-panel-head">
            <span className="info-panel-title">{content.title}</span>
            {content.provenance && (
              <span className={`chip chip-tiny tone-${toneNum}`}>{PROVENANCE_LABEL[content.provenance]}</span>
            )}
          </div>
          <p className="info-panel-desc">
            {content.description}
            {content.unit && <span className="info-panel-unit"> Unit: {content.unit}.</span>}
          </p>
          {content.source && (
            <p className="info-panel-meta"><strong>Source: </strong>{content.source}</p>
          )}
          {content.limitations && (
            <p className="info-panel-limit">
              <AlertTriangle size={11} className="info-panel-limit-icon" aria-hidden="true" />
              <span>{content.limitations}</span>
            </p>
          )}
        </div>,
        document.body,
      )}
    </span>
  );
};
