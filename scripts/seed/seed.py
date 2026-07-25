from __future__ import annotations

import hashlib
import io
import math
import random
import struct
import wave
from datetime import UTC, datetime, timedelta

from signal_index.config import get_settings
from signal_index.database import SessionLocal
from signal_index.models import (
    AudioSegment,
    ExternalEvent,
    ExtractedEntity,
    FrequencyEntry,
    Hypothesis,
    ProcessingJob,
    Provenance,
    Receiver,
    Recording,
    Relation,
    Source,
    Transcript,
    TransmissionSession,
    User,
)
from signal_index.security import hash_password
from signal_index.storage import ObjectStorage
from sqlalchemy import select

SEED = 20260725


def synthetic_wav(index: int, duration_sec: int = 6, sample_rate: int = 16_000) -> bytes:
    rng = random.Random(SEED + index)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        values = []
        for sample in range(duration_sec * sample_rate):
            t = sample / sample_rate
            tone = 0.18 * math.sin(2 * math.pi * (650 + index * 45) * t)
            cadence = 1.0 if int(t * 4) % 3 else 0.12
            noise = rng.uniform(-0.025, 0.025)
            values.append(struct.pack("<h", int(max(-1, min(1, tone * cadence + noise)) * 32767)))
        wav.writeframes(b"".join(values))
    return output.getvalue()


