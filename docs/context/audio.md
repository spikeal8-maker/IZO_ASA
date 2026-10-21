---
status: canonical
domain: audio
read_when: ["audio","speech","transcription","text-to-speech","speech-to-text"]
source_paths: ["backend/app/api/routers/phone_audio.py","backend/app/integrations/phone_speech_http.py","tools/phone_speech_host.py","backend/app/integrations/qwen_asr.py","frontend/src/phone/features/audio/PhoneAudioWorkspace.tsx","frontend/src/phone/features/audio/api.ts","frontend/src/DesktopAudioWorkspace.tsx"]
test_paths: ["backend/test_phone_audio.py","tools/test_phone_speech_host.py","frontend/phoneAudio.test.ts"]
related_domains: ["admin-models"]
forbidden_paths: ["unknown"]
owner: audio-platform
context_role: scoped-domain-map
updated: 2026-10-11
---
# Context: audio

## Назначение

Эта карточка маршрутизирует задачи по speech synthesis, transcription и audio UI.
Она описывает текущие подтверждённые contracts, а не исторический план развития.
Runtime/provider availability отдельно от source truth и по умолчанию неизвестна.

## Текущее capability state

- Authenticated audio config endpoint реализован.
- Authenticated speech endpoint реализован.
- TTS реализован локально через Windows System.Speech.
- Phone transcription client реализован.
- Phone client использует `/api/tools/transcribe`.
- Qwen ASR integration boundary существует как отдельный HTTP client.
- Persistent audio history текущими source paths не доказана.
- Runtime availability ASR/TTS service нельзя выводить только из repository source.

## Владение

- `backend/app/api/routers/phone_audio.py` владеет audio config и speech endpoint.
- Windows speech synthesis выполняется внутри этого router boundary.
- `backend/app/integrations/qwen_asr.py` владеет Qwen ASR HTTP adapter contract.
- `frontend/src/phone/features/audio/api.ts` владеет phone audio HTTP client.
- `PhoneAudioWorkspace.tsx` владеет session-local phone recording UI.
- `DesktopAudioWorkspace.tsx` владеет desktop text-to-speech UI.
- Model publication/configuration может требовать `admin-models`.

## Основные точки входа

1. Audio config: `GET /api/phone/audio/config`.
2. Speech synthesis: `POST /api/phone/audio/speech`.
3. Phone transcription client: `/api/tools/transcribe`.
4. ASR adapter: `backend/app/integrations/qwen_asr.py`.
5. Phone UI: `frontend/src/phone/features/audio/PhoneAudioWorkspace.tsx`.
6. Desktop UI: `frontend/src/DesktopAudioWorkspace.tsx`.

## STT

Speech-to-text начинается с client request и transcription boundary.
Phone client отправляет audio file через protected transcription endpoint.
Qwen ASR adapter имеет отдельные status/transcription operations.
Наличие adapter не доказывает, что runtime service сейчас запущен.
Ошибки provider/runtime должны оставаться безопасными для пользователя.

## TTS

Text-to-speech реализован через authenticated speech endpoint.
Backend использует Windows `System.Speech` и локальные Microsoft voices.
Desktop UI прямо описывает эти голоса как локальные, без внешнего API.
Не документировать внешний production TTS provider без отдельного source evidence.
Speech publication может быть отключена server-side config.

An opt-in `IZO_PHONE_TTS_PROVIDER=http` preserves the Windows voice boundary for
the Linux application. `IZO_PHONE_TTS_HTTP_URL` names an explicit private host
origin on a dedicated port; `IZO_PHONE_TTS_HTTP_TOKEN_FILE` names an external
secret file mounted read-only into the application. The authenticated host
helper `tools/phone_speech_host.py` reuses the existing System.Speech function.
It defaults to loopback, requires an explicit token/work directory, bounds
requests, synthesis concurrency and audio responses, and logs no speech text.
Redirects and ambient proxies are disabled. Missing configuration or unavailable
host speech fails closed with the existing public 503, without fake fallback.

This is a source integration boundary. Fake-only protocol tests do not prove
installed voices, container-to-host reachability or production voice parity.
Starting the helper, choosing its private interface and allowing the exact
provider endpoint require the owned runtime/release scope; no system service,
host firewall or public route is installed by this module.

## Session-local UI audio

Phone workspace хранит записи в component state и object URLs.
Очистка URL происходит при lifecycle cleanup.
Это является session-local UI state.
Не заявлять persistent audio history без отдельного storage/API evidence.
Загрузка файла и запись микрофона не равны persistent server history.

## Границы

- STT и TTS имеют разные execution/provider boundaries.
- UI publication flag не доказывает runtime availability.
- Session-local object URL не является durable storage.
- Audio model admin changes не принадлежат этой карточке автоматически.
- Provider credentials не являются частью frontend contract.
- Не смешивать transcription result с persistent history.
- Не делать broad scan для поиска audio ownership.

## Focused tests

- `backend/test_phone_audio.py` проверяет authenticated speech/config behavior.
- `frontend/phoneAudio.test.ts` проверяет transcription request и speech client behavior.
- Для ASR adapter changes добавлять только соответствующие focused integration tests.
- Runtime availability требует отдельного operational evidence, не unit test claim.

## Safety

- Не выполнять live provider calls ради context validation.
- Не запускать или restart ASR runtime.
- Не использовать production recordings как fixtures.
- Не читать production credentials.
- Не считать configured URL доказательством healthy provider.
- Не расширять scope на admin model changes без отдельного package amendment.

## Unknowns

- Фактическая доступность Qwen ASR runtime неизвестна без live evidence.
- Persistent audio history не доказана.
- Production voice availability зависит от установленного Windows voice set.
- Runtime latency/capacity не выводятся из source.
- Исторические phone-audio документы могут отставать от текущего source.

## Minimal handoff

При расширении audio scope фиксировать:
- STT или TTS меняется;
- какой endpoint/adapter затронут;
- session-local или durable state требуется;
- нужен ли `admin-models`;
- какие focused tests подтверждают contract;
- требуется ли отдельное runtime evidence.

Карточка остаётся bounded routing map и не заменяет product specification.
