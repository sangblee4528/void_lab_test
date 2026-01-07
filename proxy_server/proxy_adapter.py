"""
proxy_adapter.py - 모델별 호출 규격 변환 로직

Void에서 받은 요청을 Ollama API 규격으로 변환하고,
Ollama 응답을 Void가 이해할 수 있는 형식으로 변환합니다.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
import sys

# 현재 디렉토리 경로 추가
sys.path.append(str(Path(__file__).parent))
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# 프롬프트 설정 경로
PROMPT_CONFIG_PATH = Path(__file__).parent / "proxy_config" / "prompt_config.json"


class OllamaAdapter:
    """Ollama API 규격 변환 어댑터"""
    
    @staticmethod
    def convert_to_ollama_request(
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: str = "qwen2.5-coder:7b",
        stream: bool = False
    ) -> Dict[str, Any]:
        """
        OpenAI 형식의 요청을 Ollama API 형식으로 변환합니다.
        
        Args:
            messages: 대화 메시지 목록 (OpenAI 형식)
            tools: 사용 가능한 도구 목록
            model: 사용할 모델 이름
            stream: 스트리밍 여부
            
        Returns:
            Dict: Ollama API 요청 형식
        """
        logger.info(f"[Adapter] OpenAI → Ollama(OpenAI) 변환 시작")
        logger.debug(f"[Adapter] 원본 메시지: {json.dumps(messages, ensure_ascii=False, indent=2)}")
        
        # [상세 코멘트: 설정 파일을 이용한 시스템 프롬프트 주입]
        # 외부 prompt_config.json 파일을 로드하여 도구 사용 권장 힌트를 주입합니다.
        injected_messages = messages
        if tools and PROMPT_CONFIG_PATH.exists():
            try:
                with open(PROMPT_CONFIG_PATH, "r", encoding="utf-8") as f:
                    p_config = json.load(f)
                
                hint_cfg = p_config.get("system_hint", {})
                if hint_cfg.get("enabled", False):
                    tool_names = ", ".join([t.get('function', {}).get('name', 'tool') for t in tools])
                    raw_hint = hint_cfg.get("content", "")
                    
                    # 리스트 형식이면 개행문자로 합침, 문자열이면 그대로 사용
                    if isinstance(raw_hint, list):
                        raw_hint = "\n".join(raw_hint)
                        
                    tool_hint = raw_hint.replace("{tool_names}", tool_names)
                    
                    # 새로운 메시지 리스트 생성 (기존 메시지 변경 방지)
                    new_messages = []
                    system_msg_found = False
                    for msg in messages:
                        m = msg.copy()
                        if m.get("role") == "system" and not system_msg_found:
                            m["content"] = (m.get("content") or "") + tool_hint
                            system_msg_found = True
                        new_messages.append(m)
                    
                    if not system_msg_found:
                        new_messages.insert(0, {"role": "system", "content": tool_hint})
                    
                    injected_messages = new_messages
                    logger.info("[Adapter] 외부 설정을 통해 시스템 프롬프트 힌트 주입 완료")
            except Exception as e:
                logger.error(f"[Adapter] 프롬프트 설정 로드 중 에러: {e}")

        # OpenAI 호환 형식으로 구성
        ollama_request = {
            "model": model,
            "messages": injected_messages,
            "stream": stream,
            "temperature": 0.7,
            "max_tokens": 1024
        }
        
        # 도구가 있으면 추가
        if tools:
            ollama_request["tools"] = tools
            # [상세 코멘트: 도구 추출을 위한 스트리밍 비활성화]
            # Void IDE는 스트리밍 중에도 도구 호출이 텍스트로 오면 감지하지 못합니다.
            # 8000번 프록시에서 텍스트 기반 도구 추출(Fallback)을 수행하려면 응답을 한 번에 다 받아야 하므로
            # 도구 목록이 포함된 요청에서는 강제로 stream을 False로 설정합니다.
            ollama_request["stream"] = False
            logger.info(f"[Adapter] 도구 {len(tools)}개 포함됨 (텍스트 추출을 위해 스트리밍 비활성화)")
        
        logger.info(f"[Adapter] Ollama 요청 변환 완료")
        return ollama_request
    
    @staticmethod
    def convert_from_ollama_response(
        ollama_response: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Ollama API 응답을 OpenAI 형식으로 변환합니다.
        
        Args:
            ollama_response: Ollama API 응답
            
        Returns:
            Dict: OpenAI 형식의 응답
        """
        logger.info(f"[Adapter] Ollama → OpenAI 변환 시작")
        # [상세 코멘트: 원본 응답 확인]
        # 모델이 실제로 보낸 '날것'의 응답을 확인하기 위해 로그 레벨을 INFO로 설정합니다.
        logger.info(f"[Adapter] [RAW] Ollama 원본 응답: {json.dumps(ollama_response, ensure_ascii=False, indent=2)}")
        
        # [상세 코멘트: 응답 포맷 대응]
        # Ollama 네이티브 API는 'message'를 직접 반환하지만, 
        # OpenAI 호환 API(/v1/)는 'choices[0].message' 구조를 갖습니다.
        # 두 경우를 모두 지원하도록 로직을 구성합니다.
        message = ollama_response.get("message")
        if not message:
            choices = ollama_response.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
            else:
                message = {}
        
        content = message.get("content", "")
        tool_calls = message.get("tool_calls", [])
        
        # [상세 코멘트: 도구 호출 추출 폴백 로직]
        # 모델(예: Qwen 2.5)이 정식 tool_calls 필드 대신 일반 텍스트(content) 안에 JSON으로 도구 정보를 보낼 때가 있습니다.
        # 이 경우 Void IDE는 이를 도구로 인식하지 못하므로, 프록시 레벨에서 content를 뒤져서 JSON을 찾아냅니다.
        if not tool_calls and content:
            # _try_extract_json_tool_call()를 호출하여 JSON 패턴(직접 JSON 혹은 ```json 블록)을 찾습니다.
            json_match = re.search(r"```json\s*([\s\S]*?)\s*```", content)
            if json_match:
                extracted = OllamaAdapter._try_extract_json_tool_call(json_match.group(0))
                if extracted:
                    tool_calls = extracted
                    # content에서 추출된 JSON 블록을 제거하여 Void가 'Apply' 버튼을 보여주지 않게 함
                    # 정규식으로 더 확실하게 제거
                    content = re.sub(r"```json\s*[\s\S]*?\s*```", "", content).strip()
                    logger.info(f"[Adapter] 💡 텍스트 코드 블록에서 도구 호출 추출 및 본문 정제 완료")
            elif content.strip().startswith("{") and content.strip().endswith("}"):
                extracted = OllamaAdapter._try_extract_json_tool_call(content)
                if extracted:
                    tool_calls = extracted
                    content = "" # 전체가 JSON이면 본문 비움
                    logger.info(f"[Adapter] 💡 전체 텍스트에서 도구 호출 추출 완료")

        openai_response = {
            "id": ollama_response.get("id") or f"chatcmpl-{ollama_response.get('created_at', 'unknown')}",
            "object": "chat.completion",
            "created": ollama_response.get("created") or ollama_response.get("created_at"),
            "model": ollama_response.get("model"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": message.get("role", "assistant"),
                        # 도구 호출이 있을 때 content가 ""이면 Void가 'Empty response'로 오해할 수 있음
                        # 도구 호출이 있더라도 원본 content를 유지하거나, 최소한 빈 문자열("")로 처리
                        # 내용이 아예 없으면 Void가 메시지 자체를 씹어버리는(숨기는) 현상 방지
                        "content": content if not tool_calls else (content or "🛠️ 도구 호출을 생성했습니다.")
                    },
                    "finish_reason": ollama_response.get("finish_reason") or "stop"
                }
            ],
            "usage": ollama_response.get("usage") or {
                "prompt_tokens": ollama_response.get("prompt_eval_count", 0),
                "completion_tokens": ollama_response.get("eval_count", 0),
                "total_tokens": (
                    ollama_response.get("prompt_eval_count", 0) + 
                    ollama_response.get("eval_count", 0)
                )
            }
        }
        
        # tool_calls가 있으면 추가 및 finish_reason 변경
        # [Plan B] 도구 호출을 쉘 명령어로 변환하여 Content에 주입
        # Void가 도구 호출 JSON은 무시하지만, 쉘 명령어 코드는 인식하여 Run 버튼을 띄우는 점을 이용
        if tool_calls:
            logger.info(f"[Adapter] 🔧 도구 호출을 쉘 명령어로 변환 (Plan B): {len(tool_calls)}건")
            
            command_lines = []
            for tool in tool_calls:
                fn_name = tool["function"]["name"]
                fn_args = tool["function"]["arguments"]
                
                # 인자 이스케이프 처리
                escaped_args = fn_args.replace("'", "'\\''")
                cmd = f"python mcp_server/mcp_tools_runner.py {fn_name} '{escaped_args}'"
                command_lines.append(f"```bash\n{cmd}\n```")
            
            # 본문에 쉘 명령어 추가
            # 이미 placeholder 텍스트가 있을 수 있으므로 체크
            base_content = content if content else "🛠️ 도구 실행을 준비했습니다:"
            openai_response["choices"][0]["message"]["content"] = base_content + "\n\n" + "\n".join(command_lines)
            
            # 중요: 도구 호출 필드는 비웁니다. Void가 도구 호출 UI 대신 쉘 UI를 쓰도록 유도
            # openai_response["choices"][0]["message"]["tool_calls"] = tool_calls
            # openai_response["choices"][0]["finish_reason"] = "tool_calls"
            
            # finish_reason은 stop으로 유지
            openai_response["choices"][0]["finish_reason"] = "stop"
        
        logger.info(f"[Adapter] OpenAI 응답 변환 완료")
        return openai_response

    @staticmethod
    def _try_extract_json_tool_call(content: str) -> Optional[List[Dict[str, Any]]]:
        """
        [상세 코멘트: 텍스트 내 JSON 추출기]
        모델이 답변 메시지 안에 섞어 보낸 도구 호출 정보를 정규표현식으로 찾아냅니다.
        
        1순위: ```json ... ``` 형태의 마크다운 코드 블록
        2순위: 메시지 전체가 { ... } 또는 [ ... ] 인 경우
        """
        content = content.strip()
        
        # 1. 마크다운 코드 블록 내부의 JSON을 먼저 찾습니다. (가장 흔한 케이스)
        # re.DOTALL을 지원하기 위해 [\s\S]*? 패턴을 사용합니다.
        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", content)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # 2. 코드 블록이 없다면 전체 텍스트가 { 로 시작해서 } 로 끝나는지 확인합니다.
            if content.startswith("{") and content.endswith("}"):
                json_str = content
            else:
                return None
        
        try:
            data = json.loads(json_str)
            
            # 케이스 A: 단일 도구 호출 객체인 경우 (Qwen 스타일)
            # { "name": "...", "arguments": { ... } }
            if isinstance(data, dict):
                if "name" in data and "arguments" in data:
                    return [{
                        "index": 0,
                        "id": f"call_{datetime.now().strftime('%M%S%f')}", # Void 인식용 ID 생성
                        "type": "function", # OpenAI 규격 고정
                        "function": {
                            "name": data["name"],
                            # arguments는 반드시 JSON 문자열 형태여야 합니다.
                            "arguments": json.dumps(data["arguments"], ensure_ascii=False) if isinstance(data["arguments"], dict) else data["arguments"]
                        }
                    }]
            
            # 케이스 B: 리스트 형태의 도구 호출인 경우 (OpenAI 스타일을 텍스트로 보낸 경우)
            # [{ "name": "...", "arguments": { ... } }, ...]
            elif isinstance(data, list):
                valid_calls = []
                for idx, item in enumerate(data):
                    if isinstance(item, dict) and "name" in item:
                        valid_calls.append({
                            "index": idx,  # OpenAI 스트리밍 규격에서는 index가 필수입니다.
                            "id": f"call_{idx}_{datetime.now().strftime('%M%S%f')}",
                            "type": "function",
                            "function": {
                                "name": item["name"],
                                "arguments": json.dumps(item.get("arguments", {}), ensure_ascii=False)
                            }
                        })
                return valid_calls if valid_calls else None
        except Exception as e:
            # JSON 파싱 실패 시 무시하고 일반 텍스트로 처리하게 둡니다.
            logger.debug(f"[Adapter] JSON 추출 실패: {str(e)}")
            
        return None

    @staticmethod
    def convert_chunk_from_ollama(
        ollama_chunk: Dict[str, Any]
    ) -> str:
        """
        Ollama 스트리밍 청크를 OpenAI SSE 형식으로 변환합니다.
        
        Args:
            ollama_chunk: Ollama API의 한 청크
            
        Returns:
            str: "data: {...}\n\n" 형식의 문자열
        """
        choices = ollama_chunk.get("choices", [])
        if not choices:
            return ""
            
        choice = choices[0]
        delta = choice.get("delta", {})
        
        openai_chunk = {
            "id": ollama_chunk.get("id", f"chatcmpl-{datetime.now().strftime('%Y%M%S%f')}"),
            "object": "chat.completion.chunk",
            "created": ollama_chunk.get("created"),
            "model": ollama_chunk.get("model"),
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": choice.get("finish_reason")
                }
            ]
        }
        
        return f"data: {json.dumps(openai_chunk, ensure_ascii=False)}\n\n"

    @staticmethod
    def convert_to_chunk_from_full_response(
        openai_response: Dict[str, Any]
    ) -> List[str]:
        """
        [상세 코멘트: 풀 응답 → 스트리밍 청크 변환]
        도구 추출을 위해 강제로 비스트리밍 모드를 사용했을 때,
        원래 스트리밍을 기대하던 클라이언트(Void)를 위해 결과를 여러 SSE 청크로 나누어 포장합니다.
        본문(content)과 도구 호출(tool_calls)을 분리하여 전달하여 Void의 인식률을 높입니다.
        """
        choices = openai_response.get("choices", [])
        if not choices:
            return []
            return []
            
        choice = choices[0]
        message = choice.get("message", {})
        common_header = {
            "id": openai_response.get("id"),
            "object": "chat.completion.chunk",
            "created": openai_response.get("created"),
            "model": openai_response.get("model"),
        }
        
        chunks = []
        
        # 1. 역할(Role)과 본문(Content) 전송
        content_chunk = common_header.copy()
        content_chunk["choices"] = [{
            "index": 0,
            "delta": {
                "role": message.get("role"),
                "content": message.get("content")
            },
            "finish_reason": None
        }]
        chunks.append(f"data: {json.dumps(content_chunk, ensure_ascii=False)}\n\n")
        
        # 2. 도구 호출(Tool Calls) 전송 (있을 경우만)
        # 2. 도구 호출(Tool Calls) 전송 (있을 경우만)
        if message.get("tool_calls"):
            tool_chunk = common_header.copy()
            tool_chunk["choices"] = [{
                "index": 0,
                "delta": {
                    "tool_calls": message.get("tool_calls")
                },
                "finish_reason": "stop"
            }]
            chunks.append(f"data: {json.dumps(tool_chunk, ensure_ascii=False)}\n\n")
        else:
            # 도구가 없으면 마지막에 finish_reason: stop 추가
            stop_chunk = common_header.copy()
            stop_chunk["choices"] = [{
                "index": 0,
                "delta": {},
                "finish_reason": choice.get("finish_reason") or "stop"
            }]
            chunks.append(f"data: {json.dumps(stop_chunk, ensure_ascii=False)}\n\n")
            
        return chunks
    
    @staticmethod
    def extract_tool_calls(
        response: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        응답에서 도구 호출 정보를 추출합니다.
        
        Args:
            response: OpenAI 형식의 응답
            
        Returns:
            List[Dict]: 도구 호출 목록
        """
        tool_calls = []
        
        try:
            choices = response.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                tool_calls = message.get("tool_calls", [])
                
                logger.info(f"[Adapter] 추출된 도구 호출: {len(tool_calls)}건")
                
        except Exception as e:
            logger.error(f"[Adapter] 도구 호출 추출 실패: {e}")
        
        return tool_calls


class RequestValidator:
    """요청 유효성 검증 클래스"""
    
    @staticmethod
    def validate_chat_request(request: Dict[str, Any]) -> tuple[bool, str]:
        """
        채팅 요청의 유효성을 검증합니다.
        
        Args:
            request: 검증할 요청
            
        Returns:
            tuple[bool, str]: (유효성 여부, 오류 메시지)
        """
        # messages 필드 확인
        if "messages" not in request:
            return False, "messages 필드가 필요합니다"
        
        messages = request["messages"]
        if not isinstance(messages, list):
            return False, "messages는 배열이어야 합니다"
        
        if len(messages) == 0:
            return False, "최소 하나의 메시지가 필요합니다"
        
        # 각 메시지 검증
        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                return False, f"메시지 {i}는 객체여야 합니다"
            
            if "role" not in msg:
                return False, f"메시지 {i}에 role이 없습니다"
            
            if "content" not in msg and "tool_calls" not in msg:
                return False, f"메시지 {i}에 content 또는 tool_calls가 필요합니다"
        
        logger.info("[Validator] 요청 유효성 검증 통과")
        return True, ""
    
    @staticmethod
    def validate_tools(tools: List[Dict[str, Any]]) -> tuple[bool, str]:
        """
        도구 목록의 유효성을 검증합니다.
        
        Args:
            tools: 검증할 도구 목록
            
        Returns:
            tuple[bool, str]: (유효성 여부, 오류 메시지)
        """
        if not isinstance(tools, list):
            return False, "tools는 배열이어야 합니다"
        
        for i, tool in enumerate(tools):
            if "type" not in tool:
                return False, f"도구 {i}에 type이 없습니다"
            
            if tool["type"] == "function":
                if "function" not in tool:
                    return False, f"도구 {i}에 function 정의가 없습니다"
                
                func = tool["function"]
                if "name" not in func:
                    return False, f"도구 {i}에 함수 이름이 없습니다"
        
        logger.info(f"[Validator] 도구 유효성 검증 통과: {len(tools)}개")
        return True, ""