def main() -> None:
    settings = get_settings()
    storage = ObjectStorage(settings)
    storage.ensure_bucket()
    rng = random.Random(SEED)
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.email == str(settings.FIRST_USER_EMAIL).lower()))
        if user is None:
            user = User(
                email=str(settings.FIRST_USER_EMAIL).lower(),
                display_name="Signal Index Owner",
                password_hash=hash_password(settings.FIRST_USER_PASSWORD.get_secret_value()),
            )
            db.add(user)
            db.flush()
        source = db.scalar(select(Source).where(Source.name == "Synthetic demonstration source"))
        if source is None:
            source = Source(
                name="Synthetic demonstration source",
                adapter_type="user_defined_static",
                enabled=False,
                parser_version="1.0.0",
                license_notes="Generated locally; no external source material.",
                config={"seed": SEED},
            )
            db.add(source)
            db.flush()
        receivers: list[Receiver] = []
        receiver_specs = [
            ("North Atlantic Demo", "KIWISDR", "IS", 64.15, -21.94),
            ("Baltic Demo", "WEBSDR", "FI", 60.17, 24.94),
            ("Central Europe Demo", "KIWISDR", "DE", 50.11, 8.68),
            ("Pacific Demo", "OTHER", "NZ", -41.29, 174.78),
            ("Arctic Demo", "WEBSDR", "NO", 69.65, 18.96),
        ]
        for name, kind, country, latitude, longitude in receiver_specs:
            receiver = Receiver(
                name=name,
                receiver_type=kind,
                base_url=f"https://example.invalid/{name.lower().replace(' ', '-')}",
                country_code=country,
                latitude=latitude,
                longitude=longitude,
                min_frequency_hz=100_000,
                max_frequency_hz=30_000_000,
                supported_modes=["AM", "USB", "LSB", "CW"],
                status="ONLINE" if len(receivers) < 4 else "OFFLINE",
                metadata_json={"synthetic": True},
            )
            db.add(receiver)
            receivers.append(receiver)
        db.flush()
        frequencies: list[FrequencyEntry] = []
        categories = [
            "NUMBERS",
            "MILITARY",
            "AVIATION",
            "MARITIME",
            "DIPLOMATIC",
            "BROADCAST",
            "AMATEUR",
            "UTILITY",
            "UNKNOWN",
        ]
        for index in range(20):
            entry = FrequencyEntry(
                frequency_hz=2_500_000 + index * 377_500,
                mode=["AM", "USB", "LSB"][index % 3],
                label=f"Synthetic channel {index + 1:02d}",
                category=categories[index % len(categories)],
                country_code=receiver_specs[index % 5][2],
                station_name=f"Demo station {index + 1:02d}",
                callsigns=[f"TEST{index + 10}"],
                schedule={"days": ["MON", "WED"], "utc": f"{index % 24:02d}:00"},
                source_id=source.id,
                confidence=round(0.55 + index * 0.02, 2),
                notes="Synthetic non-sensitive seed record.",
                watchlisted=index < 5,
            )
            db.add(entry)
            frequencies.append(entry)
        db.flush()
        sessions: list[TransmissionSession] = []
        for recording_index in range(5):
            audio = synthetic_wav(recording_index)
            sha = hashlib.sha256(audio).hexdigest()
            key = f"seed/originals/{sha}.wav"
            storage.upload(key, audio, "audio/wav")
            started = now - timedelta(days=recording_index * 3, hours=recording_index)
            recording = Recording(
                object_key=key,
                original_filename=f"synthetic-{recording_index + 1}.wav",
                sha256=sha,
                receiver_id=receivers[recording_index].id,
                frequency_hz=frequencies[recording_index * 2].frequency_hz,
                mode=frequencies[recording_index * 2].mode,
                started_at_utc=started,
                ended_at_utc=started + timedelta(seconds=6),
                duration_sec=6,
                sample_rate=16_000,
                channels=1,
                mime_type="audio/wav",
                source_type="IMPORTED",
                processing_status="COMPLETED",
                processing_version="seed-1.0",
            )
            db.add(recording)
            db.flush()
            segment_ids: list[str] = []
            number_groups: set[str] = set()
            callsigns: set[str] = set()
            for segment_index in range(6):
                segment = AudioSegment(
                    recording_id=recording.id,
                    start_sec=float(segment_index),
                    end_sec=float(segment_index + 0.82),
                    duration_sec=0.82,
                    segment_type="VOICE" if segment_index % 3 else "TONE",
                    class_confidence=round(0.55 + rng.random() * 0.4, 3),
                    class_features={"classifier": "seed-rules", "synthetic": True},
                    snr_db=round(3 + rng.random() * 17, 2),
                    rms_energy=round(0.04 + rng.random() * 0.1, 4),
                    spectral_centroid=900 + rng.random() * 1200,
                    spectral_flatness=0.05 + rng.random() * 0.3,
                    bandwidth_hz=600 + rng.random() * 1500,
                    zero_crossing_rate=0.04 + rng.random() * 0.12,
                    reviewed=segment_index < 2,
                )
                db.add(segment)
                db.flush()
                segment_ids.append(segment.id)
                group = f"{281 + recording_index}{46 + segment_index}{992 - segment_index}"
                callsign = f"TEST{recording_index + 10}"
                number_groups.add(group)
                callsigns.add(callsign)
                machine = Transcript(
                    segment_id=segment.id,
                    transcript_type="MACHINE",
                    language="en" if segment_index % 2 else "ru",
                    text=f"{callsign} two eight one, four six, nine nine two group {segment_index}",
                    normalized_text=f"{callsign.lower()} 281 46 992 group {segment_index}",
                    model_name="synthetic-asr",
                    model_version="1.0",
                    confidence=round(0.45 + rng.random() * 0.45, 3),
                    word_timestamps=[
                        {"word": callsign, "start": 0.0, "end": 0.25, "confidence": 0.8}
                    ],
                    is_preferred=True,
                )
                alternative = Transcript(
                    segment_id=segment.id,
                    transcript_type="ALTERNATIVE",
                    language=machine.language,
                    text=f"{callsign} 281 46 992",
                    normalized_text=f"{callsign.lower()} 281 46 992",
                    model_name="synthetic-asr",
                    model_version="1.0",
                    confidence=0.42,
                    is_preferred=False,
                )
                db.add_all([machine, alternative])
                db.add_all(
                    [
                        ExtractedEntity(
                            segment_id=segment.id,
                            entity_type="CALLSIGN",
                            raw_value=callsign,
                            normalized_value=callsign,
                            confidence=0.88,
                            source="RULE",
                        ),
                        ExtractedEntity(
                            segment_id=segment.id,
                            entity_type="NUMBER_GROUP",
                            raw_value=group,
                            normalized_value=group,
                            confidence=0.9,
                            source="RULE",
                        ),
                    ]
                )
            session = TransmissionSession(
                title=f"Synthetic session {recording_index + 1}",
                start_at_utc=started,
                end_at_utc=started + timedelta(seconds=6),
                primary_frequency_hz=recording.frequency_hz,
                frequencies_hz=[recording.frequency_hz],
                receiver_ids=[recording.receiver_id],
                recording_ids=[recording.id],
                segment_ids=segment_ids,
                callsigns=sorted(callsigns),
                number_groups=sorted(number_groups),
                languages=["en", "ru"],
                category=frequencies[recording_index * 2].category,
                session_fingerprint=f"seed:{recording_index}",
                confidence=round(0.62 + recording_index * 0.06, 2),
                status=["UNREVIEWED", "REVIEWED", "CONFIRMED"][recording_index % 3],
            )
            db.add(session)
            db.flush()
            sessions.append(session)
            for entity in db.scalars(
                select(ExtractedEntity).where(ExtractedEntity.segment_id.in_(segment_ids))
            ):
                entity.session_id = session.id
            db.add(
                Provenance(
                    record_type="RECORDING",
                    record_id=recording.id,
                    source_id=source.id,
                    first_observed_at=started,
                    parser_version="seed-1.0",
                    pipeline_version="seed-1.0",
                    raw_hash=sha,
                    confidence=1.0,
                    license_notes=source.license_notes,
                    raw_object_key=key,
                )
            )
        event = ExternalEvent(
            title="Synthetic public schedule change",
            event_type="SCHEDULE",
            started_at_utc=now + timedelta(hours=2),
            ended_at_utc=now + timedelta(hours=3),
            country_codes=["ZZ"],
            location={"text": "Fictional test region"},
            description="Generated event for testing temporal association; not a real-world claim.",
            source_name="Synthetic demonstration source",
            confidence=0.7,
        )
        db.add(event)
        db.flush()
        db.add_all(
            [
                Relation(
                    subject_type="SESSION",
                    subject_id=sessions[0].id,
                    predicate="SIMILAR_TO",
                    object_type="SESSION",
                    object_id=sessions[1].id,
                    confidence=0.73,
                    relation_status="COMPUTED",
                    causal_claim=False,
                    evidence_ids=sessions[0].segment_ids[:2],
                ),
                Relation(
                    subject_type="SESSION",
                    subject_id=sessions[0].id,
                    predicate="TEMPORALLY_PRECEDES",
                    object_type="EXTERNAL_EVENT",
                    object_id=event.id,
                    delta_seconds=7200,
                    confidence=0.5,
                    relation_status="COMPUTED",
                    causal_claim=False,
                    evidence_ids=[sessions[0].id, event.id],
                ),
            ]
        )
        db.add(
            Hypothesis(
                title="Synthetic cadence hypothesis",
                statement="The fictional TEST10 format may recur on a three-day cadence.",
                status="DRAFT",
                confidence=0.45,
                supporting_evidence_ids=[sessions[0].id],
                contradicting_evidence_ids=[],
                unresolved_evidence_ids=[sessions[1].id],
                related_session_ids=[sessions[0].id, sessions[1].id],
                related_event_ids=[event.id],
                created_by_type="LOCAL_LLM",
                llm_notes="Synthetic seed hypothesis; user approval required.",
            )
        )
        db.add(
            ProcessingJob(
                recording_id=sessions[-1].recording_ids[0],
                status="FAILED",
                stage="ASR",
                progress=0.67,
                attempt=3,
                error_code="SYNTHETIC_ASR_FAILURE",
                error_stderr="Intentional deterministic seed failure.",
            )
        )
    print("Seeded 5 receivers, 20 frequencies, 5 recordings, 30 segments, and analysis records.")


if __name__ == "__main__":
    main()
