"""Opt-in Langfuse tracing v2. Self-activates on import if langfuse_config exists in mykey.

Hooks via monkey-patch (core files stay untouched):
- agent_loop.agent_runner_loop  → top-level 'agent' observation with session_id / user_id
- llmcore._write_llm_log       → 'generation' observation (Prompt=start, Response=end+usage)
- BaseHandler.tool_before/after → 'tool' observation per tool call

v2 fixes (vs v1):
  1. Replaced fragile SSE tee with _write_llm_log hook for reliable usage capture
  2. Proper parent-child nesting: agent → generation / tool (not flat)
  3. Removed broken start_as_current_observation context pattern
  4. Added session_id (from handler.parent.task_dir) and user_id
  5. Uses correct as_type values ('agent', 'generation', 'tool') per v4.6.1 SDK
  6. Proper flush on agent_runner_loop exit
"""

import sys, os, json, threading, time, traceback

# ── TLS for in-flight observations ──────────────────────────────
_tls = threading.local()

def _get(attr, default=None):
    return getattr(_tls, attr, default)

def _set(attr, val):
    setattr(_tls, attr, val)

# ── Lazy Langfuse init ──────────────────────────────────────────
_lf = None
_cfg = None

def _init_langfuse():
    global _lf, _cfg
    if _lf is not None:
        return True
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from llmcore import _load_mykeys
        _cfg = _load_mykeys().get('langfuse_config')
        if not _cfg:
            return False
        from langfuse import Langfuse
        _lf = Langfuse(**_cfg)
        _lf.auth_check()
        return True
    except Exception as e:
        print(f"[Langfuse] Init failed: {e}")
        _lf = None
        return False

# ── Helpers ─────────────────────────────────────────────────────
def _extract_session_id(handler):
    """Extract session name from handler.parent.task_dir."""
    try:
        td = getattr(getattr(handler, 'parent', None), 'task_dir', None)
        if td:
            return os.path.basename(td.rstrip('/\\'))
    except Exception:
        pass
    return None

def _extract_user_id():
    """Best-effort user identification."""
    try:
        return os.environ.get('LANGFUSE_USER_ID') or os.getlogin()
    except Exception:
        return 'unknown'

def _parse_usage_from_raw(raw_text):
    """Extract token usage from raw API response JSON."""
    if not raw_text:
        return None
    try:
        data = json.loads(raw_text) if isinstance(raw_text, str) else raw_text
        usage = data.get('usage')
        if usage and isinstance(usage, dict):
            return {
                'input': usage.get('input_tokens', usage.get('prompt_tokens', 0)),
                'output': usage.get('output_tokens', usage.get('completion_tokens', 0)),
            }
    except Exception:
        pass
    return None

def _safe_name(name, maxlen=80):
    """Truncate and sanitize observation name."""
    if not name:
        return 'unnamed'
    return name[:maxlen].replace('\n', ' ')

_tool_counter = 0
_tool_counter_lock = threading.Lock()

def _next_tool_key(tool_name):
    global _tool_counter
    with _tool_counter_lock:
        _tool_counter += 1
        return f'tool_obs_{_tool_counter}_{tool_name}'

