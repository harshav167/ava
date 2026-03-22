Starting CodeRabbit review in plain text mode...

Connecting to review service
Setting up
Analyzing
Reviewing

============================================================================
File: voice_mode/elevenlabs_tts_stt.py
Line: 86 to 87
Type: potential_issue

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @voice_mode/elevenlabs_tts_stt.py around lines 86 - 87, The call to elevenlabs_play(audio_iterator) inside the async function is blocking and will freeze the event loop; wrap that blocking playback call in asyncio.to_thread(...) (or otherwise run it off the event loop) so playback runs in a background thread, and ensure asyncio is imported at the top of the module; update the code that calls elevenlabs_play to use asyncio.to_thread(elevenlabs_play, audio_iterator) (or an equivalent non-blocking executor) so the async function remains non-blocking.



============================================================================
File: voice_mode/tools/converse.py
Line: 986
Type: potential_issue

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @voice_mode/tools/converse.py at line 986, Docstring and validation disagree on the TTS "speed" parameter: the docstring (near the "speed (0.7-1.2)" mention) says ElevenLabs range 0.7–1.2 but the validation logic currently allows 0.25–4.0 (e.g., the check that looks like "if not 0.25 <= speed <= 4.0: raise ..."). Update the validation to enforce 0.7 <= speed <= 1.2 (replace the 0.25/4.0 bounds) and keep the docstring as-is; also search for any other checks that validate "speed" (the same validation block referenced around the 1046-1049 area) and make them consistent with 0.7–1.2.



============================================================================
File: voice_mode/elevenlabs_realtime_stt.py
Line: 16 to 17
Type: potential_issue

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @voice_mode/elevenlabs_realtime_stt.py around lines 16 - 17, Update the ElevenLabs SDK imports to use the canonical module path: replace imports of AudioFormat, CommitStrategy, and RealtimeEvents from submodules with direct imports from elevenlabs.realtime so that AudioFormat, CommitStrategy, and RealtimeEvents are imported from elevenlabs.realtime rather than elevenlabs.realtime.scribe or elevenlabs.realtime.connection to avoid ImportError.



Review completed: 3 findings ✔

============================================================================
File: voice_mode/config.py
Line: 556 to 561
Type: potential_issue

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @voice_mode/config.py around lines 556 - 561, reload_configuration() currently sets TTS_BASE_URLS via parse_comma_list unconditionally, causing different behavior than the initial load which checks ELEVENLABS_API_KEY; update reload_configuration() to mirror the initial logic: if ELEVENLABS_API_KEY is set and VOICEMODE_TTS_BASE_URLS env var is not present, assign TTS_BASE_URLS = ["elevenlabs://tts"], otherwise call parse_comma_list("VOICEMODE_TTS_BASE_URLS", "elevenlabs://tts"); apply the same conditional pattern for any related variables (e.g., STT_BASE_URLS) so reload and initial load behave consistently and reference the functions/variables ELEVENLABS_API_KEY, reload_configuration, parse_comma_list, TTS_BASE_URLS, STT_BASE_URLS.



============================================================================
File: voice_mode/tools/converse.py
Line: 1739 to 1744
Type: potential_issue

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @voice_mode/tools/converse.py around lines 1739 - 1744, The log call in conversation_logger.log_stt always hardcodes model="scribe_v2_realtime" even when the code falls back to speech_to_text(...); update the call to use the actual STT path/model variable (e.g., derive a model_name or stt_method variable used by speech_to_text or earlier logic) instead of the constant string so fallback/batch sessions are labeled correctly; locate conversation_logger.log_stt and the surrounding branch that calls speech_to_text(...) and pass the correct model/model_type/provider indicators based on which function succeeded.



============================================================================
File: voice_mode/elevenlabs_tts_stt.py
Line: 43 to 46
Type: potential_issue

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @voice_mode/elevenlabs_tts_stt.py around lines 43 - 46, The TTS wrapper ignores the voice/model arguments by always using ELEVENLABS_TTS_VOICE and ELEVENLABS_TTS_MODEL; update the wrapper so it uses the incoming parameters (e.g., voice and model passed from converse) instead of the globals: replace assignments to el_voice/ELEVENLABS_TTS_MODEL with the function parameters, log the effective voice and model (logger.info f"ElevenLabs TTS: voice={voice}, model={model}"), pass those into get_client/any ElevenLabs call and ensure the returned config reflects the passed-in values; apply the same fix in the two other similar blocks (around lines referenced 78-83 and 97-103) so --voice and --tts-model are honored and the response matches the request.



============================================================================
File: voice_mode/provider_discovery.py
Line: 87 to 93
Type: potential_issue

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @voice_mode/provider_discovery.py around lines 87 - 93, The registry is being initialized with voices=[] for ElevenLabs entries so find_endpoint_with_voice() can never match; populate the EndpointInfo.voices for each url with a fallback list of ElevenLabs voice IDs (e.g., derive from ELEVENLABS_TTS_MODELS or a new DEFAULT_ELEVENLABS_VOICES constant) when creating registry["tts"][url] so voice-based lookups can succeed; update the loop that builds EndpointInfo (referencing TTS_BASE_URLS, registry["tts"], EndpointInfo, ELEVENLABS_TTS_MODELS, and find_endpoint_with_voice()) to fill voices with the available voice IDs instead of an empty list.



============================================================================
File: voice_mode/cli.py
Line: 350 to 355
Type: potential_issue

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @voice_mode/cli.py around lines 350 - 355, The branches checking service_name == 'whisper' and 'kokoro' currently print an error and return, which yields exit code 0; change these to raise click.ClickException with the same error message (e.g., "Whisper has been removed..."/"Kokoro has been removed...") so the CLI exits non‑zero; locate the checks in voice_mode/cli.py (the service install handler referencing service_name) and replace the click.secho()+return pattern with raising click.ClickException, matching the pattern used by the legacy handlers below.



============================================================================
File: voice_mode/tools/converse.py
Line: 251 to 259
Type: potential_issue

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @voice_mode/tools/converse.py around lines 251 - 259, The guard currently sets voice_mode.config._startup_initialized before awaiting provider_registry.initialize(), which can leave the flag true if initialization fails; move the assignment so voice_mode.config._startup_initialized = True only after await provider_registry.initialize() completes successfully (and if you add error handling, catch/log exceptions from provider_registry.initialize() and rethrow or return without setting the flag so subsequent calls can retry). Ensure you update the block that references voice_mode.config._startup_initialized and provider_registry.initialize() accordingly.



============================================================================
File: voice_mode/elevenlabs_tts_stt.py
Line: 166 to 172
Type: potential_issue

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @voice_mode/elevenlabs_tts_stt.py around lines 166 - 172, The wrapper currently forces model_id="scribe_v2" and converts STT_LANGUAGE="auto" to "en", which disables auto-detection and ignores the caller's model choice; change the call to forward the wrapper's model parameter (pass model_id=model or the correct param name used by elevenlabs_stt_batch) and treat auto as None so elevenlabs_stt_batch can omit the language field (use language_code = STT_LANGUAGE if (STT_LANGUAGE and STT_LANGUAGE != "auto") else None).



Review completed: 7 findings ✔
