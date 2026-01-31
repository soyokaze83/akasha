"""Reply Agent service with tool calling support."""

import base64
import json
import logging
from enum import Enum
from typing import Literal, Optional

import dspy

from src.core.config import settings
from src.services.reply_agent.tools import OPENAI_TOOLS, web_search_tool

logger = logging.getLogger(__name__)


class ResponseState(Enum):
    """States for orchestrating LLM response handling."""

    NEEDS_TOOL_CALL = "needs_tool_call"  # Has tool calls to execute
    INTERMEDIARY = "intermediary"  # "Let me search..." type response
    FINAL_ANSWER = "final_answer"  # Actual complete answer


# DSPy signature for intermediary response classification
class IntermediaryClassifier(dspy.Signature):
    """Classify whether a chatbot response is an intermediary acknowledgment or an actual answer."""

    response_text: str = dspy.InputField(desc="The chatbot response text to classify")
    is_intermediary: Literal["yes", "no"] = dspy.OutputField(
        desc="'yes' if the response contains ANY promise to do something later or asks to wait "
        "(e.g., 'let me search', 'gimme a sec', 'give me a sec', 'I'll get back to you', "
        "'stay tuned', 'hold on', 'one moment', 'lemme check'). "
        "Answer 'yes' even if there is some acknowledgment text before the wait request. "
        "'no' ONLY if the response is a complete, final answer with no promises to return with more info."
    )


def _get_gemini_lm() -> dspy.LM:
    """Get Gemini LM for DSPy."""
    return dspy.LM(
        model=f"gemini/{settings.gemini_model}",
        api_key=settings.gemini_api_key.split(",")[0],  # Use first key
        temperature=0.0,
    )


def _get_openrouter_lm() -> dspy.LM:
    """Get OpenRouter LM for DSPy (fallback)."""
    return dspy.LM(
        model=f"openrouter/{settings.openrouter_model}",
        api_key=settings.openrouter_api_key,
        temperature=0.0,
    )

SYSTEM_INSTRUCTION = """You are Akasha, a helpful and friendly AI assistant available via WhatsApp.

Your capabilities:
- Answer questions on a wide range of topics
- Search the web for current information when needed
- Be concise since this is WhatsApp - keep responses under 500 words unless more detail is requested

Guidelines:
1. If asked about current events, recent news, or facts you're uncertain about, use the web_search tool
2. Be conversational and friendly
3. If you search the web, summarize the findings naturally - don't just list search results
4. Cite sources briefly when using web search (e.g., "According to [source]...")
5. If you can't help with something, say so politely
6. Respond in the same language as the user's query"""

REALISTIC_SYSTEM_INSTRUCTION = """You are Akasha, a friendly, relatable AI assistant on WhatsApp.

You're not a corporate robot—you chat like a real person: casual, honest, sometimes sarcastic or witty, but always chill and approachable. You can swear when it feels natural or adds punch to what you're saying, because real people do that. People message you because you feel like talking to a smart friend who doesn't judge and just gets it.

Your capabilities:
- Answer anything: everyday stuff, deep questions, relationships, sex, politics, memes, weird thoughts, whatever
- Search the web for up-to-date info when needed
- Keep replies short and natural—WhatsApp style. Under 500 words unless they ask for more detail

Guidelines:
1. For news, events, prices, scores, or anything time-sensitive, use the web_search tool. Don't guess.
2. Talk like a real person texting: no stiff "As an AI..." intros, use emojis when it fits 😏😂, slang if they're using it, swear if it fits the vibe, keep it flowing naturally.
3. When you search, summarize in your own words and weave it in casually. Mention sources lightly if it matters, like "Saw this on BBC..." or "Reddit's going nuts over this" or "Some blog claims...".
4. No heavy content filters beyond basic legality. Adult topics are fine if asked—be straightforward, no awkwardness.
5. If it's outside your abilities or against rules (no illegal stuff), just say politely "Sorry, can't help with that" or "That's a no from me".
6. Match their vibe: playful if they're playful, serious if serious, chill or spicy if that's the energy.
7. Be yourself—relaxed, fun, human. You're Akasha, their go-to chat buddy.
8. When you need to search the web, call the web_search tool immediately without announcing it. Never say "let me search", "gimme a sec", "I'll get back to you", or "stay tuned". Just search and respond with the answer directly. For complex queries, start working immediately without acknowledging the complexity."""


