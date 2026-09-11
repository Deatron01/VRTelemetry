// src/frontend/VRTelemetry/src/components/ParticipantConsentFlow.tsx
//
// The participant's own consent (GDPR-09). Replaces the single checkbox the
// researcher used to tick on the participant's behalf.
//
// The wording is not written here. It is fetched from GET /api/consent/texts
// and rendered verbatim, and the SHA-256 the server sent for each text is
// returned with the answers; the server refuses a consent whose hashes do not
// match the current wording. So what is stored proves which words were shown.
//
// Screens, as in the "Consent Texts (UI Copy)" legal draft:
//   notice      A1  short notice, before any box is shown
//   consent     A2  the participant ticks their own boxes; nothing pre-ticked
//   declined    A2-X nothing recorded
//   researcher  B   the researcher confirms how consent was obtained
//   receipt     A3  confirmation and the participant's withdrawal code

import { useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, Loader2, ShieldCheck, X } from 'lucide-react';

const API = 'http://localhost:8000';

interface ConsentItem {
  id: string;
  group: 'participant_required' | 'participant_optional' | 'researcher';
  required: boolean;
  label: string;
  text: string;
  sha256: string;
}

interface ConsentCatalogue {
  text_version: string;
  notice_version: string;
  notice_url: string;
  study_title: string;
  laboratory_name: string;
  provider_name: string;
  language: string;
  configured: boolean;
  short_notice: {
    title: string;
    intro: string;
    what_is_recorded: string[];
    who_is_responsible: string;
    why: string;
    how_long: string;
    your_choice: string;
    contact: string;
  };
  items: ConsentItem[];
}

export interface ConsentSubmission {
  text_version: string;
  language: string;
  choices: Record<string, boolean>;
  researcher_confirmations: Record<string, boolean>;
  displayed_sha256: Record<string, string>;
}

export interface RecordedConsent {
  consent_id: string;
  study_title: string;
  given_at_utc: string;
  choices: Record<string, boolean>;
  withdrawal_code: string | null;
}

interface Props {
  /** Sends the submission to the server; resolves with the recorded consent or throws. */
  onSubmit: (submission: ConsentSubmission) => Promise<RecordedConsent>;
  /** Called when the flow is closed, with the consent if one was recorded. */
  onClose: (recorded: RecordedConsent | null) => void;
}

type Phase = 'loading' | 'notice' | 'consent' | 'declined' | 'researcher' | 'receipt';

