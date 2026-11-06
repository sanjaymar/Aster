import os
import json
import time

from openai import OpenAI, LengthFinishReasonError
from pathlib import Path
from dataclasses import dataclass, asdict, field
from mini_harness.state import AgentState, context_size, anchors

from mini_harness.config import CONFIG
from mini_harness.retry_request import retry_call
from mini_harness.compact import COMPACT
from mini_harness.tool.box import _ask_human, _always_allow, ToolExecution, _to_api_tool, _atomic_write, log_tool
from mini_harness.tool.tag import OUTCOME, MARK
from mini_harness.tool.block import CLIP

@dataclass(frozen = True)
class Result:
    outcome: str
    calls: int
    turns: int
    ok: int
    failed_by_tag: dict
    calls_by_tool: dict
    last_prompt: int
    prompt_total: int
    completion_total: int
    wall: float
    err: str = ''
    telemetry: dict = field(default_factory=dict)


class MiniHarnessAgent:
    def __init__(self, tools: list, cfg = CONFIG, event_sink=None, cancelled=None) -> None:
        self.event_sink = event_sink
        self.cancelled = cancelled
        self.state = AgentState()
        self.tools = _to_api_tool(tools)
        self.regis = {t.name: t for t in tools}
        self.last_prompt_tokens = 0
        self.printed = ''
        self.system = [
            {
                'role': 'system',
                'content': cfg.system_prompt
            }
        ]
        self.message = list(self.system)
        self.session_memory = cfg.session_path if cfg.session_path else cfg.work_space/'session.json'
        self.last_usage = None
        self.last_reasoning = ''
        return

    def _emit(self, kind, **data):
        if self.cancelled and self.cancelled():
            raise KeyboardInterrupt
        self.state.record(kind, data)
        if self.event_sink:
            self.event_sink(kind, data)

    def _load_memory(self, cfg = CONFIG) -> list:
        if Path(self.session_memory).exists():
            ans = input('\nFound the memory, want to continue the conversation?(yes/no) -> ').strip().lower()
            if ans in cfg.AGREE:
                try:
                    data = json.loads(Path(self.session_memory).read_text(errors = 'replace', encoding = 'utf-8'))
                except (OSError, json.JSONDecodeError) as e:
                    print(f'[load error]: cannot load memory: {e}, start a new conversation')
                    return self.message
                self.message = data
                return self.message
        return self.message

    def _save_memory(self, quiet: bool = False,  cfg = CONFIG) -> None:
        try:
            data = json.dumps(self.message, indent = 2, ensure_ascii=False)
            _atomic_write(Path(self.session_memory), data)
        except (TypeError, ValueError, OSError) as e:
            print(f'[save failed]: cannot save the memory: {e}')
            return

        if not quiet:
            print(f'[save successfully!]')
        return

    def _request_agent(self, client: OpenAI, cfg = CONFIG):
        buffer = ''
        reasoning = ''
        truncated = None
        response = None
        try:
            with client.chat.completions.stream(
                tools = self.tools,
                messages = cfg.request_messages(self.message),
                **cfg.request_options(),
                stream_options = {'include_usage': True}
            ) as e:
                for d in e:
                    if d.type == 'content.delta':
                        self._emit('text', text=d.delta)
                        buffer += d.delta
                        n = min(len(buffer), len(self.printed))
                        if buffer[:n] != self.printed[:n]:
                            print('\n---- [connection lost, the text above is useless] ----')
                            print(buffer, end = '', flush = True)
                            self.printed = buffer
                        elif len(buffer) > len(self.printed):
                            print(buffer[len(self.printed):], end = '', flush = True)
                            self.printed = buffer
                    if d.type == 'chunk':
                        u = getattr(d.chunk, 'usage', None)
                        if u is not None:
                            self.last_usage = u
                        if d.chunk.choices:
                            res = getattr(d.chunk.choices[0].delta, 'reasoning_content', None)
                            if res:
                                reasoning += res
                                print(res, end = '', flush = True)
                response = e.get_final_completion()
                response.choices[0].message.reasoning_content = reasoning
        except LengthFinishReasonError as ex:
            # The SDK can raise during iteration, before get_final_completion().
            truncated = buffer
            comp = getattr(ex, 'completion', None)
            u = getattr(comp, 'usage', None) if comp is not None else None
            if u is not None:
                self.last_usage = u
        if len(buffer) < len(self.printed):
            print(f'\n--- [reconnection lost, the context above is useless] ----')
            if buffer:
                print(buffer, end = '', flush = True)
            self.printed = buffer
        self.last_reasoning = reasoning
        return response, truncated

    def _fill_interrupted(self, tool_calls, cfg = CONFIG) -> None:
        done = [t['tool_call_id'] for t in self.message if t['role'] == 'tool']
        for tool_call in tool_calls:
            if tool_call.id not in done:
                self.message.append(
                    {'role': 'tool', 'tool_call_id': tool_call.id, 'content': f'[intterupted]: the tool {tool_call.function.name} is intterupted'}
                )
        return

    def _run_turn(self, client: OpenAI, executer: ToolExecution, cfg = CONFIG) -> Result:
        start = time.time()
        outcome = OUTCOME.ERROR
        turns = calls = ok = last_prompt = prompt_total = completion_total = 0
        err = ''
        by_tag = {}
        by_tool = {}
        try:
            for turn in range(cfg.max_turns_main):
                self._emit('turn', turn=turn + 1)
                if turn == 0:
                    cfg = cfg.resolve_model(client)
                    self.effective_config = cfg
                if cfg.wall_budget is not None and time.time() -start >= cfg.wall_budget:
                    outcome = OUTCOME.TIMEOUT
                    print(f'[timeout]: agent run out of the time in the task')
                    break
                turns += 1
                self.printed = ''
                adaptive = os.getenv('MINI_HARNESS_CONTEXT_POLICY', 'adaptive') != 'baseline'
                estimated = context_size(self.message) if adaptive else 0
                if max(self.last_prompt_tokens, estimated) >= cfg.compact_limit:
                    before = len(self.message)
                    self._emit('compact_start', messages=before, estimated_tokens=estimated)
                    retained=anchors([{'role':'user','content':value} for value in self.state.memory.get('anchors',[])]+self.message)
                    self.state.memory['anchors']=retained
                    self.message = COMPACT.compact_content(client, self.message, self.session_memory, cfg = cfg, retained=retained)
                    self._emit('compact_end', before=before, after=len(self.message))
                    self._save_memory(quiet=True)
                    self.last_prompt_tokens = 0
                response, truncated = retry_call(lambda: self._request_agent(client, cfg = cfg), cfg = cfg)
                if truncated is not None:
                    note = ('\n\n[Your previous response was cut off at the output token limit. Be more concise, or take an action instead of continuing to reason.]')
                    self.message.append({
                        'role': 'assistant', 'content': truncated + note,
                        'reasoning_content': self.last_reasoning
                    })
                    com_degree = self.last_usage
                    if com_degree is not None:
                        self.last_prompt_tokens = getattr(com_degree, 'prompt_tokens', 0) or 0
                        last_prompt = self.last_prompt_tokens
                        prompt_total += self.last_prompt_tokens
                        completion_total += getattr(com_degree, 'completion_tokens', 0) or 0
                    print(f'[ctx]: {last_prompt} / {cfg.compact_limit} tokens, out {getattr(com_degree, 'completion_tokens', 0)} [TRUNCATED]')
                    self._save_memory(quiet=True)
                    continue
                if response.usage:
                    self._emit('usage', prompt=response.usage.prompt_tokens, completion=response.usage.completion_tokens)
                    self.last_prompt_tokens = response.usage.prompt_tokens
                    last_prompt = response.usage.prompt_tokens
                    prompt_total += response.usage.prompt_tokens
                    completion_total += response.usage.completion_tokens
                    print(f'[ctx]: {last_prompt} / {cfg.compact_limit} tokens, out {response.usage.completion_tokens}')
                message = response.choices[0].message
                if message.tool_calls:
                    print()
                    d = message.model_dump(exclude_none = True)
                    self.message.append(d)
                    try:
                        for tool_call in message.tool_calls:
                            self._emit('tool_start', id=tool_call.id, name=tool_call.function.name, arguments=tool_call.function.arguments)
                            res = executer.execute_tool(tool_call, cfg =cfg)
                            self._emit('tool_end', id=tool_call.id, name=tool_call.function.name, ok=res.ok, tag=res.tag, content=res.content)
                            calls += 1
                            by_tool[tool_call.function.name] = by_tool.get(tool_call.function.name, 0) + 1
                            content = CLIP.clip(res.content, cfg=cfg)
                            if res.ok:
                                ok += 1
                                if tool_call.function.name == 'run_todo':
                                    print(f'\n-=-=-=-=-= Todo List -=-=-=-=-=\n{res.content}')
                            else:
                                by_tag[res.tag] = by_tag.get(res.tag, 0) + 1
                            self.message.append(
                                {'role': 'tool', 'tool_call_id': tool_call.id, 'content': content}
                            ) 
                            log_tool(tool_call, res, cfg = cfg)
                    except KeyboardInterrupt:
                        self._fill_interrupted(message.tool_calls, cfg = cfg)
                        raise
                    self._save_memory(quiet=True)
                else:
                    outcome = OUTCOME.COMPLETED
                    self.message.append(
                        message.model_dump(exclude_none=True)
                    )
                    self._save_memory(quiet=True)
                    break
            else:
                outcome = OUTCOME.EXHAUSTED
                self._save_memory(quiet=True)
                print(f'[agent done]: the agnet run out of the turn for the actions')
        except KeyboardInterrupt:
            outcome = OUTCOME.INTERRUPTED
            print(f'[intterupted]: the action was intterupted')
            self._save_memory(quiet=True)
        except Exception as e:
            outcome = OUTCOME.ERROR
            err = f'{type(e).__name__}:{e}'
            print(f'[run failed]: agent run failed: {err}')
            self._save_memory(quiet=True)
        return Result(
            outcome = outcome,
            calls = calls,
            turns = turns,
            ok = ok,
            last_prompt=last_prompt,
            prompt_total = prompt_total,
            completion_total=completion_total,
            failed_by_tag=by_tag,
            calls_by_tool=by_tool,
            wall = time.time() -start,
            err = err,
            telemetry = self.state.public()
        )

    def run_task(self, task: str, cfg = CONFIG) -> Result:
        self.message = list(self.system)
        client = OpenAI(
            api_key = cfg.api_key,
            base_url = cfg.base_url,
            max_retries = 0
        ) 
        executer = ToolExecution(self.regis, _always_allow, cfg = cfg)
        self.message.append(
            {'role': 'user', 'content': task}
        )
        result = self._run_turn(client, executer, cfg = cfg)
        self._save_memory(quiet=True)
        return result

    def dump_run(self, result: Result, task: str, path: str|None = None, cfg = CONFIG) -> None:
        cfg = getattr(self, 'effective_config', cfg)
        payload = {
            'profile': cfg.profile,
            'model': cfg.model_main,
            'thinking': 'disabled' if cfg.provider == 'local' else cfg.think_main,
            'provider': cfg.provider,
            'task': task,
            'max_turns_main': cfg.max_turns_main,
            **asdict(result)
        }
        print(f'{MARK}{json.dumps(payload, ensure_ascii=False)}')
        if path:
            try:
                p = Path(path)
                _atomic_write(p, json.dumps(payload, indent=2, ensure_ascii=False))
            except OSError as e:
                print(f'[dump failed]: {e}')
        return
                                            
    def run(self, cfg = CONFIG) -> None:
        self.message = self._load_memory(cfg = cfg)
        client = OpenAI(
            api_key = cfg.api_key,
            base_url = cfg.base_url,
            max_retries = 0
        )
        pending_exits = False
        while True:
            try:
                user_input = input("\nPlease enter your command -> ")
            except KeyboardInterrupt:
                if not pending_exits:
                    print(f'Please click ctrl+c again to exit the program ')
                    pending_exits = True
                    continue
                print('\nBye!')
                self._save_memory(quiet = True)
                break
            except EOFError:
                print('\nBye!')
                self._save_memory(quiet = True)
                break

            if user_input.strip().lower() in ['quit', 'exit', 'bye']:
                self._save_memory()
                print('\nBye!')
                break

            self.message.append(
                {'role': 'user', 'content': user_input}
            )
            pending_exits = False
            executer = ToolExecution(self.regis, _ask_human, cfg = cfg)
            result = self._run_turn(client, executer, cfg = cfg)
            self._save_memory(quiet=True)
            print(
                f'[outcome]: {result.outcome}, [calls]: {result.calls}, [turns]: {result.turns}, [ok]: {result.ok}'
                f'[calls_tool]: {result.calls_by_tool}, [failed]: {result.failed_by_tag}'
                f'[last_prompt]: {result.last_prompt}, [last_prompt_tokens]: {result.prompt_total}, [completion_tokens]: {result.completion_total}'
                f'[wall]: {result.wall}'
                f'[err]: {result.err}'
            )
        return
                


# Backwards compatibility for existing upstream imports.
DeepSeekAgent = MiniHarnessAgent