class ReplyAgentService:
    """Service for handling AI-powered replies with tool calling."""

    TRIGGER_PHRASE = "hey akasha,"
    MAX_TOOL_CALLS = 3
    MAX_ORCHESTRATION_ITERATIONS = 5  # Extra iterations for re-prompts

    def should_trigger(self, message: str) -> bool:
        """Check if message should trigger the agent."""
        return message.lower().startswith(self.TRIGGER_PHRASE)

    def extract_query(self, message: str) -> str:
        """Extract the user query after the trigger phrase."""
        return message[len(self.TRIGGER_PHRASE) :].strip()

    async def _is_intermediary_response(self, text: str) -> bool:
        """
        Use DSPy to determine if response is intermediary feedback.
        Falls back to OpenRouter if Gemini is exhausted.

        Args:
            text: The response text to classify

        Returns:
            True if intermediary, False if actual answer
        """
        import asyncio

        async def classify_with_lm(lm: dspy.LM) -> str:
            """Run classification with given LM."""
            dspy.configure(lm=lm)
            classifier = dspy.Predict(IntermediaryClassifier)

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: classifier(response_text=text[:500])
            )
            return result.is_intermediary

        try:
            # Try Gemini first
            gemini_lm = _get_gemini_lm()
            classification = await classify_with_lm(gemini_lm)

        except Exception as e:
            error_str = str(e).lower()
            is_fallback_worthy = (
                "429" in str(e)
                or "quota" in error_str
                or "rate" in error_str
                or "exhausted" in error_str
                or "503" in str(e)
                or "unavailable" in error_str
            )

            if (
                is_fallback_worthy
                and settings.llm_fallback_enabled
                and settings.openrouter_api_key
            ):
                logger.warning(
                    f"Gemini classifier failed ({type(e).__name__}), "
                    "falling back to OpenRouter"
                )
                try:
                    openrouter_lm = _get_openrouter_lm()
                    classification = await classify_with_lm(openrouter_lm)
                except Exception as fallback_e:
                    logger.warning(
                        f"OpenRouter fallback also failed: {fallback_e}, "
                        "defaulting to final_answer"
                    )
                    return False
            else:
                logger.warning(
                    f"Intermediary classification failed: {e}, "
                    "defaulting to final_answer"
                )
                return False

        is_intermediary = classification == "yes"
        logger.debug(
            f"DSPy intermediary classification: {classification} -> {is_intermediary}"
        )
        return is_intermediary

    async def _classify_response(self, text: str, has_tool_calls: bool) -> ResponseState:
        """
        Classify the LLM response into a state for orchestration.
        Uses DSPy-based classification to detect intermediary responses.

        Args:
            text: The response text from the LLM
            has_tool_calls: Whether the response contains tool calls

        Returns:
            ResponseState indicating what action to take next
        """
        if has_tool_calls:
            return ResponseState.NEEDS_TOOL_CALL

        if not text:
            return ResponseState.INTERMEDIARY  # Empty response, retry

        # Use DSPy to detect intermediary responses
        if await self._is_intermediary_response(text):
            return ResponseState.INTERMEDIARY

        return ResponseState.FINAL_ANSWER

    async def process_query(
        self,
        query: str,
        quoted_context: Optional[str] = None,
        image_data: Optional[bytes] = None,
        image_mime_type: Optional[str] = None,
    ) -> tuple[str, list[str]]:
        """
        Process a user query using the LLM with tool calling.

        Supports automatic fallback to alternate provider if primary is exhausted.
        Supports multimodal queries with images.

        Args:
            query: User's question/request
            quoted_context: Optional quoted message the user is replying to
            image_data: Optional image bytes for multimodal queries
            image_mime_type: MIME type of the image (e.g., "image/jpeg")

        Returns:
            Tuple of (response text, list of source URLs used)
        """
        # Build prompt with context if replying to a message
        if quoted_context:
            full_prompt = f"""The user is replying to this message:
---
{quoted_context}
---

User's question/comment: {query}"""
        else:
            full_prompt = query

        primary_provider = settings.llm_provider.lower()

        # Try primary provider first
        try:
            return await self._call_provider(
                primary_provider, full_prompt, image_data, image_mime_type
            )
        except Exception as e:
            error_str = str(e).lower()

            # Check if this is an error that warrants trying the fallback provider
            is_fallback_worthy_error = (
                # Rate limit / quota errors
                "429" in str(e)
                or "quota" in error_str
                or "rate" in error_str
                or "exhausted" in error_str
                or "all api keys" in error_str
                # Invalid/expired API key errors
                or "api_key_invalid" in error_str
                or "api key expired" in error_str
                or "invalid_argument" in error_str
                or "invalid api key" in error_str
                # SERVER OVERLOAD / UNAVAILABLE ERRORS
                or "503" in str(e)
                or "500" in error_str
                or "unavailable" in error_str
                or "overload" in error_str
                or "overloaded" in error_str
                or "internal error" in error_str
                or "temporarily unavailable" in error_str
            )

            # Fallback is always OpenRouter (text-only, no vision)
            if settings.llm_fallback_enabled and is_fallback_worthy_error:
                if self._can_use_provider("openrouter"):
                    if image_data:
                        logger.info(
                            "Stripping image data for OpenRouter fallback "
                            "(model does not support vision)"
                        )
                    logger.warning(
                        f"Primary provider '{primary_provider}' failed ({type(e).__name__}), "
                        f"falling back to 'openrouter'"
                    )
                    return await self._call_provider(
                        "openrouter", full_prompt, None, None
                    )

            # Re-raise if fallback not possible
            raise

    def _can_use_provider(self, provider: str) -> bool:
        """Check if a provider has valid API keys configured."""
        if provider == "openai":
            return bool(settings.openai_api_key)
        elif provider == "gemini":
            return bool(settings.gemini_api_key)
        elif provider == "openrouter":
            return bool(settings.openrouter_api_key)
        return False

    async def _call_provider(
        self,
        provider: str,
        prompt: str,
        image_data: Optional[bytes] = None,
        image_mime_type: Optional[str] = None,
    ) -> tuple[str, list[str]]:
        """Call the specified LLM provider."""
        if provider == "openai":
            return await self._process_with_openai(prompt, image_data, image_mime_type)
        elif provider == "gemini":
            return await self._process_with_gemini(prompt, image_data, image_mime_type)
        elif provider == "openrouter":
            return await self._process_with_openrouter(prompt)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    async def _process_with_openai(
        self,
        query: str,
        image_data: Optional[bytes] = None,
        image_mime_type: Optional[str] = None,
    ) -> tuple[str, list[str]]:
        """Process query using OpenAI with orchestrated tool calling.

        Uses a state machine to ensure we only return final answers,
        not intermediary feedback like "Let me search for that".
        """
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1", api_key=settings.openai_api_key
        )

        # Build user content - either simple text or multimodal with image
        if image_data and image_mime_type:
            b64_image = base64.b64encode(image_data).decode()
            user_content: list[dict] | str = [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image_mime_type};base64,{b64_image}"},
                },
                {"type": "text", "text": query},
            ]
            logger.info(
                f"OpenAI processing multimodal query with image ({image_mime_type})"
            )
        else:
            user_content = query

        messages: list[dict] = [
            {"role": "system", "content": REALISTIC_SYSTEM_INSTRUCTION},
            {"role": "user", "content": user_content},
        ]
        sources_used: list[str] = []
        tool_calls_made = 0

        # Orchestration loop - only exits when we have a validated final answer
        for iteration in range(self.MAX_ORCHESTRATION_ITERATIONS):
            # Disable tools after MAX_TOOL_CALLS to force text response
            use_tools = tool_calls_made < self.MAX_TOOL_CALLS

            response = await client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                tools=OPENAI_TOOLS if use_tools else None,
                tool_choice="auto" if use_tools else None,
                timeout=45.0,
            )

            assistant_message = response.choices[0].message
            has_tool_calls = bool(assistant_message.tool_calls)
            response_text = assistant_message.content or ""

            # Classify the response using state machine
            state = await self._classify_response(response_text, has_tool_calls)
            logger.debug(
                f"OpenAI iteration {iteration}: state={state.value}, "
                f"text_len={len(response_text)}, tool_calls={tool_calls_made}"
            )

            if state == ResponseState.NEEDS_TOOL_CALL:
                # Execute tool calls
                messages.append(assistant_message)
                tool_calls_made += 1

                for tool_call in assistant_message.tool_calls:
                    if tool_call.function.name == "web_search":
                        args = json.loads(tool_call.function.arguments)
                        search_query = args.get("query", "")

                        logger.info(f"OpenAI tool call: web_search('{search_query}')")
                        search_results = await web_search_tool.search(search_query)

                        for result in search_results:
                            sources_used.append(result["link"])

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": json.dumps(search_results),
                            }
                        )
                # Continue loop to get response with search results

            elif state == ResponseState.INTERMEDIARY:
                # Don't return intermediary feedback - prompt for actual answer
                logger.debug(
                    f"Detected intermediary response: {response_text[:80]}..."
                )
                messages.append(assistant_message)
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Don't tell me what you're going to do - "
                            "just do it and give me the answer directly."
                        ),
                    }
                )
                # Continue loop

            elif state == ResponseState.FINAL_ANSWER:
                # We have a real answer - return it
                return response_text, sources_used

        # Fallback: max iterations reached, force final response without tools
        logger.warning("OpenAI max orchestration iterations reached, forcing response")
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            timeout=45.0,
        )
        return response.choices[0].message.content or "", sources_used

    async def _process_with_gemini(
        self,
        query: str,
        image_data: Optional[bytes] = None,
        image_mime_type: Optional[str] = None,
    ) -> tuple[str, list[str]]:
        """Process query using Gemini with tool calling, key rotation, and optional image."""
        from google.genai import types
        from google.genai.errors import ClientError

        from src.llm.key_rotator import gemini_key_rotator

        sources_used: list[str] = []

        # Define tools for Gemini
        tools = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name="web_search",
                        description="Search the web for current information. Use this when you need up-to-date information, recent news, or facts you're not certain about.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "query": types.Schema(
                                    type=types.Type.STRING,
                                    description="The search query to look up",
                                )
                            },
                            required=["query"],
                        ),
                    )
                ]
            )
        ]

        # Build content parts - text only or multimodal with image
        parts: list[types.Part] = []
        if image_data and image_mime_type:
            parts.append(
                types.Part.from_bytes(data=image_data, mime_type=image_mime_type)
            )
            logger.info(
                f"Gemini processing multimodal query with image ({image_mime_type})"
            )
        parts.append(types.Part.from_text(text=query))

        contents: list[types.Content] = [types.Content(role="user", parts=parts)]

        async def call_with_rotation(config: types.GenerateContentConfig):
            """Make Gemini API call with automatic key rotation on errors."""
            num_keys = len(gemini_key_rotator._keys)
            last_error = None

            for attempt in range(num_keys):
                client = gemini_key_rotator.get_client()
                try:
                    return await client.aio.models.generate_content(
                        model=settings.gemini_model,
                        contents=contents,
                        config=config,
                    )
                except ClientError as e:
                    error_str = str(e).lower()
                    # Check if error warrants trying next key
                    is_rotatable_error = (
                        # Rate limit / quota errors
                        "429" in str(e)
                        or "quota" in error_str
                        or "rate" in error_str
                        or "exhausted" in error_str
                        or "all api keys" in error_str
                        # Invalid/expired API key errors
                        or "api_key_invalid" in error_str
                        or "api key expired" in error_str
                        or "invalid_argument" in error_str
                        or "invalid api key" in error_str
                        # SERVER OVERLOAD / UNAVAILABLE ERRORS
                        or "503" in str(e)
                        or "500" in error_str
                        or "unavailable" in error_str
                        or "overload" in error_str
                        or "overloaded" in error_str
                        or "internal error" in error_str
                        or "temporarily unavailable" in error_str
                    )

                    if is_rotatable_error:
                        last_error = e
                        logger.warning(
                            f"API key {attempt + 1}/{num_keys} failed ({str(e)[:50]}...), rotating..."
                        )
                        gemini_key_rotator.rotate()
                    else:
                        raise

            raise last_error or ClientError("All API keys exhausted")

        tool_calls_made = 0

        # Orchestration loop - only exits when we have a validated final answer
        for iteration in range(self.MAX_ORCHESTRATION_ITERATIONS):
            # Disable tools after MAX_TOOL_CALLS to force text response
            use_tools = tool_calls_made < self.MAX_TOOL_CALLS

            response = await call_with_rotation(
                types.GenerateContentConfig(
                    system_instruction=REALISTIC_SYSTEM_INSTRUCTION,
                    tools=tools if use_tools else None,
                )
            )

            candidate = response.candidates[0]

            # Check for function calls in response parts
            function_calls = []
            for part in candidate.content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    function_calls.append(part.function_call)

            has_tool_calls = bool(function_calls)
            response_text = response.text or ""

            # Classify the response using state machine
            state = await self._classify_response(response_text, has_tool_calls)
            logger.debug(
                f"Gemini iteration {iteration}: state={state.value}, "
                f"text_len={len(response_text)}, tool_calls={tool_calls_made}"
            )

            if state == ResponseState.NEEDS_TOOL_CALL:
                # Execute tool calls
                contents.append(candidate.content)
                tool_calls_made += 1

                function_responses = []
                for fc in function_calls:
                    if fc.name == "web_search":
                        search_query = fc.args.get("query", "")

                        logger.info(f"Gemini tool call: web_search('{search_query}')")
                        search_results = await web_search_tool.search(search_query)

                        for result in search_results:
                            sources_used.append(result["link"])

                        function_responses.append(
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name="web_search",
                                    response={"results": search_results},
                                )
                            )
                        )

                contents.append(types.Content(role="user", parts=function_responses))
                # Continue loop to get response with search results

            elif state == ResponseState.INTERMEDIARY:
                # Don't return intermediary feedback - prompt for actual answer
                logger.debug(
                    f"Detected intermediary response: {response_text[:80]}..."
                )
                contents.append(candidate.content)
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(
                                text=(
                                    "Don't tell me what you're going to do - "
                                    "just do it and give me the answer directly."
                                )
                            )
                        ],
                    )
                )
                # Continue loop

            elif state == ResponseState.FINAL_ANSWER:
                # We have a real answer - return it
                return response_text, sources_used

        # Fallback: max iterations reached, force final response without tools
        logger.warning("Gemini max orchestration iterations reached, forcing response")
        response = await call_with_rotation(
            types.GenerateContentConfig(
                system_instruction=REALISTIC_SYSTEM_INSTRUCTION,
            )
        )
        return response.text or "", sources_used

    async def _process_with_openrouter(
        self,
        query: str,
    ) -> tuple[str, list[str]]:
        """Process query using OpenRouter fallback (text-only, with tool calling).

        Uses the same OpenAI-compatible API format but with dedicated
        OpenRouter credentials. No vision/image support.
        """
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
        )

        messages: list[dict] = [
            {"role": "system", "content": REALISTIC_SYSTEM_INSTRUCTION},
            {"role": "user", "content": query},
        ]
        sources_used: list[str] = []
        tool_calls_made = 0

        for iteration in range(self.MAX_ORCHESTRATION_ITERATIONS):
            use_tools = tool_calls_made < self.MAX_TOOL_CALLS

            response = await client.chat.completions.create(
                model=settings.openrouter_model,
                messages=messages,
                tools=OPENAI_TOOLS if use_tools else None,
                tool_choice="auto" if use_tools else None,
                timeout=45.0,
            )

            assistant_message = response.choices[0].message
            has_tool_calls = bool(assistant_message.tool_calls)
            response_text = assistant_message.content or ""

            state = await self._classify_response(response_text, has_tool_calls)
            logger.debug(
                f"OpenRouter iteration {iteration}: state={state.value}, "
                f"text_len={len(response_text)}, tool_calls={tool_calls_made}"
            )

            if state == ResponseState.NEEDS_TOOL_CALL:
                messages.append(assistant_message)
                tool_calls_made += 1

                for tool_call in assistant_message.tool_calls:
                    if tool_call.function.name == "web_search":
                        args = json.loads(tool_call.function.arguments)
                        search_query = args.get("query", "")

                        logger.info(
                            f"OpenRouter tool call: web_search('{search_query}')"
                        )
                        search_results = await web_search_tool.search(search_query)

                        for result in search_results:
                            sources_used.append(result["link"])

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": json.dumps(search_results),
                            }
                        )

            elif state == ResponseState.INTERMEDIARY:
                logger.debug(
                    f"Detected intermediary response: {response_text[:80]}..."
                )
                messages.append(assistant_message)
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Don't tell me what you're going to do - "
                            "just do it and give me the answer directly."
                        ),
                    }
                )

            elif state == ResponseState.FINAL_ANSWER:
                return response_text, sources_used

        # Max iterations reached
        logger.warning(
            "OpenRouter max orchestration iterations reached, forcing response"
        )
        response = await client.chat.completions.create(
            model=settings.openrouter_model,
            messages=messages,
            timeout=45.0,
        )
        return response.choices[0].message.content or "", sources_used


# Singleton instance
reply_agent = ReplyAgentService()
