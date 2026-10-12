# Disclaimer — Research Use Only

**VRTelemetry is a research data-acquisition tool. It is not a medical device,
it does not diagnose, and nothing it outputs is medical advice.**

Please read this before installing, running, or relying on any output of this
software. By using it you accept the terms below.

---

## 1. Intended purpose

VRTelemetry records sensor data (eye tracking, head and hand pose, physiology
signals reported by the hardware, device state) from people using VR headsets,
and lets researchers review, export and summarise that data **for non-clinical
research**, such as human-factors, usability, and VR-interaction studies.

That is its only intended purpose.

## 2. Not a medical device

VRTelemetry is **not** intended to be used — alone or in combination with other
software or hardware — for the diagnosis, prevention, monitoring, prediction,
prognosis, treatment or alleviation of any disease, injury, disability or other
medical condition, in humans or animals.

- It is **not CE-marked** under the EU Medical Device Regulation
  (Regulation (EU) 2017/745) or the In Vitro Diagnostic Regulation
  (Regulation (EU) 2017/746).
- It is **not cleared, approved or registered** by the U.S. Food and Drug
  Administration or by any other medical-device regulator.
- It has **not been clinically validated**.

Do not use it to make, support or replace any clinical decision about any
person. Do not use it in an emergency. If you have a health concern, consult a
qualified healthcare professional.

## 3. What the numbers are — and are not

Some screens and exports show derived values: questionnaire scores (SSQ,
NASA-TLX), cognitive-load and pupil-response indices, cybersickness indicators,
postural and kinematic measures, data-quality figures, and — where enabled —
experimental stress estimates.

These are **research-support indices**. They are:

- computed from consumer or research-grade VR hardware that was not designed or
  calibrated as medical measuring equipment;
- based on published research methods and simplifying assumptions that may not
  hold for a particular person, headset, task or session;
- **not validated diagnostic measures, not clinical cut-offs, and not health
  assessments of any individual.**

A high or low value does not mean a person is ill, healthy, stressed, impaired,
or anything else. Interpreting results is the researcher's responsibility,
within a properly designed and approved study.

The words "patient", "diagnostic" or "medical" that may appear in the
software, its code or its plugin names refer to research participants and to
technical (signal and system) diagnostics. They do not imply clinical use.

## 4. Your responsibilities as a user

If you record people with VRTelemetry, **you** — the researcher, lab or
institution operating it — are responsible for:

- obtaining any ethics-committee / institutional-review-board approval your
  study requires;
- obtaining valid, informed consent from every participant, and honouring its
  withdrawal;
- complying with data-protection law (in the EU, the GDPR — eye-tracking and
  physiological recordings can be special-category data under Article 9),
  including acting as data controller, securing the data, and running any
  required data-protection impact assessment;
- operating the software securely — for example, the workstation API is meant
  to stay on the local machine and must not be exposed to a network (see
  [SECURITY.md](SECURITY.md));
- participant safety in VR. VRTelemetry does not make a headset safe to use.
  Follow the hardware manufacturer's health and safety warnings (including those
  about photosensitive seizures, motion sickness, and physical surroundings),
  and stop a session if a participant feels unwell.

The consent texts, privacy-notice drafts and data-protection features included
in the software are aids, **not legal advice**, and do not by themselves make
any particular deployment lawful.

## 5. No warranty

The software is provided **"as is" and "as available", without warranty of any
kind**, express or implied, including but not limited to warranties of
accuracy, reliability, completeness, merchantability, fitness for a particular
purpose, and non-infringement. Recordings may be incomplete, mistimed, or
wrong; hardware and drivers may report incorrect values; data may be lost.
Keep your own backups.

## 6. Limitation of liability

To the maximum extent permitted by applicable law, the author(s) and
contributors shall not be liable for any claim, damages or other liability —
whether direct, indirect, incidental, special, consequential or exemplary, and
whether in contract, tort or otherwise — arising from, out of, or in connection
with the software, its outputs, or its use, including any decision made on the
basis of its outputs, any injury or discomfort during a VR session, or any loss
or disclosure of data.

Nothing in this disclaimer limits liability that cannot be limited under
applicable law.

## 7. Third-party hardware and software

Meta Quest, HTC VIVE, SteamVR, OpenXR and other product names are trademarks of
their respective owners. VRTelemetry is an independent project and is not
affiliated with, endorsed by, or sponsored by any of them. Third-party
components bundled with or used by VRTelemetry are governed by their own
licences.

---

This disclaimer supplements the [LICENSE](LICENSE). If any part of it is held
unenforceable, the remainder stays in effect.