# ════════════════════════════════════════════════════════════════
#  ACTIVATION — monkey-patch on import
# ════════════════════════════════════════════════════════════════
if _init_langfuse():
    from langfuse.types import TraceContext
    import agent_loop
    import llmcore

    # ── 1. Patch _write_llm_log for generation spans ────────────
    _orig_write_log = llmcore._write_llm_log

    def _patched_write_log(label, content, log_path=None):
        try:
            trace_obs = _get('trace_obs')
            if trace_obs is not None:
                if label == 'Prompt':
                    # Start a generation span under the trace
                    # Extract a short preview of the prompt for the name
                    preview = ''
                    try:
                        data = json.loads(content)
                        # Try to get text content from the merged message
                        parts = data.get('content', [])
                        if isinstance(parts, list):
                            for p in parts:
                                if isinstance(p, dict) and p.get('type') == 'text' and p.get('text', '').strip():
                                    preview = p['text'][:60].replace('\n', ' ')
                                    break
                        elif isinstance(parts, str):
                            preview = parts[:60].replace('\n', ' ')
                    except Exception:
                        preview = str(content[:60]).replace('\n', ' ')

                    gen_name = f"llm.{_get('current_model', 'chat')}"
                    gen_obs = trace_obs.start_observation(
                        name=_safe_name(gen_name),
                        as_type='generation',
                        input=content[:8000] if content else None,
                        metadata={'preview': preview} if preview else None,
                    )
                    _set('gen_obs', gen_obs)
                    _set('gen_start', time.time())

                elif label == 'Response':
                    gen_obs = _get('gen_obs')
                    if gen_obs is not None:
                        # Parse usage from response
                        usage = _parse_usage_from_raw(content)
                        update_kwargs = {'output': content[:8000] if content else None}
                        if usage:
                            update_kwargs['usage_details'] = usage
                        elapsed = time.time() - _get('gen_start', time.time())
                        update_kwargs['metadata'] = {'elapsed_sec': round(elapsed, 2)}
                        gen_obs.update(**update_kwargs)
                        gen_obs.end()
                        _set('gen_obs', None)
                        _set('gen_start', None)
        except Exception as e:
            # Never break the core loop
            if os.environ.get('LANGFUSE_DEBUG'):
                print(f"[Langfuse] write_log hook error: {e}")
                traceback.print_exc()

        return _orig_write_log(label, content, log_path)

    _patched_write_log.__wrapped__ = _orig_write_log
    llmcore._write_llm_log = _patched_write_log

    # ── 2. Patch agent_runner_loop for trace lifecycle ──────────
    _orig_loop = agent_loop.agent_runner_loop

    def _patched_loop(client, system_prompt, user_input, handler, tools_schema,
                      max_turns=40, verbose=True, initial_user_content=None, yield_info=False):
        # Create top-level trace observation
        trace_id = _lf.create_trace_id()
        session_id = _extract_session_id(handler)
        user_id = _extract_user_id()
        tc = TraceContext(trace_id=trace_id,
                         session_id=session_id,
                         user_id=user_id)

        task_preview = str(user_input or initial_user_content or '')[:120].replace('\n', ' ')
        trace_obs = _lf.start_observation(
            name=_safe_name(f"agent.{task_preview}" if task_preview else "agent.task"),
            as_type='agent',
            trace_context=tc,
            input={'user_input': str(user_input or '')[:2000],
                   'system_prompt': str(system_prompt or '')[:500]},
        )
        _set('trace_obs', trace_obs)
        _set('trace_id', trace_id)

        # Store model name for generation naming
        try:
            _set('current_model', getattr(getattr(client, 'backend', client), 'model',
                                          getattr(client, 'name', 'unknown')))
        except Exception:
            _set('current_model', 'unknown')

        try:
            gen = _orig_loop(client, system_prompt, user_input, handler, tools_schema,
                             max_turns, verbose, initial_user_content, yield_info)
            result = yield from gen
        except Exception as e:
            trace_obs.update(output={'error': str(e)})
            raise
        finally:
            # Close any dangling generation
            gen_obs = _get('gen_obs')
            if gen_obs is not None:
                try:
                    gen_obs.update(output={'status': 'interrupted'})
                    gen_obs.end()
                except Exception:
                    pass
                _set('gen_obs', None)

            # Finalize and flush
            try:
                trace_obs.update(output=result if isinstance(result, dict) else {'result': str(result)})
                trace_obs.end()
            except Exception:
                pass
            try:
                _lf.flush()
            except Exception:
                pass

            _set('trace_obs', None)
            _set('trace_id', None)
            _set('current_model', None)

        return result

    agent_loop.agent_runner_loop = _patched_loop

    # ── 3. Patch BaseHandler for tool spans ─────────────────────
    from agent_loop import BaseHandler

    _orig_tool_before = BaseHandler.tool_before_callback
    _orig_tool_after = BaseHandler.tool_after_callback

    def _patched_tool_before(self, tool_name, args, response):
        trace_obs = _get('trace_obs')
        if trace_obs is not None:
            try:
                clean_args = {k: v for k, v in args.items() if k not in ('_index', '_tool_num')}
                tool_obs = trace_obs.start_observation(
                    name=_safe_name(f"tool.{tool_name}"),
                    as_type='tool',
                    input=clean_args,
                )
                obs_key = _next_tool_key(tool_name)
                _set(obs_key, tool_obs)
                _set('_last_tool_key', obs_key)
            except Exception:
                pass
        return _orig_tool_before(self, tool_name, args, response)

    def _patched_tool_after(self, tool_name, args, response, ret):
        obs_key = _get('_last_tool_key')
        tool_obs = _get(obs_key) if obs_key else None
        if tool_obs is not None:
            try:
                output = None
                if hasattr(ret, 'data'):
                    output = ret.data
                elif ret is not None:
                    output = str(ret)[:2000]
                tool_obs.update(output=output)
                tool_obs.end()
            except Exception:
                pass
            _set(obs_key, None)
            _set('_last_tool_key', None)
        return _orig_tool_after(self, tool_name, args, response, ret)

    BaseHandler.tool_before_callback = _patched_tool_before
    BaseHandler.tool_after_callback = _patched_tool_after

    # ── 4. Propagate to other modules that imported originals ───
    for _m in list(sys.modules.values()):
        if _m and getattr(_m, 'agent_runner_loop', None) is _orig_loop:
            try:
                setattr(_m, 'agent_runner_loop', _patched_loop)
            except Exception:
                pass

    print(f"[Langfuse] ✅ Tracing v2 active → {_cfg.get('host', 'default')}")
else:
    print("[Langfuse] ⏭️ Skipped (no langfuse_config or auth failed)")