export const ParticipantConsentFlow = ({ onSubmit, onClose }: Props) => {
  const [catalogue, setCatalogue] = useState<ConsentCatalogue | null>(null);
  const [phase, setPhase] = useState<Phase>('loading');
  const [choices, setChoices] = useState<Record<string, boolean>>({});
  const [researcher, setResearcher] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [recorded, setRecorded] = useState<RecordedConsent | null>(null);
  const [largeText, setLargeText] = useState(false);

  useEffect(() => {
    fetch(`${API}/api/consent/texts`)
      .then(r => (r.ok ? r.json() : Promise.reject(new Error('Could not load the consent wording.'))))
      .then((data: ConsentCatalogue) => {
        setCatalogue(data);
        // Nothing is ticked in advance: every box starts false (Recital 32 GDPR).
        setChoices(Object.fromEntries(data.items.filter(i => i.group !== 'researcher').map(i => [i.id, false])));
        setResearcher(Object.fromEntries(data.items.filter(i => i.group === 'researcher').map(i => [i.id, false])));
        setPhase('notice');
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Could not load the consent wording.'));
  }, []);

  const participantItems = catalogue?.items.filter(i => i.group !== 'researcher') ?? [];
  const required = participantItems.filter(i => i.required);
  const optional = participantItems.filter(i => !i.required);
  const researcherItems = catalogue?.items.filter(i => i.group === 'researcher') ?? [];
  const allRequiredTicked = required.every(i => choices[i.id]);
  const allResearcherTicked = researcherItems.every(i => researcher[i.id]);

  const readAloud = () => {
    if (!catalogue || !('speechSynthesis' in window)) return;
    const n = catalogue.short_notice;
    const text = [n.title, n.intro, ...n.what_is_recorded, n.who_is_responsible, n.why, n.how_long, n.your_choice].join('. ');
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  };

  const submit = async () => {
    if (!catalogue) return;
    setIsSaving(true);
    setError(null);
    try {
      const result = await onSubmit({
        text_version: catalogue.text_version,
        language: catalogue.language,
        choices,
        researcher_confirmations: researcher,
        displayed_sha256: Object.fromEntries(catalogue.items.map(i => [i.id, i.sha256])),
      });
      setRecorded(result);
      setPhase('receipt');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The consent could not be recorded.');
    } finally {
      setIsSaving(false);
    }
  };

  const textSize = largeText ? 'text-[16px]' : 'text-[13px]';

  const Checkbox = ({ item, value, onChange }: { item: ConsentItem; value: boolean; onChange: (v: boolean) => void }) => (
    <label className="flex cursor-pointer items-start gap-3 rounded-md p-3" style={{ background: 'var(--well-grid)' }}>
      <input type="checkbox" className="mt-1 h-4 w-4 flex-none" style={{ accentColor: 'var(--s1)' }}
        checked={value} onChange={e => onChange(e.target.checked)} />
      <div>
        <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-3">{item.id} — {item.label}</span>
        <p className={`m-0 mt-1 leading-relaxed ${textSize}`}>{item.text}</p>
      </div>
    </label>
  );

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="consent-flow-title">
      <div className="modal-card flex max-w-2xl flex-col overflow-hidden p-0">
        <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid var(--hair)' }}>
          <h2 id="consent-flow-title" className="m-0 flex items-center gap-2 text-[16px] font-semibold">
            <ShieldCheck className="h-[18px] w-[18px]" style={{ color: 'var(--s1)' }} />
            {phase === 'researcher' ? 'Researcher confirmation' : phase === 'receipt' ? 'Consent recorded' : 'Participant consent'}
          </h2>
          {phase !== 'receipt' && (
            <button onClick={() => onClose(null)} aria-label="Close consent flow" className="btn-ghost"><X className="h-[18px] w-[18px]" /></button>
          )}
        </div>

        <div className="space-y-4 overflow-y-auto px-5 py-5">
          {catalogue && !catalogue.configured && (
            <div className="notice tone-2 items-start text-[12px]">
              <AlertCircle className="mt-0.5 h-4 w-4 flex-none text-tone" />
              <p className="m-0">
                The study details in this wording are still placeholders (laboratory, study title, purpose, retention).
                Set the <code>[consent]</code> section in <code>config.toml</code> before recording real participants.
              </p>
            </div>
          )}
          {error && (
            <div className="notice tone-2 items-start text-[13px]">
              <AlertCircle className="mt-0.5 h-4 w-4 flex-none text-tone" /><p className="m-0">{error}</p>
            </div>
          )}
          {phase === 'loading' && !error && (
            <p className="flex items-center gap-2 text-ink-3"><Loader2 className="h-4 w-4 animate-spin" /> Loading the consent wording…</p>
          )}

          {/* A1 — short notice */}
          {phase === 'notice' && catalogue && (
            <div className={`space-y-3 ${textSize}`}>
              <h3 className="m-0 text-[15px] font-semibold">{catalogue.short_notice.title}</h3>
              <p className="m-0">{catalogue.short_notice.intro}</p>
              <div>
                <p className="m-0 font-semibold">What is recorded</p>
                <ul className="m-0 mt-1 list-disc pl-5">
                  {catalogue.short_notice.what_is_recorded.map(line => <li key={line}>{line}</li>)}
                </ul>
              </div>
              <p className="m-0"><strong>Who is responsible:</strong> {catalogue.short_notice.who_is_responsible}</p>
              <p className="m-0"><strong>Why:</strong> {catalogue.short_notice.why}</p>
              <p className="m-0"><strong>How long:</strong> {catalogue.short_notice.how_long}</p>
              <p className="m-0"><strong>Your choice:</strong> {catalogue.short_notice.your_choice}</p>
              <div className="flex flex-wrap gap-2 pt-1 text-[12px]">
                {catalogue.notice_url && (
                  <a href={catalogue.notice_url} target="_blank" rel="noreferrer" className="btn-clay">Read the full privacy notice</a>
                )}
                <button className="btn-clay" onClick={() => setLargeText(v => !v)}>{largeText ? 'Normal text' : 'Larger text'}</button>
                <button className="btn-clay" onClick={readAloud}>Read aloud</button>
                <button className="btn-clay" onClick={() => window.print()}>Print a copy</button>
              </div>
            </div>
          )}

          {/* A2 — the participant's own choices */}
          {phase === 'consent' && catalogue && (
            <div className="space-y-3">
              <p className={`m-0 ${textSize}`}>Please tick each box you agree with. Nothing is ticked in advance.</p>
              <p className="section-title m-0">Needed to take part in this study</p>
              {required.map(item => (
                <Checkbox key={item.id} item={item} value={!!choices[item.id]}
                  onChange={v => setChoices({ ...choices, [item.id]: v })} />
              ))}
              {optional.length > 0 && (
                <>
                  <p className="section-title m-0 pt-2">Optional. Your choice here does not affect your participation.</p>
                  {optional.map(item => (
                    <Checkbox key={item.id} item={item} value={!!choices[item.id]}
                      onChange={v => setChoices({ ...choices, [item.id]: v })} />
                  ))}
                </>
              )}
              <p className="m-0 text-[12px] text-ink-3">
                You can withdraw your consent at any time. Just tell the researcher, or contact {catalogue.short_notice.contact}.
              </p>
            </div>
          )}

          {/* A2-X — declined */}
          {phase === 'declined' && (
            <div className={`space-y-2 ${textSize}`}>
              <h3 className="m-0 text-[15px] font-semibold">That's fine</h3>
              <p className="m-0">Nothing has been recorded. Please let the researcher know you have decided not to take part. Thank you for your time.</p>
            </div>
          )}

          {/* B — researcher confirmation */}
          {phase === 'researcher' && (
            <div className="space-y-3">
              <p className="m-0 text-[13px] text-ink-3">This confirms how consent was obtained. It does not replace the participant's own consent.</p>
              {researcherItems.map(item => (
                <Checkbox key={item.id} item={item} value={!!researcher[item.id]}
                  onChange={v => setResearcher({ ...researcher, [item.id]: v })} />
              ))}
            </div>
          )}

          {/* A3 — receipt */}
          {phase === 'receipt' && recorded && catalogue && (
            <div className={`space-y-3 ${textSize}`}>
              <p className="m-0 flex items-center gap-2 font-semibold"><CheckCircle2 className="h-5 w-5" style={{ color: 'var(--s1)' }} /> Thank you. Your consent has been recorded.</p>
              <ul className="m-0 list-disc pl-5">
                <li><strong>Study:</strong> {recorded.study_title}</li>
                <li><strong>Date and time (UTC):</strong> {recorded.given_at_utc}</li>
                <li>
                  <strong>You agreed to:</strong>{' '}
                  {participantItems.filter(i => recorded.choices[i.id]).map(i => i.id).join(', ')}
                </li>
              </ul>
              {recorded.withdrawal_code && (
                <div className="rounded-md p-3" style={{ background: 'var(--well-grid)' }}>
                  <p className="m-0 text-[12px] text-ink-3">Your withdrawal code</p>
                  <p className="m-0 mono text-[22px] font-semibold tracking-widest">{recorded.withdrawal_code}</p>
                  <p className="m-0 mt-1 text-[12px]">
                    Keep this code. It lets us find and delete your data, including any optional copy held by {catalogue.provider_name}, if you ask us to later.
                    It is shown only once.
                  </p>
                </div>
              )}
              <p className="m-0"><strong>During the session:</strong> you can stop at any time. Just say "stop" or take off the headset.</p>
            </div>
          )}
        </div>

        <div className="flex flex-wrap justify-end gap-2 px-5 py-4" style={{ borderTop: '1px solid var(--hair)' }}>
          {phase === 'notice' && <button className="btn-accent" onClick={() => setPhase('consent')}>Continue</button>}
          {phase === 'consent' && (
            <>
              {/* Same size and weight as the primary action: refusing must be as easy as agreeing. */}
              <button className="btn-accent" onClick={() => setPhase('declined')}>I do not agree</button>
              <button className="btn-accent" disabled={!allRequiredTicked} onClick={() => setPhase('researcher')}>
                I agree. Start the study
              </button>
            </>
          )}
          {phase === 'declined' && <button className="btn-clay" onClick={() => onClose(null)}>Close</button>}
          {phase === 'researcher' && (
            <button className="btn-accent" disabled={!allResearcherTicked || isSaving} onClick={submit}>
              {isSaving ? 'Recording consent…' : 'Record consent'}
            </button>
          )}
          {phase === 'receipt' && (
            <>
              <button className="btn-clay" onClick={() => window.print()}>Print</button>
              <button className="btn-accent" onClick={() => onClose(recorded)}>Hand over to the researcher</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
