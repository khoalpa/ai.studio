# Local LLM Configuration

Defaults remain `max_parallel_gpu_jobs=1`, `llama_cpp_url=http://127.0.0.1:8080`, a 131072-character request context limit, 8192 output tokens, 120-second timeout and two attempts. `localhost`, `127.0.0.1` and `::1` are the only accepted HTTP hosts. Remote, cloud, malformed and deceptive loopback-like hostnames fail before a request is made.

HTTP mode targets llama.cpp `/completion`, `/health` and `/props` for local health/model capability probes. Redirects are rejected so a loopback service cannot move a request to a remote endpoint. Subprocess mode must receive an explicit executable tuple; M4 neither discovers nor downloads a model. Cancellation and timeout terminate the owned process, wait briefly, then kill it if necessary. `unload()` is the explicit hook for releasing the model before later GPU-heavy image work.

The default pytest suite installs a socket-connect blocker and uses only deterministic mocks or monkeypatched HTTP. The optional test `tests/integration/test_llama_cpp_smoke.py` is marked `local_llm`; it skips unless `AUDIO_STORY_LLAMA_CPP_SMOKE_URL` is explicitly set to an installed loopback backend. No real local backend or GPU smoke run is claimed by M4 CI.
